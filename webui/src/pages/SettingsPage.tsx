import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  useSettingsLimits,
  useUserSettings,
  useUpdateUserSettings,
  useOAuthIdentities,
  SETTINGS_OAUTH_IDENTITIES_KEY,
} from "../hooks/useConversations";
import { settingsApi } from "../api/conversations";
import { Button } from "../components/Button";
import type { UserSettings } from "../types";
import { LANGUAGE_OPTIONS, normalizeLanguageCode } from "../utils/languages";
import { notifyError, notifyInfo } from "../utils/notify";
import styles from "./SettingsPage.module.css";

const LINK_FAIL_MESSAGES: Record<string, string> = {
  provider_already_linked_elsewhere:
    "This provider account is already linked to another Voice Transcriber user.",
  provider_email_conflict:
    "That provider email is already used by another account.",
  provider_denied: "Provider login was cancelled or denied.",
  missing_code: "OAuth response incomplete. Try linking again.",
  invalid_state: "Link session expired or is invalid. Try again.",
  state_mismatch: "OAuth state did not match. Try again.",
  token_exchange: "Could not complete token exchange with the provider.",
  user_not_found: "Your session no longer matches the server. Sign in again.",
  unknown: "Could not link provider.",
};

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { data: limits, isLoading: limitsLoading } = useSettingsLimits();
  const { data: userSettings, isLoading: userLoading } = useUserSettings();
  const { data: oauthIdentities, isLoading: oauthIdLoading } = useOAuthIdentities();
  const updateSettings = useUpdateUserSettings();
  const [vadCustom, setVadCustom] = useState(false);
  const [diarRetrCustom, setDiarRetrCustom] = useState(false);
  const [linkBusy, setLinkBusy] = useState<null | "google" | "yandex">(null);

  useEffect(() => {
    const link = searchParams.get("oauth_link");
    if (!link) return;
    const provider = searchParams.get("provider");
    if (link === "success") {
      notifyInfo(provider ? `Linked ${provider} to your account.` : "Provider linked.");
      void queryClient.invalidateQueries({ queryKey: SETTINGS_OAUTH_IDENTITIES_KEY });
    } else if (link === "error") {
      const reason = searchParams.get("reason") ?? "unknown";
      notifyError(LINK_FAIL_MESSAGES[reason] ?? `Link failed (${reason}).`);
    }
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams, queryClient]);

  useEffect(() => {
    if (userSettings) {
      setVadCustom(userSettings.asr_vad_use_custom);
      setDiarRetrCustom(!!userSettings.diarization_turn_level_retranscription_use_custom);
    }
  }, [userSettings]);

  const handleSave = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const defaultLanguage = (form.elements.namedItem("defaultLanguage") as HTMLSelectElement)?.value;
    const defaultTtl = Number((form.elements.namedItem("defaultTtl") as HTMLInputElement)?.value);
    const searchMode = (form.elements.namedItem("searchMode") as HTMLSelectElement)?.value as UserSettings["search_mode"];
    const asrUseCustom = (form.elements.namedItem("asrVadUseCustom") as HTMLInputElement)?.checked ?? false;
    const diarRetrUseCustom =
      (form.elements.namedItem("diarTurnRetrUseCustom") as HTMLInputElement)?.checked ?? false;
    const payload: Partial<UserSettings> = {
      default_language: normalizeLanguageCode(defaultLanguage) || userSettings?.default_language,
      default_ttl_days: Number.isFinite(defaultTtl) ? defaultTtl : userSettings?.default_ttl_days,
      search_mode: searchMode ?? userSettings?.search_mode,
      asr_vad_use_custom: asrUseCustom,
      diarization_turn_level_retranscription_use_custom: diarRetrUseCustom,
    };
    if (asrUseCustom) {
      const vadFilter = (form.elements.namedItem("asrVadFilter") as HTMLInputElement)?.checked ?? true;
      const minSil = Number((form.elements.namedItem("asrVadMinSilenceMs") as HTMLInputElement)?.value);
      const thrRaw = (form.elements.namedItem("asrVadThreshold") as HTMLInputElement)?.value?.trim() ?? "";
      const padRaw = (form.elements.namedItem("asrVadSpeechPadMs") as HTMLInputElement)?.value?.trim() ?? "";
      payload.asr_vad_filter = vadFilter;
      payload.asr_vad_min_silence_ms = Number.isFinite(minSil) ? minSil : userSettings?.asr_vad_min_silence_ms;
      const thrNum = thrRaw === "" ? null : Number(thrRaw);
      const padNum = padRaw === "" ? null : Number(padRaw);
      payload.asr_vad_threshold = thrRaw === "" || Number.isFinite(thrNum) ? thrNum : userSettings?.asr_vad_threshold;
      payload.asr_vad_speech_pad_ms =
        padRaw === "" || Number.isFinite(padNum) ? padNum : userSettings?.asr_vad_speech_pad_ms;
    }
    if (diarRetrUseCustom) {
      payload.diarization_turn_level_retranscription = (
        form.elements.namedItem("diarTurnRetr") as HTMLInputElement
      )?.checked;
    }
    updateSettings.mutate(payload);
  };

  const maxTtl = limits?.max_ttl_days ?? 30;
  const vadDefaults = limits?.asr_vad_defaults;

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Settings</h1>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Server limits</h2>
        {limitsLoading && <p className={styles.muted}>Loading…</p>}
        {!limitsLoading && limits && (
          <dl className={styles.dl}>
            <dt>Max duration</dt>
            <dd>{limits.max_duration_seconds} s</dd>
            <dt>Max TTL</dt>
            <dd>{limits.max_ttl_days} days</dd>
            <dt>Max file size</dt>
            <dd>{limits.max_file_size_bytes} bytes</dd>
            <dt>Realtime modes</dt>
            <dd>{limits.allowed_realtime_modes.join(", ")}</dd>
            <dt>Chunk size (ms)</dt>
            <dd>
              {limits.chunk_ms_min} – {limits.chunk_ms_max}
            </dd>
            {vadDefaults && (
              <>
                <dt>ASR VAD (server defaults)</dt>
                <dd>
                  {vadDefaults.vad_filter ? "on" : "off"}, min silence {vadDefaults.min_silence_ms} ms
                  {vadDefaults.threshold != null ? `, threshold ${vadDefaults.threshold}` : ""}
                  {vadDefaults.speech_pad_ms != null ? `, pad ${vadDefaults.speech_pad_ms} ms` : ""}
                </dd>
              </>
            )}
            <dt>Diarization re-ASR per turn (server default)</dt>
            <dd>{limits.diarization_turn_level_retranscription_default ? "on" : "off"}</dd>
            <dt>LLM session summary (§7.6)</dt>
            <dd>{limits.llm_session_summary_enabled ? "enabled" : "off"}</dd>
          </dl>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Connected accounts</h2>
        <p className={styles.muted}>
          Link Google or Yandex so sign-in with either provider opens the same account. Register the link callback URLs
          in your OAuth apps (see API docs).
        </p>
        {oauthIdLoading && <p className={styles.muted}>Loading linked providers…</p>}
        {!oauthIdLoading && oauthIdentities && oauthIdentities.length > 0 && (
          <ul className={styles.identityList}>
            {oauthIdentities.map((row) => (
              <li key={`${row.provider}-${row.subject_hint}`}>
                <strong>{row.provider}</strong>
                {row.provider_email ? ` — ${row.provider_email}` : ""}{" "}
                <span className={styles.muted}>(id {row.subject_hint})</span>
              </li>
            ))}
          </ul>
        )}
        {!oauthIdLoading && oauthIdentities && oauthIdentities.length === 0 && (
          <p className={styles.muted}>No extra providers linked yet.</p>
        )}
        <div className={styles.linkActions}>
          <Button
            type="button"
            variant="secondary"
            disabled={linkBusy !== null}
            onClick={() => {
              setLinkBusy("google");
              void settingsApi
                .getOAuthLinkAuthUrl("google")
                .then((url) => {
                  window.location.href = url;
                })
                .catch(() => {
                  setLinkBusy(null);
                  notifyError("Could not start Google link.");
                });
            }}
          >
            {linkBusy === "google" ? "Redirecting…" : "Link Google"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={linkBusy !== null}
            onClick={() => {
              setLinkBusy("yandex");
              void settingsApi
                .getOAuthLinkAuthUrl("yandex")
                .then((url) => {
                  window.location.href = url;
                })
                .catch(() => {
                  setLinkBusy(null);
                  notifyError("Could not start Yandex link.");
                });
            }}
          >
            {linkBusy === "yandex" ? "Redirecting…" : "Link Yandex"}
          </Button>
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>User settings</h2>
        {userLoading && <p className={styles.muted}>Loading…</p>}
        {!userLoading && userSettings && (
          <form onSubmit={handleSave} className={styles.form}>
            <label className={styles.label}>
              Default language
              <select
                name="defaultLanguage"
                defaultValue={normalizeLanguageCode(userSettings.default_language)}
                className={styles.select}
              >
                {LANGUAGE_OPTIONS.map((o) => (
                  <option key={o.code} value={o.code}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.label}>
              Default TTL (days)
              <input
                name="defaultTtl"
                type="number"
                min={1}
                max={maxTtl}
                defaultValue={Math.min(userSettings.default_ttl_days, maxTtl)}
                className={styles.input}
              />
            </label>
            <label className={styles.label}>
              Search mode
              <select
                name="searchMode"
                defaultValue={userSettings.search_mode}
                className={styles.select}
              >
                <option value="fulltext">Full-text</option>
                <option value="semantic">Semantic</option>
              </select>
            </label>

            <div className={styles.checkboxRow}>
              <input
                type="checkbox"
                id="asrVadUseCustom"
                name="asrVadUseCustom"
                checked={vadCustom}
                onChange={(ev) => setVadCustom(ev.target.checked)}
              />
              <label htmlFor="asrVadUseCustom">Custom ASR VAD (faster-whisper)</label>
            </div>
            <p className={styles.muted}>
              When off, the server uses only environment variables (for example from Docker). When on, your values
              apply to uploads, realtime, and diarization re-transcription for your account.
            </p>

            <div className={styles.checkboxRow}>
              <input
                type="checkbox"
                id="diarTurnRetrUseCustom"
                name="diarTurnRetrUseCustom"
                checked={diarRetrCustom}
                onChange={(ev) => setDiarRetrCustom(ev.target.checked)}
              />
              <label htmlFor="diarTurnRetrUseCustom">Custom diarization — re-ASR each speaker turn</label>
            </div>
            <p className={styles.muted}>
              When off, the server default above applies. When on, your choice applies to diarization jobs for your
              account: re-run ASR on short clips per pyannote turn (can change wording), or only assign speakers to
              the existing full-file transcript.
            </p>
            <div className={styles.checkboxRow}>
              <input
                type="checkbox"
                id="diarTurnRetr"
                name="diarTurnRetr"
                defaultChecked={!!userSettings.diarization_turn_level_retranscription}
                disabled={!diarRetrCustom}
              />
              <label htmlFor="diarTurnRetr">Re-ASR on each diarization turn (not speaker labeling only)</label>
            </div>

            <div className={styles.checkboxRow}>
              <input
                type="checkbox"
                id="asrVadFilter"
                name="asrVadFilter"
                defaultChecked={userSettings.asr_vad_filter}
                disabled={!vadCustom}
              />
              <label htmlFor="asrVadFilter">VAD filter enabled</label>
            </div>
            <label className={styles.label}>
              Min silence (ms)
              <input
                name="asrVadMinSilenceMs"
                type="number"
                min={50}
                max={5000}
                step={10}
                defaultValue={userSettings.asr_vad_min_silence_ms}
                disabled={!vadCustom}
                className={styles.input}
              />
            </label>
            <label className={styles.label}>
              VAD threshold (0–1, empty = model default)
              <input
                name="asrVadThreshold"
                type="number"
                min={0}
                max={1}
                step={0.01}
                defaultValue={
                  userSettings.asr_vad_threshold === null || userSettings.asr_vad_threshold === undefined
                    ? ""
                    : String(userSettings.asr_vad_threshold)
                }
                disabled={!vadCustom}
                className={styles.input}
              />
            </label>
            <label className={styles.label}>
              Speech pad (ms, empty = model default)
              <input
                name="asrVadSpeechPadMs"
                type="number"
                min={0}
                max={5000}
                step={10}
                defaultValue={
                  userSettings.asr_vad_speech_pad_ms === null || userSettings.asr_vad_speech_pad_ms === undefined
                    ? ""
                    : String(userSettings.asr_vad_speech_pad_ms)
                }
                disabled={!vadCustom}
                className={styles.input}
              />
            </label>

            <Button type="submit" variant="primary" disabled={updateSettings.isPending}>
              {updateSettings.isPending ? "Saving…" : "Save"}
            </Button>
          </form>
        )}
      </section>
    </div>
  );
}
