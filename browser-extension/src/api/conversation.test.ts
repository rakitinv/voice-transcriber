import { describe, it, expect, vi, afterEach } from "vitest";
import type { ExtensionSettings } from "../settings/storage";
import { fetchConversationExport, getConversationDetail, getSessionSummary, retrySessionSummary } from "./conversation";

const baseSettings: ExtensionSettings = {
  serverUrl: "http://api.example/",
  accessToken: "jwt-test",
  refreshToken: null,
  audioSource: "microphone",
  chunkSizeMs: 1000,
  mediaChunkMs: 1000,
  asrStepMs: 2500,
  realtimeMode: "chunk",
  ttlDays: 7,
  maxConversationMinutes: 120,
};

describe("conversation API helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fetchConversationExport requests canonical path and Bearer", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => "# title",
    });
    vi.stubGlobal("fetch", fetchMock);

    const body = await fetchConversationExport(baseSettings, "abc-uuid", "md");
    expect(body).toBe("# title");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.example/api/conversations/abc-uuid/export?format=md&tier=final");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer jwt-test");
  });

  it("getConversationDetail GETs conversation", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "abc", transcript: [{ text: "hi", speaker: "S1", start: 0, end: 1 }] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const d = await getConversationDetail(baseSettings, "abc");
    expect(d.transcript).toHaveLength(1);
    expect(d.transcript[0].text).toBe("hi");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://api.example/api/conversations/abc");
  });

  it("getConversationDetail passes tier query when requested", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "abc",
        transcript: [],
        transcript_status: "running",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const d = await getConversationDetail(baseSettings, "abc", { tier: "final" });
    expect(d.transcript_status).toBe("running");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://api.example/api/conversations/abc?tier=final");
  });

  it("getSessionSummary GETs session-summary", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        recording_session_id: "rs-1",
        status: "success",
        summary_md: "# Summary",
        error: null,
        updated_at: "2026-01-01T00:00:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const d = await getSessionSummary(baseSettings, "abc");
    expect(d.summary_md).toBe("# Summary");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://api.example/api/conversations/abc/session-summary");
  });

  it("retrySessionSummary POSTs session-summary/retry", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    await retrySessionSummary(baseSettings, "abc");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.example/api/conversations/abc/session-summary/retry");
    expect(init.method).toBe("POST");
  });
});
