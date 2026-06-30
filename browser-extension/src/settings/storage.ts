export type AudioSource = "microphone" | "tab" | "system" | "dual";

export type RealtimeMode = "chunk" | "windowed";

export interface ExtensionSettings {
  serverUrl: string;
  accessToken: string | null;
  /** Долгоживущий токен сервиса для `POST /api/auth/refresh` (C7.2). */
  refreshToken: string | null;
  audioSource: AudioSource;
  /** @deprecated use mediaChunkMs — kept for stored-settings migration */
  chunkSizeMs: number;
  /** MediaRecorder.start(timeslice) — сеть / задержка */
  mediaChunkMs: number;
  /** Шаг PCM-буфера на сервере (client_chunk_ms) */
  asrStepMs: number;
  realtimeMode: RealtimeMode;
  ttlDays: number;
  maxConversationMinutes: number;
}

/** Compile-time default from `VITE_DEFAULT_SERVER_URL`; dev fallback — local Docker API. */
const DEFAULT_SERVER_URL =
  import.meta.env.VITE_DEFAULT_SERVER_URL?.trim() || "http://localhost:8002";

const DEFAULT_SETTINGS: ExtensionSettings = {
  serverUrl: DEFAULT_SERVER_URL,
  accessToken: null,
  refreshToken: null,
  audioSource: "microphone",
  chunkSizeMs: 1000,
  mediaChunkMs: 1000,
  asrStepMs: 2500,
  realtimeMode: "windowed",
  ttlDays: 7,
  maxConversationMinutes: 120,
};

function normalizeExtensionSettings(
  stored: Partial<ExtensionSettings>
): ExtensionSettings {
  const merged: ExtensionSettings = { ...DEFAULT_SETTINGS, ...stored };
  if (
    stored.mediaChunkMs == null &&
    stored.asrStepMs == null &&
    stored.chunkSizeMs != null
  ) {
    merged.mediaChunkMs = stored.chunkSizeMs;
    merged.asrStepMs = stored.chunkSizeMs;
  }
  merged.chunkSizeMs = merged.mediaChunkMs;
  return merged;
}

const SETTINGS_KEY = "voiceTranscriberSettings";

export async function loadSettings(): Promise<ExtensionSettings> {
  return new Promise((resolve) => {
    chrome.storage.local.get([SETTINGS_KEY], (result) => {
      const storedRaw = result[SETTINGS_KEY] as Record<string, unknown> | undefined;
      // Backward-compatible: drop deprecated languageMode/languageCode from older stored settings.
      const { languageMode: _lm, languageCode: _lc, ...storedRest } =
        (storedRaw ?? {}) as Record<string, unknown>;
      const stored = storedRest as Partial<ExtensionSettings>;
      resolve(normalizeExtensionSettings(stored));
    });
  });
}

export async function saveSettings(settings: ExtensionSettings): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [SETTINGS_KEY]: settings }, () => resolve());
  });
}

export async function updateSettings(
  partial: Partial<ExtensionSettings>
): Promise<ExtensionSettings> {
  const current = await loadSettings();
  const updated: ExtensionSettings = normalizeExtensionSettings({ ...current, ...partial });
  await saveSettings(updated);
  return updated;
}

