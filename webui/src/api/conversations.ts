import { api } from "./client";
import { notifyAxiosDownloadError } from "../utils/downloadErrors";
import { notifyError, notifyInfo } from "../utils/notify";
import axios from "axios";

export interface UploadAcceptedResponse {
  conversation_id: string;
  audio_object_ext: string;
  status: string;
  message: string;
}

export type TranscriptTier = "auto" | "fast" | "final";
import type {
  Conversation,
  ConversationSummary,
  OAuthIdentity,
  RecordingSessionSummaryDto,
  SearchResponseDto,
  ServerLimits,
  UserSettings,
} from "../types";

/** Raw list item from API */
interface ConversationRow {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  recording_session_id: string;
  previous_conversation_id: string | null;
  client_realtime_mode: string | null;
  client_chunk_ms: number | null;
  /** Расширение исходного аудио в S3 (audio.<ext>) */
  audio_object_ext?: string;
  audio_uploaded_at?: string | null;
  duration_seconds?: number;
  language?: string;
}

interface ConversationListPayload {
  conversations: ConversationRow[];
  total: number;
}

function parseFilenameFromContentDisposition(cd: string | undefined): string | null {
  if (!cd) return null;
  const star = /filename\*=(?:UTF-8'')?([^;\n]+)/i.exec(cd);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replace(/['"]/g, ""));
    } catch {
      return null;
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(cd);
  if (quoted?.[1]) return quoted[1].trim();
  const plain = /filename=([^;\n]+)/i.exec(cd);
  if (plain?.[1]) return plain[1].trim().replace(/^["']|["']$/g, "");
  return null;
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function formatIsoForUi(value: string): string | null {
  const s = (value ?? "").trim();
  if (!s) return null;
  // Support both ISO with timezone and plain ISO (treated as UTC by Date in modern browsers).
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString();
}

/** ISO timestamps after Russian labels in export headers → local `toLocaleString()`. */
function rewriteLabeledIsoTimesInLine(line: string): string {
  return line.replace(
    /\b(начата:|завершена:|попытка завершена:)\s*(\S+)/g,
    (full, label: string, iso: string) => {
      const formatted = formatIsoForUi(iso);
      return formatted ? `${label} ${formatted}` : full;
    }
  );
}

function rewriteExportHeaderDates(md: string): string {
  // Server writes ISO timestamps; UI shows local `toLocaleString()`.
  // Rewrite only the header lines we control; leave the body untouched.
  const lines = md.split(/\r?\n/);
  for (let i = 0; i < Math.min(lines.length, 30); i++) {
    // - Uploaded at: 2026-...Z
    {
      const m = /^- Uploaded at:\s*(.+)\s*$/.exec(lines[i]);
      if (m?.[1]) {
        const formatted = formatIsoForUi(m[1]);
        if (formatted) lines[i] = `- Uploaded at: ${formatted}`;
      }
    }
    // - Создан разговор: ISO
    {
      const m = /^- Создан разговор:\s*(.+)\s*$/.exec(lines[i]);
      if (m?.[1]) {
        const formatted = formatIsoForUi(m[1]);
        if (formatted) lines[i] = `- Создан разговор: ${formatted}`;
      }
    }
    // - Аудио загружено: ISO | нет данных
    {
      const m = /^- Аудио загружено:\s*(.+)\s*$/.exec(lines[i]);
      if (m?.[1] && m[1].trim() !== "нет данных") {
        const formatted = formatIsoForUi(m[1]);
        if (formatted) lines[i] = `- Аудио загружено: ${formatted}`;
      }
    }
    // - Транскрибация / Диаризация: … начата: ISO … завершена: ISO (и старые варианты)
    {
      if (/^- Транскрибация:/.test(lines[i]) || /^- Диаризация:/.test(lines[i])) {
        lines[i] = rewriteLabeledIsoTimesInLine(lines[i]);
      }
    }
    // - Transcription: kind=..., revision=..., at=2026-...Z
    {
      const m = /^- Transcription:\s*(.*\bat=)([^,\s]+)\s*$/.exec(lines[i]);
      if (m?.[1] && m?.[2]) {
        const formatted = formatIsoForUi(m[2]);
        if (formatted) lines[i] = `- Transcription: ${m[1]}${formatted}`;
      }
    }
    // - Diarization: 2026-...Z  OR  - Diarization: не выполнялась
    {
      const m = /^- Diarization:\s*(.+)\s*$/.exec(lines[i]);
      if (m?.[1]) {
        const formatted = formatIsoForUi(m[1]);
        if (formatted) lines[i] = `- Diarization: ${formatted}`;
      }
    }
  }
  return lines.join("\n");
}

interface ConversationDetailPayload {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  recording_session_id: string;
  previous_conversation_id: string | null;
  client_realtime_mode: string | null;
  client_chunk_ms: number | null;
  audio_object_ext?: string;
  duration_seconds: number;
  language: string;
  transcript: Array<{
    speaker: string;
    start: number;
    end: number;
    text: string;
  }>;
  summary?: string | null;
  transcript_kind?: string | null;
  transcript_status?: string | null;
  transcript_revision?: number | null;
  transcript_created_at?: string | null;
  transcript_finished_at?: string | null;
  diarization_performed_at?: string | null;
  diarization_started_at?: string | null;
  diarization_finished_at?: string | null;
  diarization_status?: string | null;
  diarization_error?: string | null;
  diarization_enabled?: boolean;
  recording_session_summary_status?: string | null;
  recording_session_summary_updated_at?: string | null;
  audio_uploaded_at?: string | null;
  refetch_recommended?: boolean;
  /** Rare: if a proxy or serializer ever emits camelCase */
  refetchRecommended?: boolean;
}

export const conversationsApi = {
  list: () =>
    api.get<ConversationListPayload>("/conversations").then((r) => {
      const rows = r.data.conversations ?? [];
      return rows.map(
        (c): ConversationSummary => ({
          id: c.id,
          date: c.audio_uploaded_at ?? c.created_at,
          duration: typeof c.duration_seconds === "number" ? c.duration_seconds : 0,
          language: (c.language && c.language.trim()) || "—",
          audioObjectExt: c.audio_object_ext,
        })
      );
    }),

  get: (id: string, opts?: { tier?: TranscriptTier }) =>
    api
      .get<ConversationDetailPayload>(`/conversations/${id}`, {
        params: opts?.tier ? { tier: opts.tier } : undefined,
      })
      .then((r) => {
      const d = r.data;
      const refetchRaw: unknown = d.refetch_recommended ?? d.refetchRecommended;
      const refetchRecommended =
        refetchRaw === true || refetchRaw === "true" || refetchRaw === 1;
      const conv: Conversation = {
        id: d.id,
        date: d.created_at,
        duration: d.duration_seconds,
        language: d.language,
        transcript: d.transcript ?? [],
        summary: d.summary ?? undefined,
        audioObjectExt: d.audio_object_ext,
        audioUploadedAt: d.audio_uploaded_at ?? null,
        transcriptKind: d.transcript_kind ?? null,
        transcriptStatus: d.transcript_status ?? null,
        transcriptRevision: d.transcript_revision ?? null,
        transcriptCreatedAt: d.transcript_created_at ?? null,
        transcriptFinishedAt: d.transcript_finished_at ?? null,
        diarizationPerformedAt: d.diarization_performed_at ?? null,
        diarizationStartedAt: d.diarization_started_at ?? null,
        diarizationFinishedAt: d.diarization_finished_at ?? null,
        diarizationStatus: d.diarization_status ?? null,
        diarizationError: d.diarization_error ?? null,
        diarizationEnabled:
          typeof d.diarization_enabled === "boolean" ? d.diarization_enabled : undefined,
        refetchRecommended,
        recordingSessionSummaryStatus: d.recording_session_summary_status ?? null,
        recordingSessionSummaryUpdatedAt: d.recording_session_summary_updated_at ?? null,
      };
      return conv;
    }),

  delete: (id: string) => api.delete(`/conversations/${id}`).then((r) => r.data),

  /**
   * Пакетная загрузка аудио — тот же контракт, что `POST /api/upload` в CLI (`upload`).
   * Новый разговор создаётся на сервере, если не передан `conversationId`.
   */
  uploadAudio: (
    file: File,
    options?: { audioFormat?: string; conversationId?: string }
  ) => {
    const form = new FormData();
    form.append("file", file);
    const params: Record<string, string> = {};
    if (options?.audioFormat) {
      params.audio_format = options.audioFormat.replace(/^\./, "").toLowerCase();
    }
    if (options?.conversationId) {
      params.conversation_id = options.conversationId;
    }
    return api
      .post<UploadAcceptedResponse>("/upload", form, {
        params: Object.keys(params).length ? params : undefined,
      })
      .then((r) => r.data);
  },

  exportTranscript: async (
    id: string,
    format: "md" | "json",
    opts?: { tier?: TranscriptTier }
  ) => {
    try {
      const res = await api.get(`/conversations/${id}/export`, {
        params: { format, ...(opts?.tier ? { tier: opts.tier } : {}) },
        responseType: "blob",
      });
      const blob = res.data as Blob;
      const ext = format === "md" ? "md" : "json";
      if (format === "md") {
        const text = await blob.text();
        const rewritten = rewriteExportHeaderDates(text);
        const outBlob = new Blob([rewritten], {
          type: "text/markdown; charset=utf-8",
        });
        triggerBlobDownload(outBlob, `transcript-${id}.md`);
      } else {
        triggerBlobDownload(blob, `transcript-${id}.${ext}`);
      }
    } catch (err) {
      await notifyAxiosDownloadError(err, "Транскрипт на сервере не найден.");
    }
  },

  downloadOriginalAudio: async (id: string, fallbackExt = "webm") => {
    try {
      const res = await api.get(`/conversations/${id}/audio`, {
        responseType: "blob",
      });
      const hdr = res.headers as Record<string, string | undefined>;
      const cd = hdr["content-disposition"] ?? hdr["Content-Disposition"];
      const fromHeader = parseFilenameFromContentDisposition(cd);
      const filename = fromHeader ?? `recording-${id}.${fallbackExt}`;
      triggerBlobDownload(res.data as Blob, filename);
    } catch (err) {
      await notifyAxiosDownloadError(err, "Исходное аудио на сервере не найдено.");
    }
  },

  diarize: async (id: string) => {
    try {
      await api.post(`/conversations/${id}/diarize`);
      notifyInfo("Диаризация запущена.");
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        notifyInfo("Диаризация уже выполняется.");
        return;
      }
      if (axios.isAxiosError(err) && err.response?.status === 400) {
        const data = err.response?.data as { detail?: unknown } | undefined;
        const detail = data?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? detail.map((x) => (typeof x === "object" && x && "msg" in x ? String((x as { msg: string }).msg) : "")).filter(Boolean).join(" ")
              : "";
        notifyError(msg || "Не удалось запустить диаризацию.");
        return;
      }
      notifyError("Не удалось запустить диаризацию.");
      throw err;
    }
  },

  getSessionSummary: (id: string) =>
    api
      .get<RecordingSessionSummaryDto>(`/conversations/${id}/session-summary`)
      .then((r) => r.data),

  retrySessionSummary: async (id: string) => {
    await api.post(`/conversations/${id}/session-summary/retry`);
  },

  retranscribe: async (id: string) => {
    try {
      await api.post(`/conversations/${id}/retranscribe`);
      notifyInfo("Повторное распознавание поставлено в очередь.");
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        notifyInfo("Распознавание уже выполняется.");
        return;
      }
      if (axios.isAxiosError(err) && err.response?.status === 400) {
        notifyError("Нет загруженного аудио для этого разговора.");
        return;
      }
      notifyError("Не удалось запустить повторное распознавание.");
      throw err;
    }
  },
};

export const searchApi = {
  search: (q: string, semantic: boolean) =>
    api
      .get<SearchResponseDto>("/search", {
        params: { q, mode: semantic ? "semantic" : "fulltext" },
      })
      .then((r) => r.data),
};

export const settingsApi = {
  getLimits: () => api.get<ServerLimits>("/settings/limits").then((r) => r.data),

  getUserSettings: () =>
    api.get<UserSettings>("/settings/user").then((r) => r.data),

  updateUserSettings: (settings: Partial<UserSettings>) =>
    api.patch<UserSettings>("/settings/user", settings).then((r) => r.data),

  listOAuthIdentities: () =>
    api.get<OAuthIdentity[]>("/settings/oauth-identities").then((r) => r.data),

  getOAuthLinkAuthUrl: (provider: "google" | "yandex") =>
    api.get<{ auth_url: string }>(`/auth/${provider}/link/start`).then((r) => r.data.auth_url),
};
