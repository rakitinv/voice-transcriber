import { Link } from "react-router-dom";
import { Button } from "../components/Button";
import type { ConversationSummary } from "../types";
import styles from "./ConversationsList.module.css";

interface ConversationsListProps {
  conversations: ConversationSummary[];
  onDelete: (id: string) => void;
  onDownload: (id: string) => void;
  isDeletingId?: string | null;
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return dateStr;
  }
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function ConversationsList({
  conversations,
  onDelete,
  onDownload,
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
