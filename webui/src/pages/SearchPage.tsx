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
      <h1 className={styles.title}>Поиск</h1>
      <form onSubmit={handleSubmit} className={styles.form}>
        <input
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Поиск по тексту…"
          className={styles.input}
          autoFocus
        />
        <label className={styles.checkbox}>
          <input
            type="checkbox"
            checked={semantic}
            onChange={(e) => setSemantic(e.target.checked)}
          />
          Семантический поиск
        </label>
        <Button
          type="submit"
          variant="primary"
          disabled={!text.trim() || searchMutation.isPending}
        >
          {searchMutation.isPending ? "Поиск…" : "Найти"}
        </Button>
      </form>

      {searchMutation.isError && (
        <p className={styles.error}>
          {searchMutation.error instanceof Error
            ? searchMutation.error.message
            : "Поиск не выполнен."}
        </p>
      )}

      {data && (
        <p className={styles.muted}>
          Режим: {data.mode} · совпадений: {data.total}
        </p>
      )}

      {hasResults && (
        <div className={styles.results}>
          <h2>Результаты</h2>
          <ul className={styles.hitList}>
            {results.map((hit) => (
              <li key={`${hit.conversation_id}-${hit.transcript_id}-${hit.start}`} className={styles.hit}>
                <div className={styles.hitMeta}>
                  <Link to={`/conversations/${hit.conversation_id}`} className={styles.hitLink}>
                    Разговор {hit.conversation_id.slice(0, 8)}…
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
        <p className={styles.empty}>Ничего не найдено.</p>
      )}
    </div>
  );
}
