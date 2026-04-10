import { ExtensionSettings } from "../settings/storage";

export type TranscriptMessage =
  | { type: "transcript"; text: string }
  | { type: "error"; message: string };

type Listener = (msg: TranscriptMessage) => void;

/**
 * Simple reconnecting WebSocket client for transcript stream.
 */
export class TranscriptWebSocketClient {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly token: string | null;
  private listeners: Set<Listener> = new Set();
  private reconnectAttempts = 0;
  private closedByClient = false;

  constructor(serverUrl: string, conversationId: string, token: string | null) {
    const base = serverUrl.replace(/^http/, "ws").replace(/\/+$/, "");
    this.url = `${base}/ws/transcript/${conversationId}`;
    this.token = token;
  }

  connect(): void {
    this.closedByClient = false;
    const urlWithParams =
      this.token == null ? this.url : `${this.url}?token=${encodeURIComponent(this.token)}`;
    this.ws = new WebSocket(urlWithParams);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as TranscriptMessage;
        this.listeners.forEach((l) => l(data));
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      if (!this.closedByClient) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      if (!this.closedByClient) {
        this.scheduleReconnect();
      }
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts > 5) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 10000);
    this.reconnectAttempts += 1;
    setTimeout(() => this.connect(), delay);
  }

  close(): void {
    this.closedByClient = true;
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

/**
 * Audio WebSocket client for sending chunks to /ws/audio.
 */
export class AudioWebSocketClient {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private readonly token: string | null;

  constructor(settings: ExtensionSettings, conversationId: string) {
    const base = settings.serverUrl.replace(/^http/, "ws").replace(/\/+$/, "");
    this.url = `${base}/ws/audio/${conversationId}`;
    this.token = settings.accessToken;
  }

  connect(): void {
    const urlWithParams =
      this.token == null ? this.url : `${this.url}?token=${encodeURIComponent(this.token)}`;
    this.ws = new WebSocket(urlWithParams);
  }

  sendChunk(chunk: Blob): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(chunk);
  }

  close(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      this.ws.close();
    }
    this.ws = null;
  }
}

