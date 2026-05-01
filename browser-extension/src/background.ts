import {
  clearRecordingSession,
  readRecordingSession,
  writeRecordingSession,
  type RecordingSessionV1,
} from "./recording/sessionPersist";
import { loadSettings, type ExtensionSettings } from "./settings/storage";
import { registerOAuthMessageListener, runOAuthLoginAsync, writeOAuthFlowSnap } from "./auth/oauth";
import { clearSidePanelCloseSuppression } from "./sidePanelPresence";

type Message =
  | { type: "create_conversation_for_recording" }
  | { type: "update_settings"; payload: unknown }
  | { type: "bg_start_offscreen_recording"; settings: ExtensionSettings; conversationId: string; windowId: number }
  | { type: "bg_stop_offscreen_recording" }
  | {
      type: "bg_register_popup_recording";
      windowId: number;
      capturedTabId?: number;
      conversationId: string;
      source: "microphone" | "tab" | "dual";
    }
  | { type: "bg_clear_recording_session" };

async function createConversation(settings: {
  serverUrl: string;
  accessToken: string | null;
  realtimeMode?: string;
  chunkSizeMs?: number;
  ttlDays?: number;
}) {
  const url = `${settings.serverUrl.replace(/\/+$/, "")}/api/conversations`;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (settings.accessToken) headers.Authorization = `Bearer ${settings.accessToken}`;

  const ttl =
    typeof settings.ttlDays === "number" && Number.isFinite(settings.ttlDays)
      ? Math.trunc(settings.ttlDays)
      : null;

  const body = JSON.stringify({
    title: "Browser recording",
    ttl_days: ttl != null && ttl >= 1 ? ttl : null,
    realtime_mode: settings.realtimeMode ?? null,
    chunk_ms: settings.chunkSizeMs ?? null,
  });

  const res = await fetch(url, { method: "POST", headers, body });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to create conversation: ${res.status} ${text}`);
  }
  const data = (await res.json()) as { id?: string };
  if (!data?.id) throw new Error("Backend did not return conversation id");
  return data.id;
}

const startWaiters = new Map<string, (r: { ok: boolean; error?: string }) => void>();
let stopResolver: (() => void) | null = null;

/**
 * `chrome.sidePanel.open` must run without preceding `await` in the gesture chain (context menu).
 * `tabs.onActivated` carries both ids synchronously.
 */
let lastActivatedInBrowser: { windowId: number; tabId: number } | null = null;
if (chrome.tabs?.onActivated) {
  chrome.tabs.onActivated.addListener((activeInfo) => {
    lastActivatedInBrowser = { windowId: activeInfo.windowId, tabId: activeInfo.tabId };
  });
}

async function ensureOffscreenDocument(): Promise<void> {
  if (await chrome.offscreen.hasDocument()) return;
  await chrome.offscreen.createDocument({
    url: chrome.runtime.getURL("offscreen.html"),
    reasons: [chrome.offscreen.Reason.USER_MEDIA, chrome.offscreen.Reason.AUDIO_PLAYBACK],
    justification:
      "Run microphone MediaRecorder and WebSocket /ws/audio when the extension popup may be closed (Chrome MV3).",
  });
}

/** Badge = any active session; context menus: Stop = offscreen mic; Start disabled while any session active. */
function setRecordingUiFromSession(session: RecordingSessionV1 | null): void {
  const active = !!session?.active;
  const offscreenMic = active && session?.surface === "offscreen";
  void chrome.action.setBadgeText({ text: active ? " " : "" });
  void chrome.action.setBadgeBackgroundColor({ color: "#b71c1c" });
  try {
    chrome.contextMenus.update("vt_stop_recording", { enabled: offscreenMic });
    chrome.contextMenus.update("vt_start_recording", { enabled: !active });
  } catch {
    // ignore if menu missing
  }
}

async function closeOffscreenIfIdle(): Promise<void> {
  if (await chrome.offscreen.hasDocument()) {
    await chrome.offscreen.closeDocument();
  }
}

/**
 * In the service worker there is no "current" window. Prefer the tab from the click when present,
 * otherwise the active tab in the last-focused browser window (getLastFocused alone can miss `id`).
 */
async function resolveSidePanelTargetWindowId(
  info: chrome.contextMenus.OnClickData,
  tab?: chrome.tabs.Tab
): Promise<number | null> {
  const fromHandler = tab?.windowId;
  if (typeof fromHandler === "number") return fromHandler;
  const fromClick = info.tab?.windowId;
  if (typeof fromClick === "number") return fromClick;
  if (lastActivatedInBrowser) return lastActivatedInBrowser.windowId;
  for (const query of [
    { active: true, currentWindow: true } as const,
    { active: true, lastFocusedWindow: true } as const,
  ]) {
    try {
      const tabs = await chrome.tabs.query(query);
      const wid = tabs[0]?.windowId;
      if (typeof wid === "number") return wid;
    } catch {
      // ignore
    }
  }
  try {
    const w = await chrome.windows.getLastFocused({ populate: false });
    if (typeof w.id === "number") return w.id;
  } catch {
    // ignore
  }
  return null;
}

/** Resolve window/tab for `sidePanel.open` without async (preserves user gesture from context menu). */
function resolveSidePanelOpenTargetSync(
  info: chrome.contextMenus.OnClickData,
  tab?: chrome.tabs.Tab
): { windowId: number | null; tabId: number | null } {
  if (tab?.id != null && tab.windowId != null) {
    return { windowId: tab.windowId, tabId: tab.id };
  }
  if (info.tab?.id != null && info.tab.windowId != null) {
    return { windowId: info.tab.windowId, tabId: info.tab.id };
  }
  if (lastActivatedInBrowser) {
    return { windowId: lastActivatedInBrowser.windowId, tabId: lastActivatedInBrowser.tabId };
  }
  const windowId =
    typeof tab?.windowId === "number"
      ? tab.windowId
      : typeof info.tab?.windowId === "number"
        ? info.tab.windowId
        : null;
  const tabId =
    typeof tab?.id === "number" ? tab.id : typeof info.tab?.id === "number" ? info.tab.id : null;
  return { windowId, tabId };
}

/** Fire-and-forget suppression clear so `open` is not deferred behind storage. */
function openSidePanelFromToolbarMenu(info: chrome.contextMenus.OnClickData, tab?: chrome.tabs.Tab): void {
  if (!chrome.sidePanel?.open) return;
  const { windowId, tabId } = resolveSidePanelOpenTargetSync(info, tab);
  if (typeof windowId === "number") {
    void clearSidePanelCloseSuppression(windowId);
  }
  if (typeof tabId === "number") {
    void chrome.sidePanel.open({ tabId }).catch(() => {
      if (typeof windowId === "number") {
        void chrome.sidePanel.open({ windowId }).catch((e) => {
          console.error("Open side panel failed:", e);
        });
      }
    });
    return;
  }
  if (typeof windowId === "number") {
    void chrome.sidePanel.open({ windowId }).catch((e) => {
      console.error("Open side panel failed:", e);
    });
    return;
  }
  void (async () => {
    try {
      const wid = await resolveSidePanelTargetWindowId(info, tab);
      if (wid == null) {
        console.error("Open side panel: could not resolve browser window.");
        return;
      }
      await clearSidePanelCloseSuppression(wid);
      await chrome.sidePanel.open({ windowId: wid });
    } catch (e) {
      console.error("Open side panel failed:", e);
    }
  })();
}

async function repairStaleRecordingFlag(): Promise<void> {
  const s = await readRecordingSession();
  if (!s?.active) return;
  if (s.surface === "offscreen" && !(await chrome.offscreen.hasDocument())) {
    await clearRecordingSession();
    setRecordingUiFromSession(null);
    return;
  }
  if (s.surface === "popup") {
    await clearRecordingSession();
    setRecordingUiFromSession(null);
  }
}

async function startOffscreenRecording(
  settings: ExtensionSettings,
  conversationId: string,
  windowId: number
): Promise<void> {
  await ensureOffscreenDocument();
  const requestId = crypto.randomUUID();
  await new Promise<void>((resolve, reject) => {
    const t = setTimeout(() => {
      if (startWaiters.has(requestId)) {
        startWaiters.delete(requestId);
        reject(new Error("Offscreen recording failed to start (timeout)"));
      }
    }, 30_000);

    startWaiters.set(requestId, (r) => {
      clearTimeout(t);
      startWaiters.delete(requestId);
      if (r.ok) resolve();
      else reject(new Error(r.error ?? "Offscreen start failed"));
    });

    void chrome.runtime.sendMessage({
      type: "OFFSCREEN_START",
      requestId,
      settings,
      conversationId,
    });
  });

  const session: RecordingSessionV1 = {
    v: 1,
    active: true,
    surface: "offscreen",
    source: "microphone",
    windowId,
    conversationId,
    updatedAt: Date.now(),
  };
  await writeRecordingSession(session);
  setRecordingUiFromSession(session);
}

async function stopOffscreenRecording(): Promise<void> {
  const snap = await readRecordingSession();
  if (!snap?.active || snap.surface !== "offscreen") {
    return;
  }

  if (!(await chrome.offscreen.hasDocument())) {
    await clearRecordingSession();
    setRecordingUiFromSession(null);
    return;
  }

  let settled = false;
  await new Promise<void>((resolve, reject) => {
    const t = setTimeout(() => {
      if (settled) return;
      settled = true;
      stopResolver = null;
      reject(new Error("Stop recording timed out"));
    }, 120_000);

    stopResolver = () => {
      if (settled) return;
      settled = true;
      clearTimeout(t);
      stopResolver = null;
      resolve();
    };

    void chrome.runtime.sendMessage({ type: "OFFSCREEN_STOP" });
  });

  await clearRecordingSession();
  setRecordingUiFromSession(null);
  await closeOffscreenIfIdle();
}

function initSidePanel(): void {
  if (!chrome.sidePanel?.setPanelBehavior) return;
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false });
  void chrome.sidePanel.setOptions({ enabled: true, path: "sidepanel.html" });
}

function registerContextMenus(): void {
  if (!chrome.contextMenus) return;
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "vt_start_recording",
      title: "Start recording…",
      contexts: ["action"],
    });
    chrome.contextMenus.create({
      id: "vt_open_side_panel",
      title: "Open recording side panel",
      contexts: ["action"],
    });
    chrome.contextMenus.create({
      id: "vt_upload_audio",
      title: "Upload audio file…",
      contexts: ["action"],
    });
    chrome.contextMenus.create({
      id: "vt_open_settings",
      title: "Open settings (popup)…",
      contexts: ["action"],
    });
    chrome.contextMenus.create({
      id: "vt_stop_recording",
      title: "Stop recording (microphone)",
      contexts: ["action"],
      enabled: false,
    });
  });
}

chrome.runtime.onInstalled.addListener(() => {
  console.log("Voice Transcriber extension installed");
  initSidePanel();
  registerContextMenus();
  void (async () => {
    await repairStaleRecordingFlag();
    setRecordingUiFromSession(await readRecordingSession());
  })();
});

chrome.runtime.onStartup.addListener(() => {
  initSidePanel();
  registerContextMenus();
  void (async () => {
    await repairStaleRecordingFlag();
    setRecordingUiFromSession(await readRecordingSession());
  })();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  void (async () => {
    const s = await readRecordingSession();
    if (!s?.active || s.surface !== "popup" || (s.source !== "tab" && s.source !== "dual"))
      return;
    if (s.capturedTabId === tabId) {
      await clearRecordingSession();
      setRecordingUiFromSession(null);
    }
  })();
});

chrome.windows.onRemoved.addListener((windowId) => {
  void (async () => {
    const s = await readRecordingSession();
    if (!s?.active || s.windowId !== windowId) return;
    if (s.surface === "offscreen") {
      try {
        await stopOffscreenRecording();
      } catch (e) {
        console.error("Window close: stop offscreen failed:", e);
        await clearRecordingSession();
        setRecordingUiFromSession(null);
      }
    } else {
      await clearRecordingSession();
      setRecordingUiFromSession(null);
    }
  })();
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "vt_start_recording") {
    openSidePanelFromToolbarMenu(info, tab);
    void (async () => {
      try {
        await new Promise((r) => setTimeout(r, 280));
        chrome.runtime.sendMessage({ type: "vt_remote_start_recording" });
      } catch (e) {
        console.error("Start recording (after open side panel) failed:", e);
      }
    })();
    return;
  }
  if (info.menuItemId === "vt_open_side_panel") {
    openSidePanelFromToolbarMenu(info, tab);
    return;
  }
  if (info.menuItemId === "vt_upload_audio") {
    const url = chrome.runtime.getURL("upload.html");
    chrome.windows.create({
      url,
      type: "popup",
      width: 460,
      height: 260,
      focused: true,
    });
    return;
  }
  if (info.menuItemId === "vt_open_settings") {
    void chrome.action.openPopup().catch((e) => {
      console.error("openPopup failed (requires default_popup + user gesture):", e);
    });
    return;
  }
  if (info.menuItemId === "vt_stop_recording") {
    void (async () => {
      try {
        await stopOffscreenRecording();
      } catch (e) {
        console.error("Context menu stop failed:", e);
      }
    })();
  }
});

registerOAuthMessageListener();

/** Popup closes ⇒ OAuth started there aborts; run OAuth here instead (Chrome MV3). */
let oauthLoginInFlight = false;

chrome.runtime.onMessage.addListener((message: unknown, _sender, sendResponse) => {
  const m = message as Record<string, unknown>;

  if (m?.type === "vt_oauth_login") {
    const provider = m.provider === "yandex" ? "yandex" : "google";
    if (oauthLoginInFlight) {
      sendResponse({ ok: false, error: "Sign-in already in progress." });
      return false;
    }
    oauthLoginInFlight = true;
    void writeOAuthFlowSnap({ pending: true, lastError: null })
      .then(async () => {
        try {
          const settings = await loadSettings();
          const result = await runOAuthLoginAsync(settings.serverUrl, provider);
          await writeOAuthFlowSnap({
            pending: false,
            lastError: result.ok ? null : result.error,
          });
        } catch (e) {
          await writeOAuthFlowSnap({
            pending: false,
            lastError: e instanceof Error ? e.message : String(e),
          });
        } finally {
          oauthLoginInFlight = false;
        }
      })
      .catch(async (e) => {
        oauthLoginInFlight = false;
        await writeOAuthFlowSnap({
          pending: false,
          lastError: e instanceof Error ? e.message : String(e),
        });
      });
    sendResponse({ ok: true });
    return false;
  }

  if (m?.type === "offscreen_recording_reply") {
    const requestId = String(m.requestId ?? "");
    const cb = startWaiters.get(requestId);
    if (cb) {
      cb({ ok: m.ok === true, error: typeof m.error === "string" ? m.error : undefined });
    }
    return false;
  }

  if (m?.type === "offscreen_stopped") {
    stopResolver?.();
    return false;
  }

  const typed = message as Message;
  (async () => {
    if (typed.type === "create_conversation_for_recording") {
      const settings = await loadSettings();
      const conversationId = await createConversation({
        serverUrl: settings.serverUrl,
        accessToken: settings.accessToken,
        realtimeMode: settings.realtimeMode,
        chunkSizeMs: settings.chunkSizeMs,
        ttlDays: settings.ttlDays,
      });
      sendResponse({ ok: true, conversationId });
    } else if (typed.type === "update_settings") {
      sendResponse({ ok: true });
    } else if (typed.type === "bg_start_offscreen_recording") {
      try {
        await startOffscreenRecording(typed.settings, typed.conversationId, typed.windowId);
        sendResponse({ ok: true });
      } catch (e) {
        await clearRecordingSession();
        setRecordingUiFromSession(null);
        await closeOffscreenIfIdle();
        sendResponse({ ok: false, error: e instanceof Error ? e.message : String(e) });
      }
    } else if (typed.type === "bg_stop_offscreen_recording") {
      try {
        await stopOffscreenRecording();
        sendResponse({ ok: true });
      } catch (e) {
        sendResponse({ ok: false, error: e instanceof Error ? e.message : String(e) });
      }
    } else if (typed.type === "bg_register_popup_recording") {
      const session: RecordingSessionV1 = {
        v: 1,
        active: true,
        surface: "popup",
        source: typed.source,
        windowId: typed.windowId,
        capturedTabId: typed.capturedTabId,
        conversationId: typed.conversationId,
        updatedAt: Date.now(),
      };
      await writeRecordingSession(session);
      setRecordingUiFromSession(session);
      sendResponse({ ok: true });
    } else if (typed.type === "bg_clear_recording_session") {
      await clearRecordingSession();
      setRecordingUiFromSession(null);
      sendResponse({ ok: true });
    }
  })().catch((err) => {
    console.error("Background error:", err);
    sendResponse({ ok: false, error: String(err) });
  });

  return true;
});
