import { useCallback, useEffect, useRef, useState } from "react";

function pickRecorderMimeType(): string | undefined {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];
  for (const c of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c)) {
      return c;
    }
  }
  return undefined;
}

function extensionForMime(mime: string): string {
  const m = mime.toLowerCase();
  if (m.includes("webm")) return "webm";
  if (m.includes("ogg")) return "ogg";
  if (m.includes("mp4") || m.includes("m4a") || m.includes("aac")) return "m4a";
  return "webm";
}

/**
 * Запись с микрофона в один Blob/File (MediaRecorder), без realtime WS —
 * после остановки файл передаётся в тот же POST /api/upload, что и внешний файл.
 */
export function useMicrophoneRecorder() {
  const [isRecording, setIsRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const startRecording = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      throw new Error("Запись с микрофона не поддерживается в этом браузере.");
    }
    if (typeof MediaRecorder === "undefined") {
      throw new Error("MediaRecorder не поддерживается в этом браузере.");
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    chunksRef.current = [];

    const mimeType = pickRecorderMimeType();
    const recorder = new MediaRecorder(
      stream,
      mimeType ? { mimeType } : undefined
    );

    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data && e.data.size > 0) {
        chunksRef.current.push(e.data);
      }
    };

    recorderRef.current = recorder;
    recorder.start(250);
    setIsRecording(true);
  }, []);

  const stopRecording = useCallback(async (): Promise<File> => {
    const recorder = recorderRef.current;
    if (!recorder) {
      stopStream();
      setIsRecording(false);
      throw new Error("Запись не была запущена.");
    }

    const effectiveMime =
      recorder.mimeType ||
      pickRecorderMimeType() ||
      "audio/webm";

    return new Promise((resolve, reject) => {
      recorder.onerror = () => {
        recorder.onstop = null;
        recorder.onerror = null;
        stopStream();
        recorderRef.current = null;
        setIsRecording(false);
        reject(new Error("Ошибка записи с микрофона."));
      };

      recorder.onstop = () => {
        recorder.onstop = null;
        recorder.onerror = null;
        stopStream();
        recorderRef.current = null;
        setIsRecording(false);
        const blob = new Blob(chunksRef.current, { type: effectiveMime });
        chunksRef.current = [];
        if (blob.size === 0) {
          reject(
            new Error("Пустая запись — разрешите доступ к микрофону и попробуйте снова.")
          );
          return;
        }
        const ext = extensionForMime(effectiveMime);
        const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        const file = new File([blob], `mic-recording-${ts}.${ext}`, {
          type: effectiveMime,
        });
        resolve(file);
      };

      try {
        if (recorder.state === "recording") {
          recorder.requestData();
        }
        recorder.stop();
      } catch (e) {
        recorder.onstop = null;
        recorder.onerror = null;
        stopStream();
        recorderRef.current = null;
        setIsRecording(false);
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    });
  }, [stopStream]);

  /** Отмена записи без загрузки на сервер. */
  const discardRecording = useCallback(() => {
    chunksRef.current = [];
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.ondataavailable = null;
      recorder.onerror = null;
      recorder.onstop = () => {
        recorder.onstop = null;
        stopStream();
        recorderRef.current = null;
        setIsRecording(false);
      };
      try {
        if (recorder.state === "recording") {
          recorder.requestData();
        }
        recorder.stop();
      } catch {
        stopStream();
        recorderRef.current = null;
        setIsRecording(false);
      }
    } else {
      stopStream();
      recorderRef.current = null;
      setIsRecording(false);
    }
  }, [stopStream]);

  useEffect(() => {
    return () => {
      chunksRef.current = [];
      const recorder = recorderRef.current;
      if (recorder) {
        recorder.ondataavailable = null;
        recorder.onstop = null;
        if (recorder.state !== "inactive") {
          try {
            recorder.stop();
          } catch {
            /* ignore */
          }
        }
      }
      recorderRef.current = null;
      stopStream();
    };
  }, [stopStream]);

  return {
    isRecording,
    startRecording,
    stopRecording,
    discardRecording,
  };
}
