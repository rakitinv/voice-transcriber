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
  };
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
