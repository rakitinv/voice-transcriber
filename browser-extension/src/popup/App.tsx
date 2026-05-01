import React, { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";

import {
  AudioSource,
  ExtensionSettings,
  RealtimeMode,
  loadSettings,
  updateSettings,
} from "../settings/storage";
import { getConversationDetail, fetchConversationExport } from "../api/conversation";
import { getUserSettings, type UserSettings } from "../api/settings";
import { postUploadAudio } from "../api/upload";
import { readRecordingSession } from "../recording/sessionPersist";
import { RECORDING_ACTIVE_KEY, RECORDING_SESSION_KEY } from "../recording/storageKeys";
import {
  clearExtensionAuth,
  verifyOrRefreshSession,
  readOAuthFlowSnap,
  writeOAuthFlowSnap,
  OAUTH_FLOW_STORAGE_KEY,
  type OAuthFlowSnap,
} from "../auth/oauth";
import { TranscriptWebSocketClient, type TranscriptMessage } from "../websocket/client";
import { AudioRecorderController } from "../recorder/recorder";
import {
  SIDE_PANEL_PING_MS,
  clearSidePanelCloseSuppression,
  clearSidePanelPresence,
  getExtensionHostWindowId,
  isSidePanelCloseSuppressed,
  isSidePanelPresentForWindow,
  setSidePanelCloseSuppression,
  touchSidePanelPresence,
} from "../sidePanelPresence";

type RecordingStatus = "idle" | "recording";

export type AppLayout = "popup" | "sidepanel";

/** `shell` — auth, settings, open side panel (toolbar popup). `recording` — capture + transcript (side panel). */
export type AppVariant = "shell" | "recording";

export interface AppProps {
  /** `sidepanel` — Chrome Side Panel (B2.6); default narrow popup shell. */
  layout?: AppLayout;
  variant?: AppVariant;
}

interface TranscriptLine {
  id: string;
  text: string;
}

type SidePanelWithClose = typeof chrome.sidePanel & {
  close?: (options: { windowId: number }) => Promise<void>;
};

/** Chrome 141+: `sidePanel.close`. Older: message to side panel document (`window.close`). */
async function closeExtensionSidePanel(windowId: number): Promise<void> {
  const sp = chrome.sidePanel as SidePanelWithClose;
  if (typeof sp.close === "function") {
    await sp.close({ windowId });
    return;
  }
  await new Promise<void>((resolve) => {
    chrome.runtime.sendMessage({ type: "vt_request_close_side_panel", windowId }, () => {
      void chrome.runtime.lastError;
      resolve();
    });
  });
}

export const App: React.FC<AppProps> = ({ layout = "popup", variant: variantProp }) => {
  const uiMode: AppVariant = variantProp ?? (layout === "sidepanel" ? "recording" : "shell");
  const [settings, setSettings] = useState<ExtensionSettings | null>(null);
  const [sessionOk, setSessionOk] = useState<boolean | null>(null);
  const [status, setStatus] = useState<RecordingStatus>("idle");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [transcriptLines, setTranscriptLines] = useState<TranscriptLine[]>([]);
  /** ТЗ §17.9: канонический export final только после success финальной ветки на сервере. */
  const [finalExportReady, setFinalExportReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadInfo, setUploadInfo] = useState<string | null>(null);
  const [oauthBusy, setOauthBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [serverUserSettings, setServerUserSettings] = useState<UserSettings | null>(null);
  const [serverUserSettingsError, setServerUserSettingsError] = useState<string | null>(null);
  /** Bumps transcript WebSocket client (manual reconnect, B2.6). */
  const [transcriptWsBootKey, setTranscriptWsBootKey] = useState(0);
  const [offscreenMicActive, setOffscreenMicActive] = useState(false);
  /** Popup only: whether the extension side panel is open in the last-focused window (polled). */
  const [sidePanelOpen, setSidePanelOpen] = useState(false);
  /** Latest ids for async callbacks (e.g. tab `onAfterStop`) where React state may lag. */
  const settingsRef = React.useRef<ExtensionSettings | null>(null);
  const conversationIdRef = React.useRef<string | null>(null);
  const wsRef = React.useRef<TranscriptWebSocketClient | null>(null);
  const recorderRef = React.useRef<AudioRecorderController | null>(null);
  /** Microphone uses MV3 offscreen document; tab capture runs in this document when uiMode is recording. */
  const recordingSurfaceRef = React.useRef<"offscreen" | "popup" | null>(null);
  const handleStartRef = React.useRef<() => Promise<void>>(async () => {});
  /** Cancels post-stop transcript polling when a new recording starts. */
  const transcriptPollAbortRef = React.useRef<AbortController | null>(null);
  /** After Stop, ignore late transcript_partial (buffer flush) so server poll is not overwritten. */
  const ignoreLiveTranscriptRef = React.useRef(false);

  useEffect(() => {
    void loadSettings().then(setSettings);
  }, []);

  useEffect(() => {
    if (layout !== "sidepanel") return;
    const onMsg = (msg: unknown) => {
      if (
        msg &&
        typeof msg === "object" &&
        (msg as { type?: string }).type === "vt_request_close_side_panel"
      ) {
        window.close();
      }
    };
    chrome.runtime.onMessage.addListener(onMsg);
    return () => chrome.runtime.onMessage.removeListener(onMsg);
  }, [layout]);

  /** Heartbeat so the toolbar popup can detect an open side panel (`getContexts` is unreliable). */
  useEffect(() => {
    if (layout !== "sidepanel") return;
    let cancelled = false;
    let windowId: number | null = null;
    let interval: ReturnType<typeof setInterval> | null = null;

    const stop = () => {
      if (interval != null) {
        clearInterval(interval);
        interval = null;
      }
      if (windowId != null) {
        void clearSidePanelPresence(windowId);
        windowId = null;
      }
    };

    void getExtensionHostWindowId().then(async (id) => {
      if (cancelled || id == null) return;
      windowId = id;
      await clearSidePanelCloseSuppression(id);
      void touchSidePanelPresence(windowId);
      interval = setInterval(() => {
        void (async () => {
          if (cancelled || windowId == null) return;
          if (await isSidePanelCloseSuppressed(windowId)) {
            stop();
            window.close();
            return;
          }
          await touchSidePanelPresence(windowId);
        })();
      }, SIDE_PANEL_PING_MS);
    });

    const onPageHide = () => stop();
    window.addEventListener("pagehide", onPageHide);
    return () => {
      cancelled = true;
      window.removeEventListener("pagehide", onPageHide);
      stop();
    };
  }, [layout]);

  useEffect(() => {
    if (layout !== "popup") return;
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      try {
        const wid = await getExtensionHostWindowId();
        if (wid == null || cancelled) return;
        const open = await isSidePanelPresentForWindow(wid);
        if (!cancelled) setSidePanelOpen(open);
      } catch {
        if (!cancelled) setSidePanelOpen(false);
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 650);
    const onFocus = () => void tick();
    const onVis = () => {
      if (document.visibilityState === "visible") void tick();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [layout]);

  settingsRef.current = settings;
  conversationIdRef.current = conversationId;

  useEffect(() => {
    void readRecordingSession().then((s) => {
      const off = !!(s?.active && s.surface === "offscreen");
      setOffscreenMicActive(off);
      if (uiMode !== "recording" || !off || !s) return;
      recordingSurfaceRef.current = "offscreen";
      setStatus("recording");
      setConversationId(s.conversationId);
    });
  }, [uiMode]);

  useEffect(() => {
    const onStorage = (
      changes: Record<string, chrome.storage.StorageChange>,
      areaName: string
    ) => {
      if (areaName !== "local") return;
      const sess = changes[RECORDING_SESSION_KEY];
      const leg = changes[RECORDING_ACTIVE_KEY];
      if (!sess && !leg) return;
      void readRecordingSession().then((s) => {
        setOffscreenMicActive(!!(s?.active && s.surface === "offscreen"));
        const nextActive = !!s?.active;
        if (!nextActive && recordingSurfaceRef.current === "offscreen") {
          recordingSurfaceRef.current = null;
          setStatus("idle");
        }
      });
    };
    chrome.storage.onChanged.addListener(onStorage);
    return () => chrome.storage.onChanged.removeListener(onStorage);
  }, []);

  useEffect(() => {
    const onPageHide = () => {
      if (recordingSurfaceRef.current === "popup") {
        void recorderRef.current?.stop();
      }
    };
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, []);

  const refreshSession = useCallback(async (_s: ExtensionSettings) => {
    const latest = await loadSettings();
    const r = await verifyOrRefreshSession(latest);
    if (r.status === "ok") {
      setSessionOk(true);
      setSettings(r.settings);
      setError(null);
      return true;
    }
    if (r.status === "unauthorized") {
      setSessionOk(false);
      setSettings(await loadSettings());
      setError("Session expired or token invalid — please login again.");
      return false;
    }
    /* network: /auth/me timeout, 5xx, or fetch failure — tokens usually unchanged */
    const hasToken = !!(latest.accessToken ?? "").trim();
    setSessionOk(hasToken);
    setError(
      "Server is slow or unreachable while checking your session (the API may be busy). You may still be signed in — retry shortly. If this persists, check Server URL and that the API is running."
    );
    return false;
  }, []);

  const handleLogout = useCallback(async () => {
    setError(null);
    setUploadInfo(null);
    setOauthBusy(true);
    try {
      await writeOAuthFlowSnap({ pending: false, lastError: null });
      await clearExtensionAuth();
      const latest = await loadSettings();
      setSettings(latest);
      setSessionOk(false);
    } finally {
      setOauthBusy(false);
    }
  }, []);

  const pollServerTranscriptAfterStop = useCallback(
    async (s: ExtensionSettings, cid: string, signal: AbortSignal) => {
      setUploadInfo("Loading full transcript from server…");
      const ok = await refreshSession(s);
      if (!ok || signal.aborted) {
        if (!signal.aborted) setUploadInfo(null);
        return;
      }
      const intervalMs = 1600;
      const maxAttempts = 55;
      for (let attempt = 0; attempt < maxAttempts; attempt++) {
        if (signal.aborted) return;
        try {
          const cur = await loadSettings();
          const detail = await getConversationDetail(cur, cid);
          const finalSnap = await getConversationDetail(cur, cid, { tier: "final" });
          if (!signal.aborted) {
            setFinalExportReady(finalSnap.transcript_status === "success");
          }
          const segs = detail.transcript ?? [];
          if (segs.length > 0) {
            if (signal.aborted) return;
            setTranscriptLines(segs.map((x) => ({ id: crypto.randomUUID(), text: x.text })));
            setUploadInfo(null);
            return;
          }
          if (detail.refetch_recommended === false && attempt >= 2) {
            break;
          }
        } catch (e) {
          if (!signal.aborted) {
            setError(e instanceof Error ? e.message : String(e));
            setUploadInfo(null);
          }
          return;
        }
        await new Promise<void>((resolve) => {
          const t = setTimeout(resolve, intervalMs);
          signal.addEventListener(
            "abort",
            () => {
              clearTimeout(t);
              resolve();
            },
            { once: true }
          );
        });
        if (signal.aborted) return;
        const ok2 = await refreshSession(s);
        if (!ok2 || signal.aborted) {
          setUploadInfo(null);
          return;
        }
      }
      if (!signal.aborted) {
        setUploadInfo("Full transcript not ready yet — use Refresh from server.");
      }
    },
    [refreshSession]
  );

  const startPostStopTranscriptPoll = useCallback(
    (s: ExtensionSettings, cid: string) => {
      transcriptPollAbortRef.current?.abort();
      const ac = new AbortController();
      transcriptPollAbortRef.current = ac;
      void pollServerTranscriptAfterStop(s, cid, ac.signal);
    },
    [pollServerTranscriptAfterStop]
  );

  useEffect(() => {
    if (!settings) return;
    void refreshSession(settings);
    // Intentionally only re-check when URL/token change (not on every settings tweak like chunk size).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings?.serverUrl, settings?.accessToken, settings?.refreshToken, refreshSession]);

  useEffect(() => {
    void readOAuthFlowSnap().then((snap) => {
      if (snap?.pending) setOauthBusy(true);
    });
  }, []);

  useEffect(() => {
    const onFlowChanged = (
      changes: Record<string, chrome.storage.StorageChange>,
      areaName: string
    ) => {
      if (areaName !== "local") return;
      const ch = changes[OAUTH_FLOW_STORAGE_KEY];
      if (!ch?.newValue) return;
      const snap = ch.newValue as OAuthFlowSnap;
      if (!snap.pending) {
        setOauthBusy(false);
        setError(snap.lastError ?? null);
        void loadSettings().then((latest) => refreshSession(latest));
      } else {
        setOauthBusy(true);
      }
    };
    chrome.storage.onChanged.addListener(onFlowChanged);
    return () => chrome.storage.onChanged.removeListener(onFlowChanged);
  }, [refreshSession]);

  useEffect(() => {
    if (!settingsOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSettingsOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [settingsOpen]);

  useEffect(() => {
    if (!settingsOpen) return;
    if (!settings) return;
    const token = (settings.accessToken ?? "").trim();
    if (!token) {
      setServerUserSettings(null);
      setServerUserSettingsError(null);
      return;
    }
    let cancelled = false;
    setServerUserSettings(null);
    setServerUserSettingsError(null);
    void (async () => {
      try {
        const data = await getUserSettings(settings.serverUrl, token);
        if (!cancelled) setServerUserSettings(data);
      } catch (e) {
        if (!cancelled) setServerUserSettingsError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [settingsOpen, settings?.serverUrl, settings?.accessToken, settings]);

  useEffect(() => {
    if (!conversationId || !(settings?.accessToken ?? "").trim()) {
      setFinalExportReady(false);
      return;
    }
    if (uiMode !== "recording") return;
    let cancelled = false;
    void (async () => {
      try {
        const cur = await loadSettings();
        const fd = await getConversationDetail(cur, conversationId, { tier: "final" });
        if (!cancelled) setFinalExportReady(fd.transcript_status === "success");
      } catch {
        if (!cancelled) setFinalExportReady(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId, settings?.accessToken, settings?.serverUrl, uiMode]);

  useEffect(() => {
    const onStorageChanged = (
      changes: Record<string, chrome.storage.StorageChange>,
      areaName: string
    ) => {
      if (areaName !== "local") return;
      if (!changes.voiceTranscriberSettings) return;
      const next = changes.voiceTranscriberSettings.newValue as ExtensionSettings | undefined;
      if (next) setSettings(next);
    };
    chrome.storage.onChanged.addListener(onStorageChanged);
    return () => chrome.storage.onChanged.removeListener(onStorageChanged);
  }, []);

  useLayoutEffect(() => {
    // Subscribe before audio sends chunks (layout effect after conversationId is committed).
    // Late partials after Stop are ignored via ignoreLiveTranscriptRef (see handleStop / handleStart).
    if (!settings || !conversationId) return;
    const client = new TranscriptWebSocketClient(
      settings.serverUrl,
      conversationId,
      settings.accessToken
    );
    wsRef.current = client;
    const onMsg = (msg: TranscriptMessage) => {
      if (ignoreLiveTranscriptRef.current) return;
      if (msg.type === "transcript") {
        // Append each partial as its own line: chunk/windowed ASR slices are independent; merging
        // into one string can drop text on bad suffix/prefix overlap. Final server transcript replaces all.
        const t = msg.text.trim();
        if (!t) return;
        setTranscriptLines((prev) => [...prev, { id: crypto.randomUUID(), text: t }]);
      } else if (msg.type === "error") {
        setError(msg.message);
      }
    };
    client.addListener(onMsg);
    client.connect();
    return () => {
      client.removeListener(onMsg);
      client.close();
      wsRef.current = null;
    };
  }, [settings, conversationId, transcriptWsBootKey]);

  const transcriptText = useMemo(
    () => transcriptLines.map((l) => l.text).join("\n"),
    [transcriptLines]
  );

  const handleStart = async () => {
    if (!settings) return;
    if (status === "recording") return;
    transcriptPollAbortRef.current?.abort();
    transcriptPollAbortRef.current = null;
    ignoreLiveTranscriptRef.current = false;
    setError(null);
    setUploadInfo(null);
    setTranscriptLines([]);
    setFinalExportReady(false);

    const ok = await refreshSession(settings);
    if (!ok) return;

    chrome.runtime.sendMessage({ type: "create_conversation_for_recording" }, async (response) => {
      if (chrome.runtime.lastError) {
        setError(chrome.runtime.lastError.message ?? "Failed to start recording");
        return;
      }
      if (!response?.ok) {
        setError(response?.error ?? "Failed to start recording");
        return;
      }
      const newConversationId = response.conversationId as string | undefined;
      if (!newConversationId) {
        setError("Backend did not return conversation id");
        return;
      }

      try {
        setConversationId(newConversationId);
        if (settings.audioSource === "microphone") {
          const win = await chrome.windows.getCurrent();
          if (win.id == null) throw new Error("Could not determine browser window for recording session");
          await new Promise<void>((resolve, reject) => {
            chrome.runtime.sendMessage(
              {
                type: "bg_start_offscreen_recording",
                settings,
                conversationId: newConversationId,
                windowId: win.id,
              },
              (resp) => {
                if (chrome.runtime.lastError) {
                  reject(new Error(chrome.runtime.lastError.message ?? "Background error"));
                  return;
                }
                if (!resp?.ok) {
                  reject(new Error(resp?.error ?? "Failed to start offscreen recording"));
                  return;
                }
                resolve();
              }
            );
          });
          recordingSurfaceRef.current = "offscreen";
        } else {
          if (!recorderRef.current) recorderRef.current = new AudioRecorderController();
          await recorderRef.current.start({
            settings,
            conversationId: newConversationId,
            onBeforeStop: () => {
              ignoreLiveTranscriptRef.current = true;
            },
            onAfterStop: () => {
              recordingSurfaceRef.current = null;
              setStatus("idle");
              void chrome.runtime.sendMessage({ type: "bg_clear_recording_session" });
              const s = settingsRef.current;
              const cid = conversationIdRef.current;
              if (uiMode === "recording" && s && cid) {
                startPostStopTranscriptPoll(s, cid);
              }
            },
          });
          recordingSurfaceRef.current = "popup";
          const win = await chrome.windows.getCurrent();
          if (win.id == null) throw new Error("Could not determine browser window");
          let capturedTabId: number | undefined;
          if (settings.audioSource === "tab" || settings.audioSource === "dual") {
            const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
            if (tabs[0]?.id != null) capturedTabId = tabs[0].id;
          }
          await new Promise<void>((resolve, reject) => {
            chrome.runtime.sendMessage(
              {
                type: "bg_register_popup_recording",
                windowId: win.id,
                capturedTabId,
                conversationId: newConversationId,
                source:
                  settings.audioSource === "microphone"
                    ? "microphone"
                    : settings.audioSource === "dual"
                      ? "dual"
                      : "tab",
              },
              (resp) => {
                if (chrome.runtime.lastError) {
                  reject(new Error(chrome.runtime.lastError.message ?? "Background error"));
                  return;
                }
                if (!resp?.ok) {
                  reject(new Error(resp?.error ?? "Failed to register recording session"));
                  return;
                }
                resolve();
              }
            );
          });
        }
        setStatus("recording");
      } catch (e) {
        setConversationId(null);
        recordingSurfaceRef.current = null;
        setError(e instanceof Error ? e.message : String(e));
      }
    });
  };

  handleStartRef.current = handleStart;

  useEffect(() => {
    if (uiMode !== "recording") return;
    const onMsg = (msg: unknown) => {
      if (
        msg &&
        typeof msg === "object" &&
        (msg as { type?: string }).type === "vt_remote_start_recording"
      ) {
        void handleStartRef.current();
      }
    };
    chrome.runtime.onMessage.addListener(onMsg);
    return () => chrome.runtime.onMessage.removeListener(onMsg);
  }, [uiMode]);

  const handleStop = async () => {
    ignoreLiveTranscriptRef.current = true;
    const cid = conversationId;
    const s = settings;
    const surfaceBeforeStop = recordingSurfaceRef.current;
    let stopOk = true;
    try {
      if (recordingSurfaceRef.current === "offscreen") {
        await new Promise<void>((resolve, reject) => {
          chrome.runtime.sendMessage({ type: "bg_stop_offscreen_recording" }, (resp) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message ?? "Background error"));
              return;
            }
            if (!resp?.ok) {
              reject(new Error(resp?.error ?? "Failed to stop recording"));
              return;
            }
            resolve();
          });
        });
        recordingSurfaceRef.current = null;
      } else {
        await recorderRef.current?.stop();
        recordingSurfaceRef.current = null;
      }
    } catch (e) {
      stopOk = false;
      setError(e instanceof Error ? e.message : String(e));
    }
    setStatus("idle");
    // Tab/popup: `recorder.stop` → `onAfterStop` already polls. Offscreen mic has no onAfterStop here.
    if (stopOk && uiMode === "recording" && s && cid && surfaceBeforeStop === "offscreen") {
      startPostStopTranscriptPoll(s, cid);
    }
  };

  const handleDownloadTranscript = () => {
    const blob = new Blob([transcriptText], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "transcript.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadTextFile = (body: string, filename: string, mime: string) => {
    const blob = new Blob([body], { type: `${mime};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportMd = async () => {
    if (!settings || !conversationId) return;
    setError(null);
    const ok = await refreshSession(settings);
    if (!ok) return;
    try {
      const md = await fetchConversationExport(settings, conversationId, "md");
      downloadTextFile(md, `conversation-${conversationId}.md`, "text/markdown");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleExportJson = async () => {
    if (!settings || !conversationId) return;
    setError(null);
    const ok = await refreshSession(settings);
    if (!ok) return;
    try {
      const json = await fetchConversationExport(settings, conversationId, "json");
      downloadTextFile(json, `conversation-${conversationId}.json`, "application/json");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRefreshTranscriptFromServer = async () => {
    if (!settings || !conversationId) return;
    transcriptPollAbortRef.current?.abort();
    transcriptPollAbortRef.current = null;
    setError(null);
    setUploadInfo(null);
    const ok = await refreshSession(settings);
    if (!ok) return;
    try {
      const detail = await getConversationDetail(settings, conversationId);
      const finalSnap = await getConversationDetail(settings, conversationId, { tier: "final" });
      setFinalExportReady(finalSnap.transcript_status === "success");
      const segs = detail.transcript ?? [];
      if (segs.length) {
        setTranscriptLines(segs.map((s) => ({ id: crypto.randomUUID(), text: s.text })));
      } else {
        setTranscriptLines([]);
        setUploadInfo("Server transcript has no segments yet (ASR may still be processing).");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleUploadFile = async () => {
    if (!settings) return;
    setError(null);
    setUploadInfo(null);
    const ok = await refreshSession(settings);
    if (!ok) return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "audio/*,.webm,.wav,.mp3,.m4a,.aac,.ogg,.flac,.opus";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const data = await postUploadAudio(settings, file, uiMode === "recording" ? conversationId : null);
        if (uiMode === "shell") {
          setUploadInfo(`Uploaded. Conversation id: ${data.conversation_id}`);
        } else {
          setConversationId(data.conversation_id);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    input.click();
  };

  const handleGenerateSummary = () => {
    // Summary generation is handled by backend (LLM task) once conversation is uploaded.
    // Here we could call an API endpoint to trigger it; left as a placeholder.
    alert("Summary generation is triggered on the backend (not implemented in popup).");
  };

  const updateLocalSettings = async (partial: Partial<ExtensionSettings>) => {
    if (!settings) return;
    const updated = await updateSettings(partial);
    setSettings(updated);
    chrome.runtime.sendMessage({ type: "update_settings", payload: partial }, () => {});
  };

  const onServerUrlChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ serverUrl: e.target.value });

  const onAudioSourceChange = (e: React.ChangeEvent<HTMLSelectElement>) =>
    void updateLocalSettings({ audioSource: e.target.value as AudioSource });

  const onChunkSizeChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ chunkSizeMs: Number(e.target.value) || 1000 });

  const onRealtimeModeChange = (e: React.ChangeEvent<HTMLSelectElement>) =>
    void updateLocalSettings({ realtimeMode: e.target.value as RealtimeMode });

  const onTtlChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ ttlDays: Number(e.target.value) || 7 });

  const onMaxDurationChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ maxConversationMinutes: Number(e.target.value) || 120 });

  const openExtensionMicSettings = () => {
    const url = `chrome://settings/content/siteDetails?site=chrome-extension://${chrome.runtime.id}`;
    chrome.tabs.create({ url });
  };

  const onLoginClick = (provider: "google" | "yandex") => {
    if (!settings) return;
    setError(null);
    setUploadInfo(null);
    setOauthBusy(true);
    chrome.runtime.sendMessage({ type: "vt_oauth_login", provider }, (resp) => {
      const lastErr = chrome.runtime.lastError;
      if (lastErr) {
        setOauthBusy(false);
        setError(lastErr.message);
        return;
      }
      const r = resp as { ok?: boolean; error?: string } | undefined;
      if (r?.ok === false) {
        setOauthBusy(false);
        setError(r.error ?? "Could not start sign-in.");
      }
    });
  };

  if (!settings) {
    return <div style={{ padding: 12 }}>Loading settings…</div>;
  }

  const isSidePanel = layout === "sidepanel";

  const toggleSidePanelFromPopup = async () => {
    if (!chrome.sidePanel?.open) {
      setError("Side Panel is not available in this Chromium version (need 114+).");
      return;
    }
    setError(null);
    try {
      const wid = await getExtensionHostWindowId();
      if (wid == null) throw new Error("No browser window for extension");
      const open = await isSidePanelPresentForWindow(wid);
      if (open) {
        await setSidePanelCloseSuppression(wid);
        await closeExtensionSidePanel(wid);
        await clearSidePanelPresence(wid);
        setSidePanelOpen(false);
      } else {
        await clearSidePanelCloseSuppression(wid);
        await chrome.sidePanel.open({ windowId: wid });
        window.close();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const openUploadWindow = () => {
    setError(null);
    const url = chrome.runtime.getURL("upload.html");
    chrome.windows.create({
      url,
      type: "popup",
      width: 460,
      height: 260,
      focused: true,
    });
  };

  const shellBody =
    uiMode === "shell" ? (
      <>
        <p style={{ margin: 0, fontSize: 12, color: "#444", lineHeight: 1.35 }}>
          Live recording and transcript run in the <strong>side panel</strong>. Sign in here, adjust the server URL
          in Settings, then open the panel to start.
        </p>
        {offscreenMicActive ? (
          <div
            style={{
              fontSize: 12,
              lineHeight: 1.3,
              padding: "8px 10px",
              borderRadius: 6,
              background: "#fff3e0",
              border: "1px solid #ffcc80",
            }}
          >
            Microphone recording is active (offscreen). Stop from the extension toolbar menu →{" "}
            <strong>Stop recording (microphone)</strong>, or use Stop in the side panel if it is open.
          </div>
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <button
            type="button"
            onClick={() => void toggleSidePanelFromPopup()}
            disabled={oauthBusy}
            style={{ padding: "10px 12px", fontWeight: 600 }}
          >
            {sidePanelOpen ? "Close recording side panel" : "Open recording side panel"}
          </button>
          <button type="button" onClick={openUploadWindow} disabled={oauthBusy} style={{ padding: "8px 12px" }}>
            Upload audio file…
          </button>
        </div>
        <div
          style={{
            marginTop: 2,
            fontSize: 12,
            color: "#555",
            lineHeight: 1.2,
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "6px 10px",
          }}
        >
          <span>
            Auth:{" "}
            <strong
              style={{
                color:
                  sessionOk === true ? "green" : sessionOk === false ? "#777" : "#999",
              }}
            >
              {sessionOk === null
                ? "checking…"
                : sessionOk
                  ? "signed in"
                  : settings.accessToken
                    ? "invalid token (clearing…)"
                    : "not signed in"}
            </strong>
          </span>
          {sessionOk === true ? (
            <button type="button" onClick={() => void handleLogout()} disabled={oauthBusy} style={{ padding: "4px 12px" }}>
              Log out
            </button>
          ) : null}
          {oauthBusy ? <span>Opening provider…</span> : null}
        </div>
        <div style={{ fontSize: 11, color: "#666", lineHeight: 1.25 }}>
          Toolbar menu → <strong>Start recording…</strong> opens the side panel and starts the same flow as Start
          inside the panel.
        </div>
      </>
    ) : null;

  return (
    <div
      style={{
        fontFamily: "system-ui, sans-serif",
        padding: 12,
        width: isSidePanel ? "100%" : 360,
        height: isSidePanel ? "100vh" : uiMode === "shell" ? 480 : 580,
        maxHeight: isSidePanel ? "100vh" : uiMode === "shell" ? 520 : 600,
        boxSizing: "border-box",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        minWidth: 0,
        position: "relative",
      }}
    >
      {uiMode === "recording" && isSidePanel ? (
        <div style={{ fontSize: 11, color: "#555", lineHeight: 1.25 }}>
          Primary recording surface — Start/Stop, transcript, and tab capture run here. For login and server URL, use
          the toolbar popup <strong>Settings</strong>.
        </div>
      ) : null}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: 18, lineHeight: 1.1 }}>Voice Transcriber</h2>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          {uiMode === "recording" && !isSidePanel && chrome.sidePanel?.open ? (
            <button
              type="button"
              onClick={() => void toggleSidePanelFromPopup()}
              disabled={oauthBusy}
              style={{ padding: "6px 8px" }}
            >
              {sidePanelOpen ? "Close panel" : "Side panel"}
            </button>
          ) : null}
          {!isSidePanel ? (
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              disabled={oauthBusy}
              style={{ padding: "6px 10px", whiteSpace: "nowrap" }}
            >
              Settings…
            </button>
          ) : null}
        </div>
      </div>

      {uiMode === "shell" ? (
        <div style={{ flex: "1 1 auto", minHeight: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {shellBody}
        </div>
      ) : null}

      {uiMode === "recording" ? (
        <>
      <section style={{ flex: "0 0 auto", minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={handleStart}
            disabled={status === "recording" || oauthBusy}
            style={{ flex: 1, minWidth: 0 }}
          >
            Start Recording
          </button>
          <button
            onClick={handleStop}
            disabled={status !== "recording"}
            style={{ flex: 1, minWidth: 0 }}
          >
            Stop Recording
          </button>
        </div>
        <div style={{ marginTop: 4, fontSize: 12, lineHeight: 1.2 }}>
          Status:{" "}
          <strong style={{ color: status === "recording" ? "green" : "gray" }}>
            {status}
          </strong>
        </div>
        {settings.audioSource === "microphone" ? (
          <div style={{ marginTop: 4, fontSize: 11, color: "#555", lineHeight: 1.25 }}>
            Microphone recording runs in a hidden offscreen page — you can minimize the side panel while recording.
            Use the toolbar menu → <strong>Stop recording (microphone)</strong> or press Stop here.
          </div>
        ) : (
          <div style={{ marginTop: 4, fontSize: 11, color: "#555", lineHeight: 1.25 }}>
            Tab audio is captured in this panel — keep it open while recording. If you close the captured tab,
            recording stops automatically (WebSocket closes; upload runs when chunks exist).
          </div>
        )}
        <div
          style={{
            marginTop: 2,
            fontSize: 12,
            color: "#555",
            lineHeight: 1.2,
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "6px 10px",
          }}
        >
          <span>
            Auth:{" "}
            <strong
              style={{
                color:
                  sessionOk === true
                    ? "green"
                    : sessionOk === false
                      ? "#777"
                      : "#999",
              }}
            >
              {sessionOk === null
                ? "checking…"
                : sessionOk
                  ? "signed in"
                  : settings.accessToken
                    ? "invalid token (clearing…)"
                    : "not signed in"}
            </strong>
          </span>
          {sessionOk === true ? (
            <button type="button" onClick={() => void handleLogout()} disabled={oauthBusy} style={{ padding: "4px 12px" }}>
              Log out
            </button>
          ) : null}
          {oauthBusy ? <span>Opening provider…</span> : null}
        </div>
      </section>

      <section
        style={{
          flex: "1 1 auto",
          minHeight: 0,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={handleDownloadTranscript}
            title="Сохранить текущий текст из live (fast) на диск; это не канонический final-экспорт."
            style={{ flex: "1 1 120px", minWidth: 0 }}
          >
            Save live text
          </button>
          {!isSidePanel ? (
            <button onClick={() => void handleUploadFile()} style={{ flex: "1 1 120px", minWidth: 0 }}>
              Upload audio file
            </button>
          ) : null}
          <button type="button" onClick={() => void handleRefreshTranscriptFromServer()} disabled={!conversationId} style={{ flex: "1 1 120px", minWidth: 0 }}>
            Refresh from server
          </button>
          <button
            type="button"
            onClick={() => void handleExportMd()}
            disabled={!conversationId || !finalExportReady}
            title={
              !conversationId
                ? undefined
                : !finalExportReady
                  ? "Final transcript not ready yet (server batch ASR after stop/upload)."
                  : "GET /export?format=md&tier=final"
            }
            style={{ flex: "1 1 120px", minWidth: 0 }}
          >
            Export final (MD)
          </button>
          <button
            type="button"
            onClick={() => void handleExportJson()}
            disabled={!conversationId || !finalExportReady}
            title={
              !conversationId
                ? undefined
                : !finalExportReady
                  ? "Final transcript not ready yet (server batch ASR after stop/upload)."
                  : "GET /export?format=json&tier=final"
            }
            style={{ flex: "1 1 120px", minWidth: 0 }}
          >
            Export final (JSON)
          </button>
          <button
            type="button"
            onClick={() => setTranscriptWsBootKey((k) => k + 1)}
            disabled={!conversationId}
            style={{ flex: "1 1 100%", minWidth: 0 }}
          >
            Reconnect transcript
          </button>
        </div>
        <button type="button" onClick={handleGenerateSummary} style={{ width: "100%" }}>
          Generate Summary
        </button>
        <div
          style={{
            border: "1px solid #ccc",
            borderRadius: 4,
            padding: 8,
            flex: "1 1 auto",
            minHeight: 0,
            minWidth: 0,
            overflowY: "auto",
            fontSize: 12,
            whiteSpace: "pre-wrap",
          }}
        >
          {transcriptLines.length === 0 ? (
            <span style={{ color: "#777" }}>Live transcript will appear here…</span>
          ) : (
            transcriptLines.map((line) => <div key={line.id}>{line.text}</div>)
          )}
        </div>
      </section>
        </>
      ) : null}

      <div
        style={{
          flex: "0 0 auto",
          borderTop: "1px solid #e6e6e6",
          paddingTop: 6,
          minHeight: 34,
          maxHeight: 92,
          overflowY: "auto",
          color: error ? "red" : uploadInfo ? "#2e7d32" : "#777",
          fontSize: 12,
          lineHeight: 1.25,
          wordBreak: "break-word",
          minWidth: 0,
        }}
      >
        {error ? error : uploadInfo ?? "No errors"}
      </div>

      {settingsOpen ? (
        <div
          role="presentation"
          onClick={() => setSettingsOpen(false)}
          style={{
            position: "absolute",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            display: "flex",
            alignItems: "stretch",
            justifyContent: "center",
            padding: 10,
            boxSizing: "border-box",
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Settings"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "100%",
              maxWidth: 340,
              maxHeight: "100%",
              margin: "0 auto",
              background: "#fff",
              borderRadius: 8,
              border: "1px solid #ddd",
              boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
                padding: "10px 12px",
                borderBottom: "1px solid #eee",
              }}
            >
              <div style={{ fontSize: 14, fontWeight: 600 }}>Settings</div>
              <button type="button" onClick={() => setSettingsOpen(false)} style={{ padding: "4px 10px" }}>
                Close
              </button>
            </div>

            <div style={{ padding: 12, overflowY: "auto", minHeight: 0, flex: "1 1 auto" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <label style={{ display: "block", fontSize: 12 }}>
                  Server URL
                  <input
                    type="text"
                    value={settings.serverUrl}
                    onChange={onServerUrlChange}
                    style={{
                      width: "100%",
                      boxSizing: "border-box",
                      marginTop: 4,
                      padding: "6px 8px",
                      border: "1px solid #ccc",
                      borderRadius: 4,
                    }}
                  />
                </label>

                {sessionOk === true ? (
                  <button type="button" onClick={() => void handleLogout()} disabled={oauthBusy} style={{ width: "100%", padding: "8px 12px" }}>
                    Log out
                  </button>
                ) : (
                  <>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        type="button"
                        onClick={() => onLoginClick("google")}
                        disabled={oauthBusy}
                        style={{ flex: 1, minWidth: 0 }}
                      >
                        Sign in with Google
                      </button>
                      <button
                        type="button"
                        onClick={() => onLoginClick("yandex")}
                        disabled={oauthBusy}
                        style={{ flex: 1, minWidth: 0 }}
                      >
                        Sign in with Yandex
                      </button>
                    </div>
                  </>
                )}

                <label style={{ display: "block", fontSize: 12 }}>
                  Audio source
                  <select
                    value={settings.audioSource}
                    onChange={onAudioSourceChange}
                    style={{ width: "100%", boxSizing: "border-box", marginTop: 4 }}
                  >
                    <option value="microphone">Microphone</option>
                    <option value="tab">Tab audio</option>
                    <option value="dual">Microphone + tab (mixed)</option>
                    <option value="system">System audio (not implemented)</option>
                  </select>
                </label>
                {settings.audioSource === "microphone" || settings.audioSource === "dual" ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: 11, color: "#666", lineHeight: 1.25 }}>
                      If Chrome doesn’t show a microphone prompt (or you dismissed it), allow microphone for this extension in
                      Chrome site settings.
                    </div>
                    <button type="button" onClick={openExtensionMicSettings} style={{ width: "100%" }}>
                      Open microphone settings
                    </button>
                  </div>
                ) : null}

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: 8,
                  }}
                >
                  <label style={{ display: "block", fontSize: 12, minWidth: 0 }}>
                    Chunk (ms)
                    <input
                      type="number"
                      min={500}
                      max={2000}
                      step={100}
                      value={settings.chunkSizeMs}
                      onChange={onChunkSizeChange}
                      style={{ width: "100%", boxSizing: "border-box", marginTop: 4 }}
                    />
                  </label>

                  <label style={{ display: "block", fontSize: 12, minWidth: 0 }}>
                    TTL (days)
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={settings.ttlDays}
                      onChange={onTtlChange}
                      style={{ width: "100%", boxSizing: "border-box", marginTop: 4 }}
                    />
                  </label>
                </div>

                <label style={{ display: "block", fontSize: 12 }}>
                  Realtime mode
                  <select
                    value={settings.realtimeMode}
                    onChange={onRealtimeModeChange}
                    style={{ width: "100%", boxSizing: "border-box", marginTop: 4 }}
                  >
                    <option value="chunk">Chunk → ASR → partial transcript</option>
                    <option value="windowed">Window buffer → ASR → transcript</option>
                  </select>
                </label>

                <div style={{ fontSize: 12, lineHeight: 1.25 }}>
                  <div style={{ fontWeight: 600 }}>Language</div>
                  <div style={{ marginTop: 4, color: "#555" }}>
                    Server default:{" "}
                    <strong>
                      {settings.accessToken
                        ? serverUserSettings
                          ? serverUserSettings.default_language
                          : serverUserSettingsError
                            ? "unavailable"
                            : "loading…"
                        : "not signed in"}
                    </strong>
                  </div>
                  {serverUserSettingsError ? (
                    <div style={{ marginTop: 4, fontSize: 11, color: "#b00020" }}>
                      {serverUserSettingsError}
                    </div>
                  ) : null}
                  <div style={{ marginTop: 4, fontSize: 11, color: "#666" }}>
                    Language hint is managed on the server (Web UI Settings). The extension does not override it.
                  </div>
                </div>

                <label style={{ display: "block", fontSize: 12 }}>
                  Max duration (minutes)
                  <input
                    type="number"
                    min={1}
                    max={120}
                    value={settings.maxConversationMinutes}
                    onChange={onMaxDurationChange}
                    style={{ width: "100%", boxSizing: "border-box", marginTop: 4 }}
                  />
                </label>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

