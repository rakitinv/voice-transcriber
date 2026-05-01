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
    "Этот аккаунт провайдера уже привязан к другому пользователю Voice transcriber.",
  provider_email_conflict:
    "Этот адрес провайдера уже используется другой учётной записью.",
  provider_denied: "Вход у провайдера отменён или запрещён.",
  missing_code: "Ответ OAuth неполный. Попробуйте привязать снова.",
  invalid_state: "Сессия привязки истекла или недействительна. Повторите попытку.",
  state_mismatch: "OAuth state не совпал. Повторите попытку.",
  token_exchange: "Не удалось обменять код у провайдера.",
  user_not_found: "Сессия не совпадает с сервером. Войдите снова.",
  unknown: "Не удалось привязать провайдера.",
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
      notifyInfo(provider ? `Провайдер ${provider} привязан к учётной записи.` : "Провайдер привязан.");
      void queryClient.invalidateQueries({ queryKey: SETTINGS_OAUTH_IDENTITIES_KEY });
    } else if (link === "error") {
      const reason = searchParams.get("reason") ?? "unknown";
      notifyError(LINK_FAIL_MESSAGES[reason] ?? `Привязка не удалась (${reason}).`);
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
      <h1 className={styles.title}>Настройки</h1>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Ограничения сервера</h2>
        {limitsLoading && <p className={styles.muted}>Загрузка…</p>}
        {!limitsLoading && limits && (
          <dl className={styles.dl}>
            <dt>Макс. длительность</dt>
            <dd>{limits.max_duration_seconds} с</dd>
            <dt>Макс. TTL</dt>
            <dd>{limits.max_ttl_days} дн.</dd>
            <dt>Макс. размер файла</dt>
            <dd>{limits.max_file_size_bytes} байт</dd>
            <dt>Режимы realtime</dt>
            <dd>{limits.allowed_realtime_modes.join(", ")}</dd>
            <dt>Размер фрагмента (мс)</dt>
            <dd>
              {limits.chunk_ms_min} – {limits.chunk_ms_max}
            </dd>
            {vadDefaults && (
              <>
                <dt>ASR VAD (значения сервера по умолчанию)</dt>
                <dd>
                  {vadDefaults.vad_filter ? "вкл." : "выкл."}, мин. тишина {vadDefaults.min_silence_ms} мс
                  {vadDefaults.threshold != null ? `, порог ${vadDefaults.threshold}` : ""}
                  {vadDefaults.speech_pad_ms != null ? `, отступ ${vadDefaults.speech_pad_ms} мс` : ""}
                </dd>
              </>
            )}
            <dt>Повторное ASR по репликам при диаризации (по умолчанию на сервере)</dt>
            <dd>{limits.diarization_turn_level_retranscription_default ? "вкл." : "выкл."}</dd>
            <dt>Сводка сессии LLM</dt>
            <dd>{limits.llm_session_summary_enabled ? "включено" : "выкл."}</dd>
          </dl>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Подключённые аккаунты</h2>
        <p className={styles.muted}>
          Привяжите Google или Яндекс — вход через любой из них откроет одну и ту же учётную запись. Зарегистрируйте URL
          обратного вызова привязки в настройках OAuth-приложений (см. документацию API).
        </p>
        {oauthIdLoading && <p className={styles.muted}>Загрузка привязанных провайдеров…</p>}
        {!oauthIdLoading && oauthIdentities && oauthIdentities.length > 0 && (
          <ul className={styles.identityList}>
            {oauthIdentities.map((row) => (
              <li key={`${row.provider}-${row.subject_hint}`}>
                <strong>{row.provider}</strong>
                {row.provider_email ? ` — ${row.provider_email}` : ""}{" "}
                <span className={styles.muted}>(ид. {row.subject_hint})</span>
              </li>
            ))}
          </ul>
        )}
        {!oauthIdLoading && oauthIdentities && oauthIdentities.length === 0 && (
          <p className={styles.muted}>Дополнительные провайдеры ещё не привязаны.</p>
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
                  notifyError("Не удалось начать привязку Google.");
                });
            }}
          >
            {linkBusy === "google" ? "Переадресация…" : "Привязать Google"}
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
                  notifyError("Не удалось начать привязку Яндекса.");
                });
            }}
          >
            {linkBusy === "yandex" ? "Переадресация…" : "Привязать Яндекс"}
          </Button>
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Пользовательские настройки</h2>
        {userLoading && <p className={styles.muted}>Загрузка…</p>}
        {!userLoading && userSettings && (
          <form onSubmit={handleSave} className={styles.form}>
            <label className={styles.label}>
              Язык по умолчанию
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
              TTL по умолчанию (дней)
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
              Режим поиска
              <select
                name="searchMode"
                defaultValue={userSettings.search_mode}
                className={styles.select}
              >
                <option value="fulltext">Полнотекстовый</option>
                <option value="semantic">Семантический</option>
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
              <label htmlFor="asrVadUseCustom">Свои параметры ASR VAD (faster-whisper)</label>
            </div>
            <p className={styles.muted}>
              Если выключено, сервер берёт только переменные окружения (например из Docker). Если включено, ваши значения
              применяются к загрузкам, realtime и повторному распознаванию при диаризации для вашей учётной записи.
            </p>

            <div className={styles.checkboxRow}>
              <input
                type="checkbox"
                id="diarTurnRetrUseCustom"
                name="diarTurnRetrUseCustom"
                checked={diarRetrCustom}
                onChange={(ev) => setDiarRetrCustom(ev.target.checked)}
              />
              <label htmlFor="diarTurnRetrUseCustom">Свои параметры диаризации — повторное ASR для каждой реплики</label>
            </div>
            <p className={styles.muted}>
              Если выключено, действует значение сервера выше. Если включено, ваш выбор применяется к задачам диаризации:
              снова запускать ASR на коротких фрагментах по репликам pyannote (может изменить формулировки) или только
              назначать говорящих для уже готовой расшифровки всего файла.
            </p>
            <div className={styles.checkboxRow}>
              <input
                type="checkbox"
                id="diarTurnRetr"
                name="diarTurnRetr"
                defaultChecked={!!userSettings.diarization_turn_level_retranscription}
                disabled={!diarRetrCustom}
              />
              <label htmlFor="diarTurnRetr">
                Повторное ASR для каждой реплики при диаризации (не только метки говорящих)
              </label>
            </div>

            <div className={styles.checkboxRow}>
              <input
                type="checkbox"
                id="asrVadFilter"
                name="asrVadFilter"
                defaultChecked={userSettings.asr_vad_filter}
                disabled={!vadCustom}
              />
              <label htmlFor="asrVadFilter">Фильтр VAD включён</label>
            </div>
            <label className={styles.label}>
              Мин. тишина (мс)
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
              Порог VAD (0–1, пусто = по умолчанию у модели)
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
              Отступ речи (мс, пусто = по умолчанию у модели)
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
              {updateSettings.isPending ? "Сохранение…" : "Сохранить"}
            </Button>
          </form>
        )}
      </section>
    </div>
  );
}
