import { useParams, Link } from "react-router-dom";
import { useConversation } from "../hooks/useConversations";
import { TranscriptViewer } from "../components/TranscriptViewer";
import { Button } from "../components/Button";
import { conversationsApi } from "../api/conversations";
import styles from "./ConversationViewerPage.module.css";

export function ConversationViewerPage() {
  const { id } = useParams<{ id: string }>();
  const { data: conversation, isLoading, isError, error } = useConversation(id);

  const handleDownload = () => {
    if (!id) return;
    conversationsApi.download(id).then((res) => {
      const blob = res.data;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `transcript-${id}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    }).catch(() => {});
  };

  if (isLoading) return <p className={styles.status}>Loading…</p>;
  if (isError) {
    return (
      <p className={styles.error}>
        {error instanceof Error ? error.message : "Failed to load conversation."}
      </p>
    );
  }
  if (!conversation) return null;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <Link to="/" className={styles.back}>← Conversations</Link>
        <div className={styles.actions}>
          <Button variant="secondary" onClick={handleDownload}>
            Download transcript
          </Button>
          <Button variant="ghost" disabled>
            Generate summary
          </Button>
        </div>
      </div>
      <div className={styles.meta}>
        <span>{new Date(conversation.date).toLocaleString()}</span>
        <span>{conversation.language}</span>
        <span>{Math.floor(conversation.duration / 60)}m {conversation.duration % 60}s</span>
      </div>
      {conversation.summary && (
        <div className={styles.summary}>
          <h3>Summary</h3>
          <p>{conversation.summary}</p>
        </div>
      )}
      <TranscriptViewer segments={conversation.transcript} />
    </div>
  );
}
