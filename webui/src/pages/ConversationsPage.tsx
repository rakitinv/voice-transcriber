import { ConversationsList } from "./ConversationsList";
import { useConversations, useDeleteConversation } from "../hooks/useConversations";
import { conversationsApi } from "../api/conversations";
import styles from "./ConversationsPage.module.css";

export function ConversationsPage() {
  const { data: conversations = [], isLoading, isError, error } = useConversations();
  const deleteMutation = useDeleteConversation();

  const handleDownload = (id: string) => {
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

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Conversations</h1>
      {isLoading && <p className={styles.status}>Loading…</p>}
      {isError && (
        <p className={styles.error}>
          {error instanceof Error ? error.message : "Failed to load conversations."}
        </p>
      )}
      {!isLoading && !isError && (
        <ConversationsList
          conversations={conversations}
          onDelete={(id) => deleteMutation.mutate(id)}
          onDownload={handleDownload}
          isDeletingId={deleteMutation.isPending ? deleteMutation.variables ?? null : null}
        />
      )}
    </div>
  );
}
