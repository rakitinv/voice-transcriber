import { AudioSource, ExtensionSettings } from "../settings/storage";
import { AudioWebSocketClient } from "../websocket/client";

export type RecorderState = "idle" | "recording";

export interface RecorderConfig {
  settings: ExtensionSettings;
  conversationId: string;
}

export class AudioRecorderController {
  private mediaStream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private wsClient: AudioWebSocketClient | null = null;
  private state: RecorderState = "idle";
  private config: RecorderConfig | null = null;

  getState(): RecorderState {
    return this.state;
  }

  async start(config: RecorderConfig): Promise<void> {
    if (this.state === "recording") return;
    this.config = config;

    this.mediaStream = await this.getStream(config.settings.audioSource);
    if (!this.mediaStream) throw new Error("Unable to acquire audio stream");

    this.wsClient = new AudioWebSocketClient(config.settings, config.conversationId);
    this.wsClient.connect();

    const options: MediaRecorderOptions = {
      mimeType: "audio/webm;codecs=opus",
    };
    this.mediaRecorder = new MediaRecorder(this.mediaStream, options);

    const timeslice = Math.min(
      Math.max(config.settings.chunkSizeMs, 500),
      2000
    ); // clamp to 500–2000

    this.mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0 && this.wsClient) {
        this.wsClient.sendChunk(event.data);
      }
    };

    this.mediaRecorder.start(timeslice);
    this.state = "recording";
  }

  stop(): void {
    if (this.mediaRecorder && this.state === "recording") {
      this.mediaRecorder.stop();
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
    }
    this.mediaRecorder = null;
    this.mediaStream = null;

    if (this.wsClient) {
      this.wsClient.close();
      this.wsClient = null;
    }

    this.state = "idle";
  }

  private async getStream(source: AudioSource): Promise<MediaStream> {
    if (source === "microphone") {
      return navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    }

    // Tab / system audio require additional permissions and APIs.
    // Here we keep minimal stubs and rely on tabCapture for tab audio.
    if (source === "tab") {
      // Tab capture
      return new Promise<MediaStream>((resolve, reject) => {
        if (!chrome.tabCapture) {
          reject(new Error("tabCapture API not available"));
          return;
        }
        chrome.tabCapture.capture({ audio: true, video: false }, (stream) => {
          if (!stream) {
            reject(new Error("Failed to capture tab audio"));
          } else {
            resolve(stream);
          }
        });
      });
    }

    // System audio capture is browser/OS dependent; left as a placeholder.
    throw new Error("System audio capture not implemented");
  }
}

