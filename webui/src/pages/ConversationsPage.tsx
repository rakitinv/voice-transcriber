import { useRef, type ChangeEvent } from "react";
import { ConversationsList } from "./ConversationsList";
import {
  useConversations,
  useDeleteConversation,
  useUploadAudio,
} from "../hooks/useConversations";
import { useMicrophoneRecorder } from "../hooks/useMicrophoneRecorder";
import { Button } from "../components/Button";
import { conversationsApi } from "../api/conversations";
import { notifyError } from "../utils/notify";
import styles from "./ConversationsPage.module.css";

const UPLOAD_ACCEPT =
  "audio/*,.webm,.mp3,.wav,.m4a,.aac,.ogg,.flac,.opus";

export function ConversationsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { data: conversations = [], isLoading, isError, error } = useConversations();
  const deleteMutation = useDeleteConversation();
  const uploadMutation = useUploadAudio();
  const {
    isRecording,
    startRecording,
    stopRecording,
    discardRecording,
  } = useMicrophoneRecorder();

  const handleDownload = (id: string) => {
    void conversationsApi.exportTranscript(id, "md");
  };

  const handleDownloadOriginal = (id: string, fallbackExt?: string) => {
    void conversationsApi.downloadOriginalAudio(id, fallbackExt ?? "webm");
  };

  const handlePickFile = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    uploadMutation.mutate(file);
  };

  const handleStartMic = async () => {
    try {
      await startRecording();
    } catch (err) {
      notifyError(
        err instanceof Error
          ? err.message
          : "Не удалось получить доступ к микрофону."
      );
    }
  };

  const handleStopMicAndUpload = async () => {
    try {
      const file = await stopRecording();
      uploadMutation.mutate(file);
    } catch (err) {
      notifyError(
        err instanceof Error ? err.message : "Не удалось завершить запись."
      );
    }
  };

  const uploadBusy = uploadMutation.isPending;
  const disableFilePick = uploadBusy || isRecording;

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <h1 className={styles.title}>Разговоры</h1>
        <div className={styles.toolbarActions}>
          <input
            ref={fileInputRef}
            type="file"
            className={styles.hiddenFileInput}
            accept={UPLOAD_ACCEPT}
            tabIndex={-1}
            onChange={handleFileChange}
          />
          <Button
            variant="primary"
            onClick={handlePickFile}
            disabled={disableFilePick}
          >
            {uploadBusy ? "Загрузка…" : "Загрузить аудио"}
          </Button>
          {!isRecording ? (
            <Button
              variant="secondary"
              onClick={() => void handleStartMic()}
              disabled={uploadBusy}
            >
              Запись с микрофона
            </Button>
          ) : (
            <>
              <span className={styles.recordingLabel}>Идёт запись…</span>
              <Button
                variant="danger"
                onClick={() => void handleStopMicAndUpload()}
                disabled={uploadBusy}
              >
                Остановить и отправить
              </Button>
              <Button
                variant="ghost"
                onClick={discardRecording}
                disabled={uploadBusy}
              >
                Отмена
              </Button>
            </>
          )}
        </div>
      </div>
      {isLoading && <p className={styles.status}>Загрузка…</p>}
      {isError && (
        <p className={styles.error}>
          {error instanceof Error ? error.message : "Не удалось загрузить список разговоров."}
        </p>
      )}
      {!isLoading && !isError && (
        <ConversationsList
          conversations={conversations}
          onDelete={(id) => deleteMutation.mutate(id)}
          onDownload={handleDownload}
          onDownloadOriginal={handleDownloadOriginal}
          isDeletingId={deleteMutation.isPending ? deleteMutation.variables ?? null : null}
        />
      )}
    </div>
  );
}
