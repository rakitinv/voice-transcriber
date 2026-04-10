import { useState } from "react";
import { useSearch } from "../hooks/useConversations";
import { Button } from "../components/Button";
import { TranscriptViewer } from "../components/TranscriptViewer";
import type { SearchResult } from "../types";
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

  const results = searchMutation.data as SearchResult[] | undefined;
  const hasResults = Array.isArray(results) && results.length > 0;

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

      {hasResults && (
        <div className={styles.results}>
          <h2>Results</h2>
          {results!.map((r, i) => (
            <div key={`${r.conversationId}-${i}`} className={styles.resultCard}>
              <div className={styles.resultMeta}>
                <span>{new Date(r.date).toLocaleDateString()}</span>
                <span>{r.language}</span>
                <span>{Math.floor(r.duration / 60)}m</span>
              </div>
              {r.matches?.length > 0 ? (
                <TranscriptViewer segments={r.matches} />
              ) : (
                <p className={styles.noMatches}>No transcript segments.</p>
              )}
            </div>
          ))}
        </div>
      )}

      {searchMutation.isSuccess && Array.isArray(results) && results.length === 0 && (
        <p className={styles.empty}>No results found.</p>
      )}
    </div>
  );
}
