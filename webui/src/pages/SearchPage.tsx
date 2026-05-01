import { useState } from "react";
import { Link } from "react-router-dom";
import { useSearch } from "../hooks/useConversations";
import { Button } from "../components/Button";
import styles from "./SearchPage.module.css";

export function SearchPage() {
  const [text, setText] = useState("");
  const [semantic, setSemantic] = useState(false);
  const searchMutation = useSearch();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    searchMutation.mutate({ text: text.trim(), semantic });
  };

  const data = searchMutation.data;
  const results = data?.results ?? [];
  const hasResults = results.length > 0;

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Search</h1>
      <form onSubmit={handleSubmit} className={styles.form}>
        <input
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Search by text…"
          className={styles.input}
          autoFocus
        />
        <label className={styles.checkbox}>
          <input
            type="checkbox"
            checked={semantic}
            onChange={(e) => setSemantic(e.target.checked)}
          />
          Semantic search
        </label>
        <Button
          type="submit"
          variant="primary"
          disabled={!text.trim() || searchMutation.isPending}
        >
          {searchMutation.isPending ? "Searching…" : "Search"}
        </Button>
      </form>

      {searchMutation.isError && (
        <p className={styles.error}>
          {searchMutation.error instanceof Error
            ? searchMutation.error.message
            : "Search failed."}
        </p>
      )}

      {data && (
        <p className={styles.muted}>
          Mode: {data.mode} · {data.total} hit(s)
        </p>
      )}

      {hasResults && (
        <div className={styles.results}>
          <h2>Results</h2>
          <ul className={styles.hitList}>
            {results.map((hit) => (
              <li key={`${hit.conversation_id}-${hit.transcript_id}-${hit.start}`} className={styles.hit}>
                <div className={styles.hitMeta}>
                  <Link to={`/conversations/${hit.conversation_id}`} className={styles.hitLink}>
                    Conversation {hit.conversation_id.slice(0, 8)}…
                  </Link>
                  {hit.speaker && <span className={styles.speaker}>{hit.speaker}</span>}
                  <span className={styles.time}>
                    {hit.start.toFixed(1)}s – {hit.end.toFixed(1)}s
                  </span>
                </div>
                <p className={styles.hitText}>{hit.text}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {searchMutation.isSuccess && data && results.length === 0 && (
        <p className={styles.empty}>No results found.</p>
      )}
    </div>
  );
}
