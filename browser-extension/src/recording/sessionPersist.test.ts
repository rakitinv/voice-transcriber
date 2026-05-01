import { describe, it, expect, beforeEach } from "vitest";
import {
  readRecordingSession,
  writeRecordingSession,
  clearRecordingSession,
  type RecordingSessionV1,
} from "./sessionPersist";
import { RECORDING_ACTIVE_KEY, RECORDING_CONV_KEY, RECORDING_SESSION_KEY } from "./storageKeys";

let store: Record<string, unknown>;

beforeEach(() => {
  store = {};
  (globalThis as unknown as { chrome: typeof chrome }).chrome = {
    storage: {
      local: {
        get: async (keys: string | string[] | Record<string, unknown> | null) => {
          const keyList = Array.isArray(keys)
            ? keys
            : typeof keys === "string"
              ? [keys]
              : keys
                ? Object.keys(keys)
                : Object.keys(store);
          const out: Record<string, unknown> = {};
          for (const k of keyList) {
            if (store[k] !== undefined) out[k] = store[k];
          }
          return out;
        },
        set: async (obj: Record<string, unknown>) => {
          Object.assign(store, obj);
        },
        remove: async (keys: string | string[]) => {
          const keyList = Array.isArray(keys) ? keys : [keys];
          for (const k of keyList) delete store[k];
        },
      },
    },
  } as typeof chrome;
});

describe("sessionPersist", () => {
  it("round-trips v1 session", async () => {
    const session: RecordingSessionV1 = {
      v: 1,
      active: true,
      surface: "popup",
      source: "tab",
      windowId: 42,
      capturedTabId: 7,
      conversationId: "550e8400-e29b-41d4-a716-446655440000",
      updatedAt: 1,
    };
    await writeRecordingSession(session);
    const read = await readRecordingSession();
    expect(read?.conversationId).toBe(session.conversationId);
    expect(read?.surface).toBe("popup");
    expect(read?.capturedTabId).toBe(7);
    await clearRecordingSession();
    expect(await readRecordingSession()).toBeNull();
  });

  it("migrates legacy keys to v1", async () => {
    store[RECORDING_ACTIVE_KEY] = true;
    store[RECORDING_CONV_KEY] = "legacy-uuid";
    const read = await readRecordingSession();
    expect(read?.v).toBe(1);
    expect(read?.conversationId).toBe("legacy-uuid");
    expect(read?.surface).toBe("offscreen");
    expect(store[RECORDING_SESSION_KEY]).toBeDefined();
    expect(store[RECORDING_ACTIVE_KEY]).toBe(true);
    expect(store[RECORDING_CONV_KEY]).toBe("legacy-uuid");
  });
});
