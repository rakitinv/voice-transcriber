import { Link } from "react-router-dom";
import { Button } from "../components/Button";
import { RecordingDownloadIconButton } from "../components/RecordingDownloadIconButton";
import type { ConversationSummary } from "../types";
import styles from "./ConversationsList.module.css";

interface ConversationsListProps {
  conversations: ConversationSummary[];
  onDelete: (id: string) => void;
  onDownload: (id: string) => void;
  onDownloadOriginal: (id: string, fallbackExt?: string) => void;
  isDeletingId?: string | null;
}

function formatDate(dateStr: string): string {
  try {
    // Use toLocaleString: toLocaleDateString doesn't support timeStyle in all browsers.
    return new Date(dateStr).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return dateStr;
  }
}

function formatDuration(seconds: number): string {
  // Round up so sub-second durations aren't shown as 0:00.
  const whole = seconds > 0 ? Math.ceil(seconds) : 0;
  const m = Math.floor(whole / 60);
  const s = Math.floor(whole % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function ConversationsList({
  conversations,
  onDelete,
  onDownload,
  onDownloadOriginal,
  isDeletingId,
}: ConversationsListProps) {
  if (!conversations.length) {
    return (
      <div className={styles.empty}>
        <p>No conversations yet.</p>
      </div>
    );
  }

  return (
    <ul className={styles.list}>
      {conversations.map((c) => (
        <li key={c.id} className={styles.item}>
          <div className={styles.meta}>
            <span className={styles.date}>{formatDate(c.date)}</span>
            <span className={styles.duration}>{formatDuration(c.duration)}</span>
            <span className={styles.language}>{c.language}</span>
          </div>
          <div className={styles.actions}>
            <Link to={`/conversations/${c.id}`}>
              <Button variant="secondary">View</Button>
            </Link>
            <RecordingDownloadIconButton
              onClick={() => onDownloadOriginal(c.id, c.audioObjectExt)}
            />
            <Button
              variant="ghost"
              onClick={() => onDownload(c.id)}
            >
              Download
            </Button>
            <Button
              variant="danger"
              onClick={() => onDelete(c.id)}
              disabled={isDeletingId === c.id}
            >
              {isDeletingId === c.id ? "Deleting…" : "Delete"}
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
