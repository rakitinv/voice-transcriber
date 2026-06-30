import { ExtensionSettings } from "../settings/storage";

export type TranscriptMessage =
  | { type: "transcript"; text: string; realtime_mode?: string | null }
  | { type: "error"; message: string }
  | { type: "keepalive" }
  | { type: "ready"; channel?: string; conversation_id?: string; message?: string }
  | { type: "transcript_partial"; conversation_id?: string; text: string; realtime_mode?: string };

type Listener = (msg: TranscriptMessage) => void;

function openWebSocketWithAuth(url: string, token: string | null): WebSocket {
  if (token && token.trim()) {
    return new WebSocket(url, [`bearer.${token}`]);
  }
  return new WebSocket(url);
}

/**
 * Reconnecting WebSocket client for transcript stream (Phase B: /ws/transcript).
 * Auth: Sec-WebSocket-Protocol `bearer.<JWT>` when token set (see docs/WEBSOCKET.md).
 */
export class TranscriptWebSocketClient {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly token: string | null;
  private listeners: Set<Listener> = new Set();
  private reconnectAttempts = 0;
  private closedByClient = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(serverUrl: string, conversationId: string, token: string | null) {
    const base = serverUrl.replace(/^http/, "ws").replace(/\/+$/, "");
    this.url = `${base}/ws/transcript/${conversationId}`;
    this.token = token;
  }

  connect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    const socket = openWebSocketWithAuth(this.url, this.token);
    this.ws = socket;

    socket.onopen = () => {
      if (this.ws !== socket) return;
      this.reconnectAttempts = 0;
    };

    socket.onmessage = (event) => {
      if (this.ws !== socket) return;
      try {
        const data = JSON.parse(event.data as string) as TranscriptMessage;
        if (data && (data as { type?: string }).type === "transcript_partial") {
          const raw = data as { text?: unknown; realtime_mode?: unknown };
          const text = raw.text;
          const mode =
            typeof raw.realtime_mode === "string" && raw.realtime_mode.trim()
              ? raw.realtime_mode.trim().toLowerCase()
              : null;
          if (typeof text === "string" && text.trim()) {
            this.listeners.forEach((l) =>
              l({ type: "transcript", text: text.trim(), realtime_mode: mode } as TranscriptMessage)
            );
          }
          return;
        }
        this.listeners.forEach((l) => l(data));
      } catch {
        // ignore malformed messages
      }
    };

    socket.onclose = () => {
      if (this.ws === socket) this.ws = null;
      if (!this.closedByClient) this.scheduleReconnect();
    };

    socket.onerror = () => {
      // Reconnect is driven from onclose in normal browsers.
    };
  }

  private scheduleReconnect(): void {
    if (this.closedByClient) return;
    if (this.reconnectAttempts > 5) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 10000);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.closedByClient) return;
      this.connect();
    }, delay);
  }

  close(): void {
    this.closedByClient = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      this.ws.close();
    }
    this.ws = null;
  }

  addListener(listener: Listener): void {
    this.listeners.add(listener);
  }

  removeListener(listener: Listener): void {
    this.listeners.delete(listener);
  }
}

type FinalizeAckStatus = "accepted" | "duplicate" | "error";

/**
 * Audio WebSocket client for sending chunks to /ws/audio with optional reconnect.
 * Auth: Sec-WebSocket-Protocol `bearer.<JWT>` when token set.
 */
export class AudioWebSocketClient {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly token: string | null;
  private pendingChunks: Blob[] = [];
  private reconnectAttempts = 0;
  private closedByClient = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(settings: ExtensionSettings, conversationId: string) {
    const base = settings.serverUrl.replace(/^http/, "ws").replace(/\/+$/, "");
    this.url = `${base}/ws/audio/${conversationId}`;
    this.token = settings.accessToken;
  }

  connect(): void {
    if (this.closedByClient) return;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    const socket = openWebSocketWithAuth(this.url, this.token);
    this.ws = socket;

    socket.addEventListener("open", () => {
      if (this.ws !== socket) return;
      this.reconnectAttempts = 0;
      for (const chunk of this.pendingChunks) {
        if (socket.readyState === WebSocket.OPEN) socket.send(chunk);
      }
      this.pendingChunks = [];
    });

    socket.addEventListener("close", () => {
      if (this.ws === socket) this.ws = null;
      if (!this.closedByClient) this.scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      // Reconnect after close event.
    });
  }

  private scheduleReconnect(): void {
    if (this.closedByClient) return;
    if (this.reconnectAttempts > 5) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 10000);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.closedByClient) return;
      this.connect();
    }, delay);
  }

  waitUntilOpen(timeoutMs: number = 8000): Promise<void> {
    const ws = this.ws;
    if (!ws) return Promise.reject(new Error("WebSocket not initialized"));
    if (ws.readyState === WebSocket.OPEN) return Promise.resolve();
    if (ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED) {
      return Promise.reject(new Error("WebSocket closed before open"));
    }

    return new Promise((resolve, reject) => {
      const onOpen = () => {
        cleanup();
        resolve();
      };
      const onClose = (ev: Event) => {
        cleanup();
        const ce = ev as CloseEvent;
        const reason = (ce.reason || "").trim();
        reject(
          new Error(
            `WebSocket closed before open (code=${ce.code}` + (reason ? `, reason=${reason}` : "") + ")"
          )
        );
      };
      const onError = () => {
        cleanup();
        reject(new Error("WebSocket failed to open (network error)"));
      };
      const t = setTimeout(() => {
        cleanup();
        reject(new Error("WebSocket open timeout"));
      }, timeoutMs);

      const cleanup = () => {
        clearTimeout(t);
        ws.removeEventListener("open", onOpen);
        ws.removeEventListener("error", onError);
        ws.removeEventListener("close", onClose);
      };

      ws.addEventListener("open", onOpen, { once: true });
      ws.addEventListener("error", onError, { once: true });
      ws.addEventListener("close", onClose, { once: true });
    });
  }

  sendChunk(chunk: Blob): void {
    if (!this.ws) {
      this.pendingChunks.push(chunk);
      return;
    }
    if (this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(chunk);
      return;
    }
    if (this.ws.readyState === WebSocket.CONNECTING) {
      this.pendingChunks.push(chunk);
      return;
    }
    this.pendingChunks.push(chunk);
  }

  sendFinalize(finalizeId: string): void {
    const payload = JSON.stringify({ type: "finalize", finalize_id: finalizeId });
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(payload);
    }
  }

  waitForFinalizeAck(finalizeId: string, timeoutMs: number = 30_000): Promise<FinalizeAckStatus> {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return Promise.resolve("error");
    }

    return new Promise((resolve) => {
      const onMessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data as string) as {
            type?: string;
            finalize_id?: string;
            status?: string;
          };
          if (data.type === "finalize_ack" && data.finalize_id === finalizeId) {
            cleanup();
            resolve(data.status === "duplicate" ? "duplicate" : "accepted");
            return;
          }
          if (data.type === "finalize_error") {
            cleanup();
            resolve("error");
          }
        } catch {
          // ignore malformed messages
        }
      };

      const t = setTimeout(() => {
        cleanup();
        resolve("error");
      }, timeoutMs);

      const cleanup = () => {
        clearTimeout(t);
        ws.removeEventListener("message", onMessage);
      };

      ws.addEventListener("message", onMessage);
    });
  }

  close(): void {
    this.closedByClient = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      this.ws.close();
    }
    this.ws = null;
    this.pendingChunks = [];
  }
}
