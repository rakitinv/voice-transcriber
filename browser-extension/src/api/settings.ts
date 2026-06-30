/** GET /api/settings/limits — поля, нужные расширению. */
export interface ServerLimits {
  llm_session_summary_enabled?: boolean;
}

export async function getServerLimits(
  serverUrl: string,
  accessToken: string
): Promise<ServerLimits> {
  const base = serverUrl.replace(/\/+$/, "");
  const res = await fetch(`${base}/api/settings/limits`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Не удалось загрузить лимиты: ${res.status} ${text}`.trim());
  }
  return (await res.json()) as ServerLimits;
}

export interface UserSettings {
  default_language: string;
  default_ttl_days: number;
  search_mode: "fulltext" | "semantic";
  asr_vad_use_custom?: boolean;
  asr_vad_filter?: boolean;
  asr_vad_min_silence_ms?: number;
  asr_vad_threshold?: number | null;
  asr_vad_speech_pad_ms?: number | null;
  diarization_turn_level_retranscription_use_custom?: boolean;
  diarization_turn_level_retranscription?: boolean;
}

export async function getUserSettings(
  serverUrl: string,
  accessToken: string
): Promise<UserSettings> {
  const base = serverUrl.replace(/\/+$/, "");
  const res = await fetch(`${base}/api/settings/user`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Не удалось загрузить настройки: ${res.status} ${text}`.trim());
  }
  return (await res.json()) as UserSettings;
}

