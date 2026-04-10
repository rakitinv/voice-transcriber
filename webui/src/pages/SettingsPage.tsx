import { useSettingsLimits, useUserSettings, useUpdateUserSettings } from "../hooks/useConversations";
import { Button } from "../components/Button";
import type { UserSettings } from "../types";
import styles from "./SettingsPage.module.css";

export function SettingsPage() {
  const { data: limits, isLoading: limitsLoading } = useSettingsLimits();
  const { data: userSettings, isLoading: userLoading } = useUserSettings();
  const updateSettings = useUpdateUserSettings();

  const handleSave = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const defaultLanguage = (form.elements.namedItem("defaultLanguage") as HTMLInputElement)?.value;
    const defaultTtl = Number((form.elements.namedItem("defaultTtl") as HTMLInputElement)?.value);
    const searchMode = (form.elements.namedItem("searchMode") as HTMLSelectElement)?.value as UserSettings["searchMode"];
    if (defaultLanguage != null || defaultTtl != null || searchMode != null) {
      updateSettings.mutate({
        defaultLanguage: defaultLanguage ?? userSettings?.defaultLanguage,
        defaultTtl: Number.isFinite(defaultTtl) ? defaultTtl : userSettings?.defaultTtl,
        searchMode: searchMode ?? userSettings?.searchMode,
      });
    }
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Settings</h1>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Server limits</h2>
        {limitsLoading && <p className={styles.muted}>Loading…</p>}
        {!limitsLoading && limits && (
          <dl className={styles.dl}>
            <dt>Max duration</dt>
            <dd>{limits.maxDuration} s</dd>
            <dt>Max TTL</dt>
            <dd>{limits.maxTtl} days</dd>
            <dt>Max file size</dt>
            <dd>{limits.maxFileSize} bytes</dd>
          </dl>
        )}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>User settings</h2>
        {userLoading && <p className={styles.muted}>Loading…</p>}
        {!userLoading && (
          <form onSubmit={handleSave} className={styles.form}>
            <label className={styles.label}>
              Default language
              <input
                name="defaultLanguage"
                type="text"
                defaultValue={userSettings?.defaultLanguage ?? "en"}
                className={styles.input}
              />
            </label>
            <label className={styles.label}>
              Default TTL (days)
              <input
                name="defaultTtl"
                type="number"
                min={1}
                defaultValue={userSettings?.defaultTtl ?? 30}
                className={styles.input}
              />
            </label>
            <label className={styles.label}>
              Search mode
              <select
                name="searchMode"
                defaultValue={userSettings?.searchMode ?? "text"}
                className={styles.select}
              >
                <option value="text">Text</option>
                <option value="semantic">Semantic</option>
              </select>
            </label>
            <Button type="submit" variant="primary" disabled={updateSettings.isPending}>
              {updateSettings.isPending ? "Saving…" : "Save"}
            </Button>
          </form>
        )}
      </section>
    </div>
  );
}
