import type { ExtensionSettings } from "../settings/storage";

export type TranscriptTier = "auto" | "fast" | "final";

export type TranscriptSegmentDto = {
  text: string;
  speaker?: string;
  start?: number;
  end?: number;
};

export type ConversationDetailDto = {
  id: string;
  transcript: TranscriptSegmentDto[];
  refetch_recommended?: boolean;
  /** Статус строки транскрипта для выбранного tier (§17). */
  transcript_status?: string | null;
  transcript_kind?: string | null;
  /** §7.6 rolling-summary цепочки записи (null если выключено на сервере). */
  recording_session_summary_status?: string | null;
};

/** GET /api/conversations/{id}/session-summary (§7.6) */
export type RecordingSessionSummaryDto = {
  recording_session_id: string;
  status: string;
  summary_md: string | null;
  error: string | null;
  updated_at: string | null;
};

function authHeaders(settings: ExtensionSettings): Record<string, string> {
  const h: Record<string, string> = {};
  const t = (settings.accessToken ?? "").trim();
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

export async function getConversationDetail(
  settings: ExtensionSettings,
  conversationId: string,
  opts?: { tier?: TranscriptTier }
): Promise<ConversationDetailDto> {
  const base = settings.serverUrl.replace(/\/+$/, "");
  const params = new URLSearchParams();
  if (opts?.tier) params.set("tier", opts.tier);
  const qs = params.toString();
  const url = `${base}/api/conversations/${encodeURIComponent(conversationId)}${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, { headers: authHeaders(settings) });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`Запрос разговора не удался: ${res.status} ${t.slice(0, 200)}`);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  const transcript = (raw.transcript as TranscriptSegmentDto[] | undefined) ?? [];
  return {
    id: String(raw.id ?? conversationId),
    transcript,
    refetch_recommended: raw.refetch_recommended === true,
    transcript_status:
      typeof raw.transcript_status === "string" || raw.transcript_status === null
        ? (raw.transcript_status as string | null)
        : undefined,
    transcript_kind:
      typeof raw.transcript_kind === "string" || raw.transcript_kind === null
        ? (raw.transcript_kind as string | null)
        : undefined,
    recording_session_summary_status:
      typeof raw.recording_session_summary_status === "string" ||
      raw.recording_session_summary_status === null
        ? (raw.recording_session_summary_status as string | null)
        : undefined,
  };
}

export async function getSessionSummary(
  settings: ExtensionSettings,
  conversationId: string
): Promise<RecordingSessionSummaryDto> {
  const base = settings.serverUrl.replace(/\/+$/, "");
  const url = `${base}/api/conversations/${encodeURIComponent(conversationId)}/session-summary`;
  const res = await fetch(url, { headers: authHeaders(settings) });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`Запрос сводки не удался: ${res.status} ${t.slice(0, 200)}`);
  }
  return (await res.json()) as RecordingSessionSummaryDto;
}

export async function retrySessionSummary(
  settings: ExtensionSettings,
  conversationId: string
): Promise<void> {
  const base = settings.serverUrl.replace(/\/+$/, "");
  const url = `${base}/api/conversations/${encodeURIComponent(conversationId)}/session-summary/retry`;
  const res = await fetch(url, {
    method: "POST",
    headers: authHeaders(settings),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`Повтор сводки не удался: ${res.status} ${t.slice(0, 200)}`);
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Ожидает завершения асинхронной сводки (pending/running → success/failed/…). */
export async function pollSessionSummary(
  settings: ExtensionSettings,
  conversationId: string,
  opts?: {
    onUpdate?: (data: RecordingSessionSummaryDto) => void;
    maxAttempts?: number;
    intervalMs?: number;
  }
): Promise<RecordingSessionSummaryDto> {
  const maxAttempts = opts?.maxAttempts ?? 90;
  const intervalMs = opts?.intervalMs ?? 2000;

  let data = await getSessionSummary(settings, conversationId);
  opts?.onUpdate?.(data);

  if (data.status === "pending" || data.status === "running") {
    for (let i = 0; i < maxAttempts; i++) {
      await sleep(intervalMs);
      data = await getSessionSummary(settings, conversationId);
      opts?.onUpdate?.(data);
      if (data.status !== "pending" && data.status !== "running") break;
    }
  }

  return data;
}

/** Canonical export (Web UI parity): `GET /api/conversations/{id}/export`. По умолчанию tier=final (ТЗ §17.9). */
export async function fetchConversationExport(
  settings: ExtensionSettings,
  conversationId: string,
  format: "md" | "json",
  opts?: { tier?: TranscriptTier }
): Promise<string> {
  const tier = opts?.tier ?? "final";
  const base = settings.serverUrl.replace(/\/+$/, "");
  const params = new URLSearchParams({ format, tier });
  const url = `${base}/api/conversations/${encodeURIComponent(conversationId)}/export?${params}`;
  const res = await fetch(url, { headers: authHeaders(settings) });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`Экспорт не удался: ${res.status} ${t.slice(0, 200)}`);
  }
  return res.text();
}
