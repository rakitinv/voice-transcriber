export type AudioSource = "microphone" | "tab" | "system";

export type RealtimeMode = "chunk" | "windowed";

export type LanguageMode = "manual" | "auto";

export interface ExtensionSettings {
  serverUrl: string;
  accessToken: string | null;
  audioSource: AudioSource;
  chunkSizeMs: number; // 500–2000
  realtimeMode: RealtimeMode;
  languageMode: LanguageMode;
  languageCode: string | null;
  ttlDays: number;
  maxConversationMinutes: number;
}

const DEFAULT_SETTINGS: ExtensionSettings = {
  serverUrl: "http://localhost:8000",
  accessToken: null,
  audioSource: "microphone",
  chunkSizeMs: 1000,
  realtimeMode: "chunk",
  languageMode: "auto",
  languageCode: null,
  ttlDays: 7,
  maxConversationMinutes: 120,
};

const SETTINGS_KEY = "voiceTranscriberSettings";

export async function loadSettings(): Promise<ExtensionSettings> {
  return new Promise((resolve) => {
    chrome.storage.local.get([SETTINGS_KEY], (result) => {
      const stored = result[SETTINGS_KEY] as Partial<ExtensionSettings> | undefined;
      resolve({ ...DEFAULT_SETTINGS, ...stored });
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
  const updated: ExtensionSettings = { ...current, ...partial };
  await saveSettings(updated);
  return updated;
}

