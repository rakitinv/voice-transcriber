import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  useConversationTier,
  CONVERSATION_QUERY_KEY,
  useSettingsLimits,
} from "../hooks/useConversations";
import { TranscriptViewer } from "../components/TranscriptViewer";
import { Button } from "../components/Button";
import { RecordingDownloadIconButton } from "../components/RecordingDownloadIconButton";
import { conversationsApi } from "../api/conversations";
import { useQueryClient } from "@tanstack/react-query";
import { LANGUAGE_OPTIONS } from "../utils/languages";
import { notifyError, notifyInfo } from "../utils/notify";
import type { RecordingSessionSummaryDto } from "../types";
import styles from "./ConversationViewerPage.module.css";

function languageLabelForDisplay(code: string): string {
  const o = LANGUAGE_OPTIONS.find((x) => x.code === code);
  return o?.label ?? code;
}

function fmtDt(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("ru-RU");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/** Пока batch ASR заполняет расшифровку (или строка транскрипта ещё не видна в GET). */
function isTranscriptProcessing(
  tier: "fast" | "final",
  c: {
  transcript: { length: number };
  transcriptStatus?: string | null;
  refetchRecommended?: boolean;
  audioUploadedAt?: string | null;
}): boolean {
  const st = c.transcriptStatus ?? null;
  const empty = !c.transcript?.length;
  // Fast ветка может отсутствовать (например, разговор создан через upload, не realtime).
  // В этом случае не показываем «в обработке».
  if (tier === "fast" && empty && st == null) return false;
  if (st && ["pending", "running"].includes(st)) return true;
  if (st === "failed") return false;
  if (c.refetchRecommended && empty) return true;
  if (empty && c.audioUploadedAt && st !== "success" && st !== "failed") return true;
  return false;
}

export function ConversationViewerPage() {
  const { id } = useParams<{ id: string }>();
  const [tier, setTier] = useState<"fast" | "final">("final");
  const { data: conversation, isLoading, isError, error } = useConversationTier(id, tier);
  const qc = useQueryClient();
  const { data: limits } = useSettingsLimits();
  const sessionSummaryFeatureOn = limits?.llm_session_summary_enabled === true;
  const [rollingSummary, setRollingSummary] = useState<RecordingSessionSummaryDto | null>(null);
  const [rollingSummaryLoading, setRollingSummaryLoading] = useState(false);

  useEffect(() => {
    setRollingSummary(null);
  }, [id]);

  useEffect(() => {
    if (!id || !sessionSummaryFeatureOn || !conversation) return;
    if (conversation.recordingSessionSummaryStatus !== "success") return;
    let cancelled = false;
    void conversationsApi.getSessionSummary(id).then(
      (data) => {
        if (!cancelled) setRollingSummary(data);
      },
      () => {
        /* retry via button */
      }
    );
    return () => {
      cancelled = true;
    };
  }, [id, sessionSummaryFeatureOn, conversation?.recordingSessionSummaryStatus]);

  const handleDownload = () => {
    if (!id) return;
    void conversationsApi.exportTranscript(id, "md", { tier });
  };

  if (isLoading) return <p className={styles.status}>Загрузка…</p>;
  if (isError) {
    return (
      <p className={styles.error}>
        {error instanceof Error ? error.message : "Не удалось загрузить разговор."}
      </p>
    );
  }
  if (!conversation) return null;

  const transcriptProcessing = isTranscriptProcessing(tier, conversation);
  const asrBusy =
    transcriptProcessing || conversation.transcriptStatus === "running";
  const hasTranscriptContent = (conversation.transcript?.length ?? 0) > 0;
  /** Нет fast-ветки (upload и т.п.): API отдаёт пустые transcript_* для tier=fast */
  const fastTranscriptAbsent =
    tier === "fast" &&
    !transcriptProcessing &&
    conversation.transcriptKind == null &&
    conversation.transcriptRevision == null &&
    conversation.transcriptStatus == null;
  const diarizationBusy = ["pending", "running"].includes(
    conversation.diarizationStatus ?? ""
  );
  const canRetranscribe = !!conversation.audioUploadedAt && !asrBusy;
  const diarizationAllowed = conversation.diarizationEnabled !== false;
  const canDiarizeAgain = !asrBusy && !diarizationBusy && diarizationAllowed;

  const diarSt = conversation.diarizationStatus ?? null;
  const diarStart = conversation.diarizationStartedAt ?? null;
  const diarEnd = conversation.diarizationFinishedAt ?? null;

  let diarizationLabel: string;
  if (!diarizationAllowed) {
    diarizationLabel = "не используется (отключена на сервере)";
  } else if (diarSt === "success" && diarStart && diarEnd) {
    diarizationLabel = `начата: ${fmtDt(diarStart)} · завершена: ${fmtDt(diarEnd)}`;
  } else if (diarSt === "failed" && diarStart && diarEnd) {
    diarizationLabel = `начата: ${fmtDt(diarStart)} · завершена: ${fmtDt(diarEnd)} · ошибка`;
  } else if ((diarSt === "pending" || diarSt === "running") && diarStart) {
    diarizationLabel = `начата: ${fmtDt(diarStart)} · в процессе`;
  } else if (
    conversation.transcriptStatus &&
    ["pending", "running"].includes(conversation.transcriptStatus)
  ) {
    diarizationLabel = "ожидается готовый транскрипт";
  } else if (
    conversation.refetchRecommended &&
    conversation.transcriptKind === "asr" &&
    conversation.transcriptStatus === "success"
  ) {
    diarizationLabel = "выполняется…";
  } else {
    diarizationLabel = "не выполнялась";
    if (diarSt === "failed") {
      diarizationLabel += " · ошибка";
    }
  }
  const diarizationErrSuffix =
    conversation.diarizationStatus === "failed" && conversation.diarizationError
      ? `: ${conversation.diarizationError}`
      : "";

  const sessionSummaryDisplayStatus =
    rollingSummary?.status ?? conversation.recordingSessionSummaryStatus ?? "—";
  const sessionSummaryDisplayUpdatedAt =
    rollingSummary?.updated_at ?? conversation.recordingSessionSummaryUpdatedAt ?? null;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <Link to="/" className={styles.back}>← Разговоры</Link>
        <div className={styles.actions}>
          <RecordingDownloadIconButton
            onClick={() => {
              if (!id) return;
              void conversationsApi.downloadOriginalAudio(
                id,
                conversation.audioObjectExt ?? "webm"
              );
            }}
          />
          <Button
            variant="secondary"
            onClick={handleDownload}
            disabled={!hasTranscriptContent}
            title={
              !hasTranscriptContent ? "Нет готовой расшифровки для скачивания" : undefined
            }
          >
            Скачать расшифровку
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              if (!id) return;
              const ok = window.confirm(
                "Запустить повторное распознавание по уже загруженному аудио?\n\nБудет создана новая версия транскрипта (ASR). После успеха она станет активной; при включённой диаризации может поставиться в очередь и диаризация."
              );
              if (!ok) return;
              void conversationsApi.retranscribe(id).finally(() => {
                void qc.invalidateQueries({ queryKey: CONVERSATION_QUERY_KEY(id, tier) });
                window.setTimeout(() => {
                  void qc.invalidateQueries({ queryKey: CONVERSATION_QUERY_KEY(id, tier) });
                }, 2000);
              });
            }}
            disabled={!canRetranscribe}
            title={
              !conversation.audioUploadedAt
                ? "Нет загруженного аудио"
                : asrBusy
                  ? conversation.transcriptStatus === "running" ||
                    conversation.transcriptStatus === "pending"
                    ? "Распознавание уже выполняется"
                    : "Дождитесь завершения текущего этапа"
                  : undefined
            }
          >
            Распознать снова
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              if (!id) return;
              if (!canDiarizeAgain) return;
              const ok = window.confirm(
                "Запустить диаризацию заново?\n\nБудет создана новая версия расшифровки и она станет активной после завершения. Предыдущие версии сохранятся."
              );
              if (!ok) return;
              void conversationsApi.diarize(id).finally(() => {
                void qc.invalidateQueries({ queryKey: CONVERSATION_QUERY_KEY(id, tier) });
                window.setTimeout(() => {
                  void qc.invalidateQueries({ queryKey: CONVERSATION_QUERY_KEY(id, tier) });
                }, 2000);
              });
            }}
            disabled={!canDiarizeAgain}
            title={
              !diarizationAllowed
                ? "Диаризация отключена в конфигурации сервера"
                : asrBusy
                  ? "Дождитесь завершения распознавания"
                  : diarizationBusy
                    ? "Диаризация уже выполняется"
                    : undefined
            }
          >
            {diarizationBusy ? "Диаризация…" : "Диаризация снова"}
          </Button>
          <Button
            variant="secondary"
            disabled={
              !sessionSummaryFeatureOn || rollingSummaryLoading || !id
            }
            title={
              !sessionSummaryFeatureOn
                ? "Отключено на сервере (llm.session_summary_enabled). См. Настройки → Ограничения сервера."
                : "Загрузить или обновить скользящую сводку сессии записи в Markdown на сервере. Формируется после конвейера расшифровки (ASR, затем диаризация при включении)."
            }
            onClick={async () => {
              if (!id || !sessionSummaryFeatureOn) return;
              setRollingSummaryLoading(true);
              try {
                let data = await conversationsApi.getSessionSummary(id);
                if (data.status === "failed") {
                  try {
                    await conversationsApi.retrySessionSummary(id);
                    notifyInfo(
                      "Пересчёт сводки поставлен в очередь. Подождите несколько секунд…"
                    );
                  } catch {
                    notifyError(
                      "Не удалось поставить сводку в очередь (LLM недоступен или отключён)."
                    );
                    setRollingSummary(data);
                    return;
                  }
                  for (let i = 0; i < 90; i++) {
                    await sleep(2000);
                    data = await conversationsApi.getSessionSummary(id);
                    setRollingSummary(data);
                    if (data.status === "success" || data.status === "failed") {
                      break;
                    }
                  }
                } else {
                  setRollingSummary(data);
                  if (data.status === "pending" || data.status === "running") {
                    for (let i = 0; i < 90; i++) {
                      await sleep(2000);
                      data = await conversationsApi.getSessionSummary(id);
                      setRollingSummary(data);
                      if (data.status !== "pending" && data.status !== "running") {
                        break;
                      }
                    }
                  }
                }
                void qc.invalidateQueries({
                  queryKey: CONVERSATION_QUERY_KEY(id, tier),
                });
              } catch {
                notifyError("Не удалось загрузить сводку сессии.");
              } finally {
                setRollingSummaryLoading(false);
              }
            }}
          >
            {rollingSummaryLoading ? "Загрузка…" : "Сводка сессии"}
          </Button>
        </div>
      </div>
      <div className={styles.meta}>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Создан разговор</span>
          <span className={styles.metaValue}>{fmtDt(conversation.date)}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Аудио загружено</span>
          <span className={styles.metaValue}>{fmtDt(conversation.audioUploadedAt)}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Параметры аудио</span>
          <span className={styles.metaValue}>
            файл <code>audio.{conversation.audioObjectExt ?? "webm"}</code>
            {", "}
            длительность по расшифровке{" "}
            {transcriptProcessing && conversation.duration <= 0 ? (
              <>уточняется после распознавания</>
            ) : (
              <>~{conversation.duration.toFixed(1)} с</>
            )}
            , язык: {languageLabelForDisplay(conversation.language)}
          </span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Транскрибация</span>
          <span className={styles.metaValue}>
            {"["}
            <button
              type="button"
              className={styles.back}
              onClick={() => setTier("fast")}
              style={{
                fontWeight: tier === "fast" ? 700 : 400,
                opacity: tier === "fast" ? 1 : 0.75,
              }}
              title="Показать быстрый (realtime) вариант, если есть"
            >
              Быстрый
            </button>
            {" / "}
            <button
              type="button"
              className={styles.back}
              onClick={() => setTier("final")}
              style={{
                fontWeight: tier === "final" ? 700 : 400,
                opacity: tier === "final" ? 1 : 0.75,
              }}
              title="Показать финальный вариант (как для загрузки файла)"
            >
              Финальный
            </button>
            {"] "}
            {transcriptProcessing ? (
              <span className={styles.processingInline}>в обработке</span>
            ) : fastTranscriptAbsent ? (
              <>Не производилась</>
            ) : (
              <>
                {conversation.transcriptKind ?? "—"} / рев.{" "}
                {conversation.transcriptRevision ?? "—"} / {conversation.transcriptStatus ?? "—"}
                {conversation.transcriptCreatedAt ? (
                  <>
                    {" · начата: "}
                    {fmtDt(conversation.transcriptCreatedAt)}
                  </>
                ) : null}
                {conversation.transcriptFinishedAt ? (
                  <>
                    {" · завершена: "}
                    {fmtDt(conversation.transcriptFinishedAt)}
                  </>
                ) : conversation.transcriptStatus &&
                  ["pending", "running"].includes(conversation.transcriptStatus) ? (
                  <> · в процессе</>
                ) : null}
              </>
            )}
          </span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Диаризация</span>
          <span className={styles.metaValue}>
            {diarizationLabel}
            {diarizationErrSuffix}
          </span>
        </div>
      </div>
      {conversation.summary && (
        <div className={styles.summary}>
          <h3>Краткая сводка</h3>
          <p>{conversation.summary}</p>
        </div>
      )}
      {sessionSummaryFeatureOn && (
        <div className={styles.summary}>
          <h3>Скользящая сводка (сессия записи)</h3>
          <p className={styles.sessionSummaryMeta}>
            Статус на сервере:{" "}
            <strong>{sessionSummaryDisplayStatus}</strong>
            {sessionSummaryDisplayUpdatedAt
              ? ` · ${fmtDt(sessionSummaryDisplayUpdatedAt)}`
              : null}
          </p>
          {(sessionSummaryDisplayStatus === "pending" ||
            sessionSummaryDisplayStatus === "running") && (
            <p className={styles.summaryHint}>
              Сводка создаётся асинхронно после готовности расшифровки (и после диаризации, если она
              включена). Эта строка обновляется автоматически, пока статус «ожидание» или «выполняется».
            </p>
          )}
          {rollingSummary?.status === "failed" && rollingSummary.error ? (
            <p className={styles.error}>{rollingSummary.error}</p>
          ) : null}
          {rollingSummary?.summary_md ? (
            <pre className={styles.sessionSummaryBody}>{rollingSummary.summary_md}</pre>
          ) : rollingSummary?.status === "success" && !rollingSummary.summary_md ? (
            <p className={styles.summaryHint}>Текст сводки пуст.</p>
          ) : null}
        </div>
      )}
      {transcriptProcessing ? (
        <div className={styles.processingBanner} role="status">
          Расшифровка в обработке… Обычно это занимает от нескольких секунд до нескольких минут (зависит от
          длины файла и загрузки сервера). Страница обновится автоматически.
        </div>
      ) : null}
      <TranscriptViewer
        segments={conversation.transcript}
        isProcessing={transcriptProcessing}
        emptyLabel={
          transcriptProcessing
            ? "Расшифровка в обработке… Это может занять несколько минут."
            : tier === "fast"
              ? "Быстрая ветка для этого разговора недоступна (есть только финальная)."
              : "Расшифровка пока недоступна."
        }
      />
    </div>
  );
}
