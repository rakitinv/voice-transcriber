import type { ExtensionSettings } from "../settings/storage";

/** Lowercase extensions accepted by the server (`resolve_audio_extension`). */
const ALLOWED_AUDIO_EXTENSIONS = new Set([
  "webm",
  "wav",
  "mp3",
  "m4a",
  "aac",
  "ogg",
  "flac",
  "opus",
]);

/**
 * Infer `audio_format` query value from the file name (no leading dot).
 * Returns null if unknown — the server will fall back to Content-Type / webm.
 */
export function inferAudioFormatFromFilename(filename: string): string | null {
  const m = /\.([a-z0-9]+)$/i.exec(filename.trim());
  if (!m) return null;
  const ext = m[1].toLowerCase();
  return ALLOWED_AUDIO_EXTENSIONS.has(ext) ? ext : null;
}

export type UploadAudioResponse = {
  conversation_id: string;
  audio_object_ext?: string;
  status?: string;
  message?: string;
};

/**
 * POST multipart `file` to `/api/upload` (same contract as Web UI / CLI).
 */
export async function postUploadAudio(
  settings: ExtensionSettings,
  file: File,
  conversationId: string | null
): Promise<UploadAudioResponse> {
  const base = settings.serverUrl.replace(/\/+$/, "");
  const url = new URL(`${base}/api/upload`);
  if (conversationId) url.searchParams.set("conversation_id", conversationId);
  const fmt = inferAudioFormatFromFilename(file.name);
  if (fmt) url.searchParams.set("audio_format", fmt);

  const form = new FormData();
  form.append("file", file, file.name);

  const headers: Record<string, string> = {};
  if (settings.accessToken?.trim()) {
    headers.Authorization = `Bearer ${settings.accessToken.trim()}`;
  }

  const res = await fetch(url.toString(), { method: "POST", headers, body: form });
  const text = await res.text().catch(() => "");
  if (!res.ok) {
    throw new Error(`Загрузка не удалась: ${res.status} ${text}`.trim());
  }
  let data: UploadAudioResponse;
  try {
    data = JSON.parse(text || "{}") as UploadAudioResponse;
  } catch {
    throw new Error("Ответ загрузки не является корректным JSON");
  }
  if (!data.conversation_id) {
    throw new Error("Загрузка выполнена, но в ответе нет conversation_id");
  }
  return data;
}
