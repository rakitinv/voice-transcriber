import { AudioSource, ExtensionSettings } from "../settings/storage";
import { AudioWebSocketClient } from "../websocket/client";

export type RecorderState = "idle" | "recording";

export interface RecorderConfig {
  settings: ExtensionSettings;
  conversationId: string;
  /** First sync hook when stop begins (before MediaRecorder.stop / upload). */
  onBeforeStop?: () => void;
  /** Called after a successful transition to idle (upload + cleanup), e.g. tab capture tab closed. */
  onAfterStop?: () => void;
}

export class AudioRecorderController {
  private mediaStream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private wsClient: AudioWebSocketClient | null = null;
  private monitorAudioContext: AudioContext | null = null;
  private monitorSourceNode: MediaStreamAudioSourceNode | null = null;
  private recordedParts: BlobPart[] = [];
  private recordMimeType: string = "audio/webm";
  private state: RecorderState = "idle";
  private config: RecorderConfig | null = null;
  private tabTrackEndedHandler: (() => void) | null = null;
  /** Tab + mic streams mixed via AudioContext (stopped explicitly on cleanup). */
  private dualSourceStreams: MediaStream[] | null = null;

  getState(): RecorderState {
    return this.state;
  }

  async start(config: RecorderConfig): Promise<void> {
    if (this.state === "recording") return;
    this.config = config;
    this.recordedParts = [];
    this.dualSourceStreams = null;

    this.mediaStream = await this.getStream(config.settings.audioSource);
    if (!this.mediaStream) throw new Error("Unable to acquire audio stream");

    const attachTabEnded = (tabStream: MediaStream) => {
      this.tabTrackEndedHandler = () => {
        if (this.state === "recording") {
          void this.stop();
        }
      };
      for (const track of tabStream.getAudioTracks()) {
        track.addEventListener("ended", this.tabTrackEndedHandler!);
      }
    };

    if (config.settings.audioSource === "tab") {
      attachTabEnded(this.mediaStream);
    } else if (config.settings.audioSource === "dual" && this.dualSourceStreams?.[0]) {
      attachTabEnded(this.dualSourceStreams[0]);
    }

    // Tab capture often stops audible playback in the tab unless we locally monitor the stream.
    if (config.settings.audioSource === "tab") {
      try {
        const ctx = new AudioContext();
        const src = ctx.createMediaStreamSource(this.mediaStream);
        src.connect(ctx.destination);
        this.monitorAudioContext = ctx;
        this.monitorSourceNode = src;
        if (ctx.state === "suspended") {
          await ctx.resume();
        }
      } catch {
        // Monitoring is best-effort; recording can still proceed.
      }
    }

    this.wsClient = new AudioWebSocketClient(config.settings, config.conversationId);
    this.wsClient.connect();
    try {
      await this.wsClient.waitUntilOpen();
    } catch (e) {
      this.wsClient.close();
      this.wsClient = null;
      throw e;
    }

    const options: MediaRecorderOptions = {
      mimeType: "audio/webm;codecs=opus",
    };
    if (!MediaRecorder.isTypeSupported(options.mimeType)) {
      // Fall back to browser default; server upload resolver can still treat it as webm via audio_format query.
      delete (options as { mimeType?: string }).mimeType;
    }
    this.recordMimeType = options.mimeType ?? "audio/webm";
    this.mediaRecorder = new MediaRecorder(this.mediaStream, options);

    const timeslice = Math.min(
      Math.max(config.settings.chunkSizeMs, 500),
      2000
    ); // clamp to 500–2000

    this.mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0 && this.wsClient) {
        this.recordedParts.push(event.data);
        this.wsClient.sendChunk(event.data);
      }
    };

    this.mediaRecorder.start(timeslice);
    this.state = "recording";
  }

  async stop(): Promise<void> {
    if (this.state !== "recording") return;

    const cfg = this.config;
    cfg?.onBeforeStop?.();
    const afterStop = cfg?.onAfterStop;
    const ws = this.wsClient;
    const recorder = this.mediaRecorder;
    const stream = this.mediaStream;

    await new Promise<void>((resolve) => {
      if (!recorder) return resolve();
      recorder.addEventListener(
        "stop",
        () => {
          resolve();
        },
        { once: true }
      );
      try {
        recorder.stop();
      } catch {
        resolve();
      }
    });

    this.mediaRecorder = null;

    if (stream) {
      if (this.tabTrackEndedHandler) {
        const tabLike =
          this.dualSourceStreams?.[0] ??
          (this.config?.settings.audioSource === "tab" ? stream : null);
        if (tabLike) {
          for (const track of tabLike.getAudioTracks()) {
            track.removeEventListener("ended", this.tabTrackEndedHandler);
          }
        }
        this.tabTrackEndedHandler = null;
      }
      stream.getTracks().forEach((t) => t.stop());
    }
    this.mediaStream = null;

    if (this.dualSourceStreams) {
      for (const s of this.dualSourceStreams) {
        s.getTracks().forEach((t) => t.stop());
      }
      this.dualSourceStreams = null;
    }

    try {
      this.monitorSourceNode?.disconnect();
    } catch {
      // ignore
    }
    this.monitorSourceNode = null;
    try {
      await this.monitorAudioContext?.close();
    } catch {
      // ignore
    }
    this.monitorAudioContext = null;

    if (ws) {
      ws.close();
    }
    this.wsClient = null;

    this.state = "idle";

    // Persist a single audio object for the conversation (WebUI download / worker ASR pipeline).
    if (cfg && this.recordedParts.length > 0) {
      const blob = new Blob(this.recordedParts, { type: this.recordMimeType });
      await this.uploadRecordingBlob(cfg, blob);
    }

    this.recordedParts = [];
    this.config = null;

    afterStop?.();
  }

  private async uploadRecordingBlob(config: RecorderConfig, blob: Blob): Promise<void> {
    const url = new URL(`${config.settings.serverUrl.replace(/\/+$/, "")}/api/upload`);
    url.searchParams.set("conversation_id", config.conversationId);
    url.searchParams.set("audio_format", "webm");

    const form = new FormData();
    form.append("file", blob, "recording.webm");

    const headers: Record<string, string> | undefined = config.settings.accessToken
      ? { Authorization: `Bearer ${config.settings.accessToken}` }
      : undefined;

    const res = await fetch(url.toString(), { method: "POST", headers, body: form });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Загрузка не удалась: ${res.status} ${text}`);
    }
  }

  private async getStream(source: AudioSource): Promise<MediaStream> {
    if (source === "dual") {
      const tabStream = await this.getStream("tab");
      const micStream = await this.getStream("microphone");
      this.dualSourceStreams = [tabStream, micStream];
      const ctx = new AudioContext();
      const dest = ctx.createMediaStreamDestination();
      const tabSrc = ctx.createMediaStreamSource(tabStream);
      const micSrc = ctx.createMediaStreamSource(micStream);
      tabSrc.connect(dest);
      micSrc.connect(dest);
      try {
        tabSrc.connect(ctx.destination);
      } catch {
        // Monitoring is best-effort.
      }
      this.monitorAudioContext = ctx;
      this.monitorSourceNode = tabSrc;
      if (ctx.state === "suspended") {
        await ctx.resume();
      }
      return dest.stream;
    }

    if (source === "microphone") {
      try {
        return await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
        });
      } catch (e) {
        const name = e && typeof e === "object" && "name" in e ? String((e as { name?: unknown }).name) : "";
        const msg = e instanceof Error ? e.message : String(e);
        if (name === "NotAllowedError" || /Permission dismissed/i.test(msg)) {
          throw new Error(
            "Доступ к микрофону запрещён или закрыт. Нажмите «Начать запись» снова и разрешите микрофон для всплывающего окна расширения. " +
              "Если Chrome не показывает запрос, откройте chrome://settings/content/siteDetails?site=chrome-extension://" +
              chrome.runtime.id +
              " и установите для микрофона «Разрешить»."
          );
        }
        throw new Error(`Ошибка микрофона: ${msg}`);
      }
    }

    // Tab / system audio require additional permissions and APIs.
    // Here we keep minimal stubs and rely on tabCapture for tab audio.
    if (source === "tab") {
      // Tab capture
      return new Promise<MediaStream>((resolve, reject) => {
        if (!chrome.tabCapture) {
          reject(new Error("API tabCapture недоступен"));
          return;
        }
        chrome.tabCapture.capture({ audio: true, video: false }, (stream) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message ?? "Ошибка tabCapture"));
            return;
          }
          if (!stream) {
            reject(
              new Error(
                "Не удалось захватить звук вкладки (часто: доступ закрыт или у активной вкладки нет звука для захвата). Повторите на обычной странице со звуком или выберите источник «Микрофон»."
              )
            );
          } else {
            resolve(stream);
          }
        });
      });
    }

    // System audio capture is browser/OS dependent; left as a placeholder.
    throw new Error("Захват системного звука не реализован");
  }
}

