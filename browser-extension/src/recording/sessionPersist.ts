import { RECORDING_ACTIVE_KEY, RECORDING_CONV_KEY, RECORDING_SESSION_KEY } from "./storageKeys";

export type RecordingSessionV1 = {
  v: 1;
  active: true;
  surface: "offscreen" | "popup";
  source: "microphone" | "tab" | "dual";
  windowId: number;
  /** Tab that was captured when `source === "tab"` or combined tab track for `dual` (B2.8). */
  capturedTabId?: number;
  conversationId: string;
  updatedAt: number;
};

export async function readRecordingSession(): Promise<RecordingSessionV1 | null> {
  const r = await chrome.storage.local.get([
    RECORDING_SESSION_KEY,
    RECORDING_ACTIVE_KEY,
    RECORDING_CONV_KEY,
  ]);
  const raw = r[RECORDING_SESSION_KEY] as RecordingSessionV1 | undefined;
  if (raw && raw.v === 1 && raw.active) {
    return raw;
  }
  if (r[RECORDING_ACTIVE_KEY] && typeof r[RECORDING_CONV_KEY] === "string") {
    const migrated: RecordingSessionV1 = {
      v: 1,
      active: true,
      surface: "offscreen",
      source: "microphone",
      windowId: -1,
      conversationId: r[RECORDING_CONV_KEY],
      updatedAt: Date.now(),
    };
    await chrome.storage.local.remove([RECORDING_ACTIVE_KEY, RECORDING_CONV_KEY]);
    await writeRecordingSession(migrated);
    return migrated;
  }
  return null;
}

export async function writeRecordingSession(session: RecordingSessionV1): Promise<void> {
  await chrome.storage.local.set({
    [RECORDING_SESSION_KEY]: { ...session, updatedAt: Date.now() },
    [RECORDING_ACTIVE_KEY]: true,
    [RECORDING_CONV_KEY]: session.conversationId,
  });
}

export async function clearRecordingSession(): Promise<void> {
  await chrome.storage.local.remove([RECORDING_SESSION_KEY, RECORDING_ACTIVE_KEY, RECORDING_CONV_KEY]);
}
