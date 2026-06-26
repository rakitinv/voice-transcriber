import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const TOKEN_KEY = "vt_admin_jwt";
const REFRESH_KEY = "vt_admin_refresh";

function adminApiBase(): string {
  const raw = (import.meta.env.VITE_ADMIN_API_BASE_URL || "http://localhost:8003").replace(
    /\/$/,
    ""
  );
  return raw;
}

/** Main product API (OAuth + refresh); not Admin API. */
function publicApiBase(): string {
  const raw = (import.meta.env.VITE_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");
  if (raw) return raw;
  return "http://localhost:8002";
}

/** Landing URL after OAuth (origin + path, e.g. `https://host/admin`). Allowlist on API compares origin only. */
function adminSelfLandingUrl(): string {
  const configured = (import.meta.env.VITE_ADMIN_WEBUI_SELF_URL || "").trim();
  if (configured) return configured.replace(/\/$/, "");
  if (typeof window !== "undefined") {
    const viteBase = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");
    if (viteBase && viteBase !== "/") {
      return `${window.location.protocol}//${window.location.host}${viteBase}`;
    }
    const path = window.location.pathname.replace(/\/$/, "") || "";
    if (path && path !== "/") {
      return `${window.location.protocol}//${window.location.host}${path}`;
    }
    return `${window.location.protocol}//${window.location.host}`;
  }
  return "http://localhost:5174";
}

function oauthGoogleHref(): string {
  const next = encodeURIComponent(adminSelfLandingUrl());
  return `${publicApiBase()}/api/auth/google?client=admin&next=${next}`;
}

function oauthYandexHref(): string {
  const next = encodeURIComponent(adminSelfLandingUrl());
  return `${publicApiBase()}/api/auth/yandex?client=admin&next=${next}`;
}

function parseHashTokens(hash: string): { access: string | null; refresh: string | null } {
  if (!hash || hash === "#") return { access: null, refresh: null };
  const q = hash.startsWith("#") ? hash.slice(1) : hash;
  const sp = new URLSearchParams(q);
  return {
    access: sp.get("access_token"),
    refresh: sp.get("refresh_token"),
  };
}

async function adminFetch(path: string, token: string, init?: RequestInit): Promise<Response> {
  return fetch(`${adminApiBase()}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  });
}

async function refreshAccessToken(refreshPlain: string): Promise<{ access: string; refresh: string } | null> {
  const r = await fetch(`${publicApiBase()}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ refresh_token: refreshPlain }),
  });
  if (!r.ok) return null;
  const j = (await r.json()) as { access_token?: string; refresh_token?: string };
  if (!j.access_token || !j.refresh_token) return null;
  return { access: j.access_token, refresh: j.refresh_token };
}

/** Base interval for admin tab auto-refresh (see docs/adr/0002-admin-console-live-updates.md). */
const ADMIN_REFRESH_BASE_MS = 5000;
const ADMIN_REFRESH_MAX_MS = 60_000;
const ADMIN_REFRESH_JITTER_RATIO = 0.28;
/** When the browser tab is hidden, only wake periodically (no full data poll each cycle). */
const ADMIN_HIDDEN_WAKE_MS = 15_000;

function adminJitteredBaseDelayMs(): number {
  const span = ADMIN_REFRESH_BASE_MS * ADMIN_REFRESH_JITTER_RATIO;
  const jitter = Math.floor((Math.random() * 2 - 1) * span);
  return Math.max(2000, ADMIN_REFRESH_BASE_MS + jitter);
}

/**
 * Polling v2: jitter, exponential backoff on failure, pause when document is hidden,
 * reset backoff when `resetNonce` changes (manual «Обновить сейчас»).
 */
