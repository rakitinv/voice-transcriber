/** Conversation list item (mapped for UI) */
export interface ConversationSummary {
  id: string;
  date: string;
  duration: number;
  language: string;
  /** Расширение исходного файла в хранилище (без точки), для имени при скачивании */
  audioObjectExt?: string;
}

/** Single conversation (viewer) */
export interface Conversation {
  id: string;
  date: string;
  duration: number;
  language: string;
  transcript: TranscriptSegment[];
  summary?: string;
  audioObjectExt?: string;
  /** When the current audio object was last uploaded (server). */
  audioUploadedAt?: string | null;
  /** Active transcript metadata */
  transcriptKind?: string | null;
  transcriptStatus?: string | null;
  transcriptRevision?: number | null;
  /** Начало фазы ASR (для diarized-транскрипта — по исходной строке `asr`). */
  transcriptCreatedAt?: string | null;
  /** Окончание успешной фазы ASR. */
  transcriptFinishedAt?: string | null;
  /** Успешное завершение диаризации (как раньше; дублирует конец при status=success). */
  diarizationPerformedAt?: string | null;
  /** Начало последней попытки диаризации. */
  diarizationStartedAt?: string | null;
  /** Завершение попытки диаризации (успех или ошибка). */
  diarizationFinishedAt?: string | null;
  diarizationStatus?: string | null;
  /** Last failed diarization error message from server, when status is "failed" */
  diarizationError?: string | null;
  /** Whether diarization.enabled is true in server config */
  diarizationEnabled?: boolean;
  /** Server hint: poll until ASR/diarization pipeline settles */
  refetchRecommended?: boolean;
  /** §7.6 rolling session summary status (null if feature disabled on server) */
  recordingSessionSummaryStatus?: string | null;
  recordingSessionSummaryUpdatedAt?: string | null;
}

export interface TranscriptSegment {
  speaker: string;
  start: number;
  end: number;
  text: string;
}

/** GET /api/conversations/{id}/session-summary (§7.6) */
export interface RecordingSessionSummaryDto {
  recording_session_id: string;
  status: string;
  summary_md: string | null;
  error: string | null;
  updated_at: string | null;
}

/** GET /api/search response */
export interface SearchResponseDto {
  results: SearchHit[];
  total: number;
  mode: string;
}

export interface SearchHit {
  conversation_id: string;
  conversation_title: string | null;
  transcript_id: number;
  text: string;
  start: number;
  end: number;
  speaker: string | null;
}

/** GET /api/settings/limits */
export interface ServerLimits {
  max_duration_seconds: number;
  max_file_size_bytes: number;
  max_ttl_days: number;
  allowed_realtime_modes: string[];
  default_realtime_mode: string;
  chunk_ms_min: number;
  chunk_ms_max: number;
  max_window_ms: number;
  autoprolong_enabled: boolean;
  autoprolong_tail_seconds: number;
  /** Текущие дефолты VAD из окружения API (подсказка для формы) */
  asr_vad_defaults?: {
    vad_filter: boolean;
    min_silence_ms: number;
    threshold: number | null;
    speech_pad_ms: number | null;
  };
  /** Серверный дефолт: повторный ASR на каждый turn при диаризации */
  diarization_turn_level_retranscription_default?: boolean;
  /** ТЗ §7.6 — включена ли генерация rolling-summary по цепочке */
  llm_session_summary_enabled?: boolean;
}

/** GET /api/settings/oauth-identities (C7.4) */
export interface OAuthIdentity {
  provider: string;
  provider_email: string | null;
  subject_hint: string;
}

/** GET/PATCH /api/settings/user */
export interface UserSettings {
  default_language: string;
  default_ttl_days: number;
  search_mode: "fulltext" | "semantic";
  asr_vad_use_custom: boolean;
  asr_vad_filter: boolean;
  asr_vad_min_silence_ms: number;
  asr_vad_threshold: number | null;
  asr_vad_speech_pad_ms: number | null;
  diarization_turn_level_retranscription_use_custom?: boolean;
  /** Эффективное значение (сервер + override) */
  diarization_turn_level_retranscription?: boolean;
}

export interface User {
  id: string;
  email?: string;
  name?: string;
  provider?: "google" | "yandex";
}
