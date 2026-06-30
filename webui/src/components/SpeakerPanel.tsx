import { useCallback, useEffect, useState } from "react";
import { Button } from "./Button";
import { conversationsApi } from "../api/conversations";
import type { SpeakerLabelEntry, SpeakersState } from "../types";
import styles from "./SpeakerPanel.module.css";

interface SpeakerPanelProps {
  conversationId: string;
  /** From GET conversation — initial hint */
  initialSpeakerIds?: string[];
  initialLabels?: Record<string, SpeakerLabelEntry>;
  initialIdentifyStatus?: string | null;
  identifyEnabled?: boolean;
  hasDiarizedTranscript?: boolean;
  onUpdated?: () => void | Promise<void>;
}

function displayForSpeaker(
  speakerId: string,
  labels: Record<string, SpeakerLabelEntry>
): string {
  const entry = labels[speakerId];
  if (!entry) return speakerId;
  if (entry.source === "llm_suggested") {
    return entry.suggested_name || entry.display_name || speakerId;
  }
  return entry.display_name || speakerId;
}

/** Имя, которое сейчас показано в расшифровке (до применения LLM-предложения — ID). */
function transcriptNameForSpeaker(
  speakerId: string,
  labels: Record<string, SpeakerLabelEntry>
): string {
  const entry = labels[speakerId];
  if (!entry) return speakerId;
  if (entry.source === "llm_suggested") return speakerId;
  const name = entry.display_name?.trim();
  return name || speakerId;
}

export function SpeakerPanel({
  conversationId,
  initialSpeakerIds = [],
  initialLabels = {},
  initialIdentifyStatus = null,
  identifyEnabled = false,
  hasDiarizedTranscript = false,
  onUpdated,
}: SpeakerPanelProps) {
  const [state, setState] = useState<SpeakersState | null>(null);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!hasDiarizedTranscript) return;
    try {
      const data = await conversationsApi.getSpeakers(conversationId);
      setState(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить спикеров");
    }
  }, [conversationId, hasDiarizedTranscript]);

  useEffect(() => {
    if (!hasDiarizedTranscript) {
      setState(null);
      return;
    }
    setState({
      speaker_ids: initialSpeakerIds,
      speaker_labels: initialLabels,
      speaker_identification_status: initialIdentifyStatus,
      speaker_identification_enabled: identifyEnabled,
    });
    void load();
  }, [
    conversationId,
    hasDiarizedTranscript,
    identifyEnabled,
    initialIdentifyStatus,
    initialLabels,
    initialSpeakerIds,
    load,
  ]);

  if (!hasDiarizedTranscript) return null;

  const labels = state?.speaker_labels ?? initialLabels;
  const speakerIds = state?.speaker_ids?.length
    ? state.speaker_ids
    : initialSpeakerIds;
  const identifyStatus = state?.speaker_identification_status ?? initialIdentifyStatus;
  const showIdentify = state?.speaker_identification_enabled ?? identifyEnabled;

  const pending = speakerIds.filter(
    (sid) => labels[sid]?.source === "llm_suggested"
  );

  const handleSaveRename = async (speakerId: string) => {
    const name = (editing[speakerId] ?? "").trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const data = await conversationsApi.patchSpeakers(conversationId, [
        { speaker_id: speakerId, display_name: name },
      ]);
      setState(data);
      setEditing((prev) => {
        const next = { ...prev };
        delete next[speakerId];
        return next;
      });
      await onUpdated?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить имя");
    } finally {
      setBusy(false);
    }
  };

  const handleApply = async (ids?: string[]) => {
    setBusy(true);
    setError(null);
    try {
      const data = await conversationsApi.applySpeakerSuggestions(conversationId, ids);
      setState(data);
      await onUpdated?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось применить предложения");
    } finally {
      setBusy(false);
    }
  };

  const handleIdentify = async () => {
    setBusy(true);
    setError(null);
    try {
      await conversationsApi.identifySpeakers(conversationId);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось запустить определение имён");
    } finally {
      setBusy(false);
    }
  };

  if (!speakerIds.length) return null;

  return (
    <section className={styles.panel} aria-label="Спикеры">
      <div className={styles.header}>
        <h3 className={styles.title}>Спикеры</h3>
        {showIdentify ? (
          <Button
            type="button"
            variant="secondary"
            disabled={busy || identifyStatus === "running"}
            onClick={() => void handleIdentify()}
          >
            {identifyStatus === "running" ? "Определение…" : "Определить имена (LLM)"}
          </Button>
        ) : null}
      </div>

      {pending.length > 0 ? (
        <div className={styles.suggestions} role="status">
          <p className={styles.suggestionsLead}>
            Предложены имена спикеров — проверьте и примите или измените.
          </p>
          <div className={styles.suggestionActions}>
            <Button
              type="button"
              disabled={busy}
              onClick={() => void handleApply()}
            >
              Принять все
            </Button>
          </div>
        </div>
      ) : null}

      <ul className={styles.chips}>
        {speakerIds.map((sid) => {
          const entry = labels[sid];
          const isPending = entry?.source === "llm_suggested";
          const currentInTranscript = transcriptNameForSpeaker(sid, labels);
          const isRenamed = currentInTranscript !== sid;
          const shown = displayForSpeaker(sid, labels);
          const draft = editing[sid] ?? shown;
          return (
            <li key={sid} className={styles.chip}>
              <div className={styles.chipSource}>
                <span className={styles.chipCurrentName}>{currentInTranscript}</span>
                {isRenamed ? (
                  <span className={styles.chipDiarizationId} title="ID диаризации">
                    {sid}
                  </span>
                ) : null}
              </div>
              <span className={styles.arrow} aria-hidden>
                →
              </span>
              <input
                className={styles.nameInput}
                value={draft}
                disabled={busy}
                onChange={(e) =>
                  setEditing((prev) => ({ ...prev, [sid]: e.target.value }))
                }
                aria-label={
                  isRenamed
                    ? `Новое имя вместо «${currentInTranscript}»`
                    : `Имя вместо «${currentInTranscript}»`
                }
              />
              <Button
                type="button"
                variant="secondary"
                disabled={busy || !draft.trim()}
                onClick={() => void handleSaveRename(sid)}
              >
                Сохранить
              </Button>
              {isPending ? (
                <>
                  <Button
                    type="button"
                    disabled={busy}
                    onClick={() => void handleApply([sid])}
                  >
                    Принять
                  </Button>
                  {entry?.confidence != null ? (
                    <span className={styles.confidence}>
                      {Math.round(entry.confidence * 100)}%
                    </span>
                  ) : null}
                  {entry?.evidence ? (
                    <span className={styles.evidence} title={entry.evidence}>
                      {entry.evidence}
                    </span>
                  ) : null}
                </>
              ) : null}
            </li>
          );
        })}
      </ul>

      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}