function useAdminTabAutoRefresh(
  enabled: boolean,
  token: string,
  refresh: () => Promise<boolean>,
  resetNonce: number
): void {
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const tokenRef = useRef(token);
  tokenRef.current = token;

  useEffect(() => {
    if (!enabled) return;
    if (!tokenRef.current.trim()) return;

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    let delayMs = adminJitteredBaseDelayMs();

    const schedule = (ms: number) => {
      if (timeoutId !== undefined) clearTimeout(timeoutId);
      timeoutId = setTimeout(() => void loop(), ms);
    };

    const loop = async () => {
      if (cancelled) return;
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        schedule(ADMIN_HIDDEN_WAKE_MS);
        return;
      }
      let ok = false;
      try {
        ok = await refreshRef.current();
      } catch {
        ok = false;
      }
      if (cancelled) return;
      if (ok) {
        delayMs = adminJitteredBaseDelayMs();
      } else {
        delayMs = Math.min(Math.floor(delayMs * 1.85), ADMIN_REFRESH_MAX_MS);
        delayMs = Math.max(delayMs, ADMIN_REFRESH_BASE_MS);
      }
      schedule(delayMs);
    };

    const onVisibility = () => {
      if (cancelled) return;
      if (typeof document === "undefined" || document.visibilityState !== "visible") return;
      delayMs = adminJitteredBaseDelayMs();
      void (async () => {
        try {
          await refreshRef.current();
        } catch {
          /* ignore */
        }
        if (!cancelled) schedule(delayMs);
      })();
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }
    schedule(delayMs);

    return () => {
      cancelled = true;
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [enabled, token, resetNonce]);
}

export function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
  /** Latest trimmed bearer used for API; in-flight responses must match this before setState. */
  const activeAuthRef = useRef("");
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<
    "list" | "detail" | "infra" | "tools" | "audit" | "pipeline" | "pipeline_events"
  >("list");
  const [listJson, setListJson] = useState<string>("");
  const [detailId, setDetailId] = useState("");
  const [detailJson, setDetailJson] = useState<string>("");
  const [infraJson, setInfraJson] = useState<string>("");
  const [toolsJson, setToolsJson] = useState<string>("");
  const [auditJson, setAuditJson] = useState<string>("");
  const [pipelineJson, setPipelineJson] = useState<string>("");
  const [pipelineEventsJson, setPipelineEventsJson] = useState<string>("");
  const [pipelineEventsLive, setPipelineEventsLive] = useState(false);
  const pipelineEventsCursorRef = useRef<{ at: string; id: string }>({
    at: "1970-01-01T00:00:00.000Z",
    id: "00000000-0000-0000-0000-000000000000",
  });
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [manualTick, setManualTick] = useState(0);

  useEffect(() => {
    const { access, refresh } = parseHashTokens(window.location.hash || "");
    if (access) {
      setToken(access);
      localStorage.setItem(TOKEN_KEY, access);
      if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
      setError(null);
      const path = window.location.pathname + (window.location.search || "");
      window.history.replaceState(null, "", path);
    }
  }, []);

  const saveToken = useCallback(() => {
    const trimmed = token.trim();
    localStorage.setItem(TOKEN_KEY, trimmed);
    setError(null);
    if (trimmed) {
      void adminFetch("/admin/api/v1/me", trimmed).catch(() => {
        /* ignore */
      });
    }
  }, [token]);

  const clearToken = useCallback(() => {
    setToken("");
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    setError(null);
    setPipelineEventsLive(false);
    setListJson("");
    setDetailJson("");
    setDetailId("");
    setInfraJson("");
    setToolsJson("");
    setAuditJson("");
    setPipelineJson("");
    setPipelineEventsJson("");
    setActionMsg(null);
    pipelineEventsCursorRef.current = {
      at: "1970-01-01T00:00:00.000Z",
      id: "00000000-0000-0000-0000-000000000000",
    };
  }, []);

  const tryRefresh = useCallback(async () => {
    const rt = (localStorage.getItem(REFRESH_KEY) || "").trim();
    if (!rt) {
      setError("Нет refresh-токена (войдите через OAuth ещё раз или вставьте JWT вручную).");
      return;
    }
    setError(null);
    const out = await refreshAccessToken(rt);
    if (!out) {
      setError("Refresh не удался (401/429). Войдите снова или вставьте access JWT.");
      return;
    }
    setToken(out.access);
    localStorage.setItem(TOKEN_KEY, out.access);
    localStorage.setItem(REFRESH_KEY, out.refresh);
  }, []);

  const authHeaders = useMemo(() => token.trim(), [token]);
  activeAuthRef.current = authHeaders;

  useEffect(() => {
    const t = (localStorage.getItem(TOKEN_KEY) || "").trim();
    if (!t) return;
    void adminFetch("/admin/api/v1/me", t).catch(() => {
      /* ignore */
    });
  }, []);

  const loadList = useCallback(async (): Promise<boolean> => {
    const authAtStart = authHeaders;
    if (!authAtStart) return false;
    setError(null);
    const r = await adminFetch("/admin/api/v1/conversations?limit=30", authAtStart);
    const t = await r.text();
    if (authAtStart !== activeAuthRef.current) return false;
    if (!r.ok) {
      setError(`${r.status}: ${t}`);
      return false;
    }
    try {
      setListJson(JSON.stringify(JSON.parse(t), null, 2));
    } catch {
      setListJson(t);
    }
    return true;
  }, [authHeaders]);

  const loadDetail = useCallback(async (): Promise<boolean> => {
    const authAtStart = authHeaders;
    if (!authAtStart) return false;
    setError(null);
    const id = detailId.trim();
    if (!id) {
      setError("Укажите UUID разговора");
      return false;
    }
    const r = await adminFetch(`/admin/api/v1/conversations/${id}`, authAtStart);
    const t = await r.text();
    if (authAtStart !== activeAuthRef.current) return false;
    if (!r.ok) {
      setError(`${r.status}: ${t}`);
      return false;
    }
    try {
      setDetailJson(JSON.stringify(JSON.parse(t), null, 2));
    } catch {
      setDetailJson(t);
    }
    return true;
  }, [authHeaders, detailId]);

  const loadInfra = useCallback(async (): Promise<boolean> => {
    const authAtStart = authHeaders;
    if (!authAtStart) return false;
    setError(null);
    const r = await adminFetch("/admin/api/v1/infrastructure", authAtStart);
    const t = await r.text();
    if (authAtStart !== activeAuthRef.current) return false;
    if (!r.ok) {
      setError(`${r.status}: ${t}`);
      return false;
    }
    try {
      setInfraJson(JSON.stringify(JSON.parse(t), null, 2));
    } catch {
      setInfraJson(t);
    }
    return true;
  }, [authHeaders]);

  const loadTools = useCallback(async (): Promise<boolean> => {
    const authAtStart = authHeaders;
    if (!authAtStart) return false;
    setError(null);
    const r = await adminFetch("/admin/api/v1/external-tools", authAtStart);
    const t = await r.text();
    if (authAtStart !== activeAuthRef.current) return false;
    if (!r.ok) {
      setError(`${r.status}: ${t}`);
      return false;
    }
    try {
      setToolsJson(JSON.stringify(JSON.parse(t), null, 2));
    } catch {
      setToolsJson(t);
    }
    return true;
  }, [authHeaders]);

  const loadAudit = useCallback(async (): Promise<boolean> => {
    const authAtStart = authHeaders;
    if (!authAtStart) return false;
    setError(null);
    const r = await adminFetch("/admin/api/v1/audit-events?limit=50", authAtStart);
    const t = await r.text();
    if (authAtStart !== activeAuthRef.current) return false;
    if (!r.ok) {
      setError(`${r.status}: ${t}`);
      return false;
    }
    try {
      setAuditJson(JSON.stringify(JSON.parse(t), null, 2));
    } catch {
      setAuditJson(t);
    }
    return true;
  }, [authHeaders]);

  const loadPipeline = useCallback(async (): Promise<boolean> => {
    const authAtStart = authHeaders;
    if (!authAtStart) return false;
    setError(null);
    const r = await adminFetch("/admin/api/v1/pipeline-settings", authAtStart);
    const t = await r.text();
    if (authAtStart !== activeAuthRef.current) return false;
    if (!r.ok) {
      setError(`${r.status}: ${t}`);
      return false;
    }
    try {
      setPipelineJson(JSON.stringify(JSON.parse(t), null, 2));
    } catch {
      setPipelineJson(t);
    }
    return true;
  }, [authHeaders]);

  const loadPipelineEvents = useCallback(async (): Promise<boolean> => {
    const authAtStart = authHeaders;
    if (!authAtStart) return false;
    setError(null);
    const r = await adminFetch("/admin/api/v1/pipeline-events?limit=80", authAtStart);
    const t = await r.text();
    if (authAtStart !== activeAuthRef.current) return false;
    if (!r.ok) {
      setError(`${r.status}: ${t}`);
      return false;
    }
    try {
      const parsed = JSON.parse(t) as {
        items?: { id: string; created_at: string }[];
      };
      setPipelineEventsJson(JSON.stringify(parsed, null, 2));
      const row0 = parsed?.items?.[0];
      if (row0?.created_at && row0?.id) {
        pipelineEventsCursorRef.current = { at: row0.created_at, id: row0.id };
      } else {
        pipelineEventsCursorRef.current = {
          at: new Date().toISOString(),
          id: "00000000-0000-0000-0000-000000000000",
        };
      }
    } catch {
      setPipelineEventsJson(t);
    }
    return true;
  }, [authHeaders]);

  useAdminTabAutoRefresh(tab === "list" && !!authHeaders, authHeaders, loadList, manualTick);
  useAdminTabAutoRefresh(tab === "infra" && !!authHeaders, authHeaders, loadInfra, manualTick);
  useAdminTabAutoRefresh(tab === "audit" && !!authHeaders, authHeaders, loadAudit, manualTick);
  useAdminTabAutoRefresh(tab === "pipeline" && !!authHeaders, authHeaders, loadPipeline, manualTick);

  useEffect(() => {
    if (!authHeaders) return;
    if (tab === "list") void loadList();
    if (tab === "infra") void loadInfra();
    if (tab === "audit") void loadAudit();
    if (tab === "pipeline") void loadPipeline();
  }, [tab, authHeaders, manualTick, loadList, loadInfra, loadAudit, loadPipeline]);

  useEffect(() => {
    if (tab !== "pipeline_events" || !authHeaders.trim() || !pipelineEventsLive) return;

    const pollAuth = authHeaders;

    const cur0 = pipelineEventsCursorRef.current;
    const neverLoaded =
      cur0.at === "1970-01-01T00:00:00.000Z" &&
      cur0.id === "00000000-0000-0000-0000-000000000000";
    if (neverLoaded) {
      pipelineEventsCursorRef.current = {
        at: new Date().toISOString(),
        id: "00000000-0000-0000-0000-000000000000",
      };
    }

    const ac = new AbortController();
    let cancelled = false;

    const mergeWait = (
      prev: string,
      incoming: {
        id: string;
        created_at: string;
        conversation_id: string;
        event_type: string;
        transcript_id?: number | null;
        detail?: unknown;
      }[]
    ) => {
      let doc: {
        items: typeof incoming;
        total?: number;
        limit?: number;
        offset?: number;
      };
      try {
        doc = JSON.parse(prev || "{}");
      } catch {
        doc = { items: [] };
      }
      if (!Array.isArray(doc.items)) doc.items = [];
      const seen = new Set(doc.items.map((x) => x.id));
      for (const it of incoming) {
        if (!seen.has(it.id)) {
          doc.items.unshift(it);
          seen.add(it.id);
        }
      }
      doc.items.sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime() ||
          a.id.localeCompare(b.id)
      );
      if (doc.items.length > 400) doc.items = doc.items.slice(0, 400);
      if (typeof doc.total === "number") doc.total = Math.max(doc.total, doc.items.length);
      return JSON.stringify(doc, null, 2);
    };

    void (async function pollLoop() {
      while (!cancelled) {
        const cur = pipelineEventsCursorRef.current;
        const sp = new URLSearchParams();
        sp.set("since_created_at", cur.at);
        sp.set("since_id", cur.id);
        sp.set("timeout_seconds", "25");
        const url = `${adminApiBase()}/admin/api/v1/pipeline-events/wait?${sp.toString()}`;
        let r: Response;
        try {
          r = await fetch(url, {
            headers: { Authorization: `Bearer ${pollAuth}`, Accept: "application/json" },
            signal: ac.signal,
          });
        } catch (e) {
          if ((e as { name?: string }).name === "AbortError") return;
          if (pollAuth !== activeAuthRef.current) return;
          setError(String(e));
          return;
        }
        const t = await r.text();
        if (pollAuth !== activeAuthRef.current) return;
        if (!r.ok) {
          setError(`${r.status}: ${t}`);
          return;
        }
        const body = JSON.parse(t) as {
          items?: {
            id: string;
            created_at: string;
            conversation_id: string;
            event_type: string;
            transcript_id?: number | null;
            detail?: unknown;
          }[];
        };
        const incoming = body.items || [];
        if (incoming.length > 0) {
          if (pollAuth !== activeAuthRef.current) return;
          setPipelineEventsJson((prev) => {
            if (pollAuth !== activeAuthRef.current) return prev;
            const next = mergeWait(prev || "{}", incoming);
            try {
              const d = JSON.parse(next) as { items?: { id: string; created_at: string }[] };
              const top = d?.items?.[0];
              if (top?.created_at && top?.id) {
                pipelineEventsCursorRef.current = { at: top.created_at, id: top.id };
              }
            } catch {
              /* ignore */
            }
            return next;
          });
        }
        if (cancelled) return;
      }
    })();

    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [tab, authHeaders, pipelineEventsLive]);

  const postAction = useCallback(
    async (path: string) => {
      const authAtStart = authHeaders;
      if (!authAtStart) return;
      setActionMsg(null);
      setError(null);
      const r = await adminFetch(path, authAtStart, { method: "POST" });
      const t = await r.text();
      if (authAtStart !== activeAuthRef.current) return;
      if (!r.ok) {
        setError(`${r.status}: ${t}`);
        setActionMsg(null);
        return;
      }
      setActionMsg(`${r.status}: ${t}`);
      await loadDetail();
    },
    [authHeaders, loadDetail]
  );

  return (
    <div style={{ fontFamily: "system-ui,sans-serif", maxWidth: 960, margin: "0 auto", padding: 16 }}>
      <h1 style={{ fontSize: "1.35rem" }}>Ops-консоль</h1>
      <section style={{ marginBottom: 16, padding: 12, background: "#f0f4f8", borderRadius: 8 }}>
        <p style={{ margin: "0 0 8px", fontSize: "0.9rem", color: "#333" }}>
          <strong>Вход:</strong> OAuth через тот же продуктовый API (тот же JWT, что у основного Web UI). После
          провайдера браузер вернётся на эту страницу с токенами в URL (фрагмент), затем фрагмент очищается.
          На сервисе API должны быть заданы совпадающие <code>VT_ADMIN_WEBUI_ORIGIN</code> (или{" "}
          <code>VT_ADMIN_WEBUI_ORIGINS</code>) и URL этой консоли.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <a
            href={oauthGoogleHref()}
            style={{
              display: "inline-block",
              padding: "8px 14px",
              background: "#1a73e8",
              color: "#fff",
              textDecoration: "none",
              borderRadius: 4,
              fontWeight: 600,
            }}
          >
            Google
          </a>
          <a
            href={oauthYandexHref()}
            style={{
              display: "inline-block",
              padding: "8px 14px",
              background: "#fc3f1e",
              color: "#fff",
              textDecoration: "none",
              borderRadius: 4,
              fontWeight: 600,
            }}
          >
            Яндекс
          </a>
          <button type="button" onClick={tryRefresh}>
            Обновить access по refresh
          </button>
          <button type="button" onClick={clearToken}>
            Выйти (очистить токены)
          </button>
        </div>
        <p style={{ margin: "10px 0 0", fontSize: "0.8rem", color: "#555" }}>
          OAuth API: <code>{publicApiBase()}</code> · эта страница: <code>{adminSelfLandingUrl()}</code>
        </p>
      </section>
      <p style={{ color: "#444", fontSize: "0.9rem" }}>
        Либо вставьте <strong>access JWT</strong> вручную (тот же пользователь с записью в{" "}
        <code>admin_memberships</code>). Сохраните токен перед запросами. При сохранении вызывается{" "}
        <code>GET /me</code> — в аудите появляется <code>admin_console_session</code>.
      </p>
      <label style={{ display: "block", marginBottom: 8 }}>
        Bearer access token
        <textarea
          style={{ display: "block", width: "100%", minHeight: 72, marginTop: 4 }}
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="eyJ..."
        />
      </label>
      <button type="button" onClick={saveToken}>
        Сохранить токен локально
      </button>
      {error ? (
        <pre style={{ color: "#b00020", background: "#fee", padding: 12, marginTop: 12 }}>{error}</pre>
      ) : null}
      <nav style={{ marginTop: 20, display: "flex", gap: 8, flexWrap: "wrap" }}>
        {(
          [
            ["list", "Разговоры"],
            ["detail", "Карточка"],
            ["infra", "Инфраструктура"],
            ["pipeline", "Пайплайн"],
            ["pipeline_events", "События пайплайна"],
            ["tools", "Внешние ссылки"],
            ["audit", "Аудит"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            type="button"
            onClick={() => setTab(k)}
            style={{
              fontWeight: tab === k ? 700 : 400,
              border: tab === k ? "2px solid #333" : "1px solid #ccc",
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      {tab === "list" ? (
        <section style={{ marginTop: 16 }}>
          <p style={{ fontSize: "0.85rem", color: "#555" }}>
            Список обновляется автоматически (интервал с джиттером, до 60 с при ошибках сети). Во
            вкладке браузера в фоне запросы реже. Кнопка ниже сбрасывает интервал и перезагружает
            сразу.
          </p>
          <button
            type="button"
            onClick={() => {
              setManualTick((x) => x + 1);
            }}
          >
            Обновить сейчас
          </button>
          <pre style={{ background: "#f6f8fa", padding: 12, overflow: "auto", maxHeight: 480 }}>
            {listJson || "—"}
          </pre>
        </section>
      ) : null}
      {tab === "detail" ? (
        <section style={{ marginTop: 16 }}>
          <label>
            conversation_id (UUID)
            <input
              style={{ display: "block", width: "100%", marginTop: 4, marginBottom: 8 }}
              value={detailId}
              onChange={(e) => setDetailId(e.target.value)}
            />
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
            <button type="button" onClick={loadDetail}>
              Загрузить карточку
            </button>
            <button
              type="button"
              onClick={() =>
                postAction(`/admin/api/v1/conversations/${detailId.trim()}/actions/retranscribe`)
              }
            >
              Повтор ASR
            </button>
            <button
              type="button"
              onClick={() =>
                postAction(
                  `/admin/api/v1/conversations/${detailId.trim()}/actions/reindex-embedding`
                )
              }
            >
              Переиндексировать embedding
            </button>
            <button
              type="button"
              onClick={() =>
                postAction(`/admin/api/v1/conversations/${detailId.trim()}/actions/rediarize`)
              }
            >
              Повтор диаризации
            </button>
            <button
              type="button"
              onClick={() =>
                postAction(`/admin/api/v1/conversations/${detailId.trim()}/actions/resummary`)
              }
            >
              Повтор сводки сессии (LLM)
            </button>
          </div>
          {actionMsg ? (
            <pre style={{ background: "#e8f5e9", padding: 8, marginBottom: 8 }}>{actionMsg}</pre>
          ) : null}
          <pre style={{ background: "#f6f8fa", padding: 12, overflow: "auto", maxHeight: 480 }}>
            {detailJson || "—"}
          </pre>
        </section>
      ) : null}
      {tab === "infra" ? (
        <section style={{ marginTop: 16 }}>
          <p style={{ fontSize: "0.85rem", color: "#555" }}>
            Автообновление (джиттер, backoff при ошибках, реже в фоновой вкладке браузера). Кнопка —
            принудительно. Поле <code>compatibility_issues</code> — рассинхрон конфига и стека
            (например GigaAM при VT_DEPLOY_PROFILE=cpu).
          </p>
          <button type="button" onClick={() => setManualTick((x) => x + 1)}>
            Обновить сейчас
          </button>
          <pre style={{ background: "#f6f8fa", padding: 12, overflow: "auto", maxHeight: 480 }}>
            {infraJson || "—"}
          </pre>
        </section>
      ) : null}
      {tab === "pipeline" ? (
        <section style={{ marginTop: 16 }}>
          <p style={{ fontSize: "0.85rem", color: "#555" }}>
            Снимок эффективной конфигурации этапов (YAML + переменные окружения), без секретов.
            Помогает отличить «этап выключен в конфиге» от «задача ещё в очереди». Автообновление с
            джиттером и backoff, реже в фоновой вкладке браузера.
          </p>
          <button type="button" onClick={() => setManualTick((x) => x + 1)}>
            Обновить сейчас
          </button>
          <pre style={{ background: "#f6f8fa", padding: 12, overflow: "auto", maxHeight: 520 }}>
            {pipelineJson || "—"}
          </pre>
        </section>
      ) : null}
      {tab === "pipeline_events" ? (
        <section style={{ marginTop: 16 }}>
          <p style={{ fontSize: "0.85rem", color: "#555" }}>
            Техническая лента этапов (ASR, диаризация, embeddings) без текста разговоров. Список
            обновляется только по кнопке ниже. Опционально включите <strong>Long poll</strong> —
            длинные запросы к <code>/admin/api/v1/pipeline-events/wait</code> (без периодического
            короткого поллинга).
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 8 }}>
            <button type="button" onClick={() => void loadPipelineEvents()}>
              Загрузить / обновить ленту
            </button>
            <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={pipelineEventsLive}
                onChange={(e) => setPipelineEventsLive(e.target.checked)}
              />
              Следить (long poll)
            </label>
          </div>
          <pre style={{ background: "#f6f8fa", padding: 12, overflow: "auto", maxHeight: 480 }}>
            {pipelineEventsJson || "—"}
          </pre>
        </section>
      ) : null}
      {tab === "tools" ? (
        <section style={{ marginTop: 16 }}>
          <button type="button" onClick={loadTools}>
            Загрузить ссылки
          </button>
          <pre style={{ background: "#f6f8fa", padding: 12, overflow: "auto", maxHeight: 200 }}>
            {toolsJson || "—"}
          </pre>
          <p style={{ fontSize: "0.9rem" }}>
            Ссылки открывайте вручную в новой вкладке (значения из конфигурации Admin API).
          </p>
        </section>
      ) : null}
      {tab === "audit" ? (
        <section style={{ marginTop: 16 }}>
          <p style={{ fontSize: "0.85rem", color: "#555" }}>
            Последние события аудита (просмотры карточек и мутации пайплайна). Автообновление с
            джиттером и backoff; в фоновой вкладке браузера — реже.
          </p>
          <button type="button" onClick={() => setManualTick((x) => x + 1)}>
            Обновить сейчас
          </button>
          <pre style={{ background: "#f6f8fa", padding: 12, overflow: "auto", maxHeight: 480 }}>
            {auditJson || "—"}
          </pre>
        </section>
      ) : null}
      <p style={{ marginTop: 24, fontSize: "0.8rem", color: "#666" }}>
        Admin API: <code>{adminApiBase()}</code>
      </p>
    </div>
  );
}
