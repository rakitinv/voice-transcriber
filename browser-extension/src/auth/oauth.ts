import { loadSettings, updateSettings, type ExtensionSettings } from "../settings/storage";

function base64UrlEncode(bytes: ArrayBuffer): string {
  const u8 = new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]!);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** RFC 7636 PKCE pair. Exported for unit tests only (extension login uses Web UI–aligned OAuth). */
export async function createPkcePair(): Promise<{ verifier: string; challenge: string }> {
  const verifierBytes = new Uint8Array(32);
  crypto.getRandomValues(verifierBytes);
  const verifier = base64UrlEncode(verifierBytes.buffer);
  const challengeBuf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const challenge = base64UrlEncode(challengeBuf);
  return { verifier, challenge };
}

/** Parse OAuth redirect: code, state, error may live in query or in URL fragment. */
export function parseOAuthRedirect(finalUrl: string): {
  code: string | null;
  state: string | null;
  error: string | null;
  errorDescription: string | null;
} {
  try {
    const u = new URL(finalUrl);
    const fromSearch = (key: string) => u.searchParams.get(key);
    let code = fromSearch("code");
    let state = fromSearch("state");
    let error = fromSearch("error");
    let errorDescription = fromSearch("error_description");

    const hash = u.hash?.startsWith("#") ? u.hash.slice(1) : (u.hash ?? "");
    if (hash) {
      const hp = new URLSearchParams(hash);
      if (!code) code = hp.get("code");
      if (!state) state = hp.get("state");
      if (!error) error = hp.get("error");
      if (!errorDescription) errorDescription = hp.get("error_description");
    }

    return {
      code: code && code.trim() ? code.trim() : null,
      state: state && state.trim() ? state.trim() : null,
      error: error && error.trim() ? error.trim() : null,
      errorDescription: errorDescription && errorDescription.trim() ? errorDescription.trim() : null,
    };
  } catch {
    return { code: null, state: null, error: null, errorDescription: null };
  }
}

/**
 * Service tokens returned by backend after Web OAuth when `client=extension`
 * (fragment on `chrome.identity` redirect URL — same shape as Web UI `/login#`).
 */
export function parseServiceTokensFromOAuthRedirect(finalUrl: string): {
  accessToken: string | null;
  refreshToken: string | null;
  error: string | null;
  errorDescription: string | null;
} {
  try {
    const u = new URL(finalUrl);
    const hash = u.hash?.startsWith("#") ? u.hash.slice(1) : (u.hash ?? "");
    const pick = (src: URLSearchParams, key: string) => {
      const v = src.get(key);
      return v && v.trim() ? v.trim() : null;
    };
    if (hash) {
      const hp = new URLSearchParams(hash);
      return {
        accessToken: pick(hp, "access_token"),
        refreshToken: pick(hp, "refresh_token"),
        error: pick(hp, "error"),
        errorDescription: pick(hp, "error_description"),
      };
    }
    return {
      accessToken: pick(u.searchParams, "access_token"),
      refreshToken: pick(u.searchParams, "refresh_token"),
      error: pick(u.searchParams, "error"),
      errorDescription: pick(u.searchParams, "error_description"),
    };
  } catch {
    return { accessToken: null, refreshToken: null, error: null, errorDescription: null };
  }
}

function launchWebAuthFlowAsync(url: string, interactive: boolean): Promise<{ responseUrl?: string; chromeError?: string }> {
  return new Promise((resolve) => {
    try {
      chrome.identity.launchWebAuthFlow({ url, interactive }, (responseUrl) => {
        const chromeError = chrome.runtime.lastError?.message;
        resolve({ responseUrl: responseUrl ?? undefined, chromeError });
      });
    } catch (e) {
      resolve({ chromeError: e instanceof Error ? e.message : String(e) });
    }
  });
}

async function tryRefreshViaApi(
  serverUrl: string,
  refreshToken: string
): Promise<{ accessToken: string; refreshToken: string } | null> {
  const base = serverUrl.replace(/\/+$/, "");
  const res = await fetch(`${base}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) return null;
  const data = (await res.json()) as { access_token?: string; refresh_token?: string };
  if (!data.access_token || !data.refresh_token) return null;
  return { accessToken: data.access_token, refreshToken: data.refresh_token };
}

export type BackendSessionVerifyResult =
  | { status: "ok" }
  | { status: "unauthorized"; httpStatus: number }
  | { status: "network" };

export async function verifyBackendSession(serverUrl: string, token: string): Promise<BackendSessionVerifyResult> {
  const url = `${serverUrl.replace(/\/+$/, "")}/api/auth/me`;
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), 2500);
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
      signal: ac.signal,
    });
    if (res.status === 401 || res.status === 403) return { status: "unauthorized", httpStatus: res.status };
    if (!res.ok) return { status: "network" };
    return { status: "ok" };
  } catch {
    return { status: "network" };
  } finally {
    clearTimeout(t);
  }
}

export type ExtensionSessionResult =
  | { status: "ok"; settings: ExtensionSettings }
  | { status: "unauthorized" }
  | { status: "network" };

/** Clears service tokens (local); next API calls require signing in again. */
export async function clearExtensionAuth(): Promise<ExtensionSettings> {
  return updateSettings({ accessToken: null, refreshToken: null });
}

export async function verifyOrRefreshSession(settings: ExtensionSettings): Promise<ExtensionSessionResult> {
  const token = (settings.accessToken ?? "").trim();
  const rt = (settings.refreshToken ?? "").trim();

  if (!token) {
    if (rt) {
      const pair = await tryRefreshViaApi(settings.serverUrl, rt);
      if (pair) {
        const next = await updateSettings({
          accessToken: pair.accessToken,
          refreshToken: pair.refreshToken,
        });
        const v = await verifyBackendSession(next.serverUrl, pair.accessToken);
        if (v.status === "ok") return { status: "ok", settings: next };
      }
    }
    return { status: "unauthorized" };
  }

  const v = await verifyBackendSession(settings.serverUrl, token);
  if (v.status === "ok") return { status: "ok", settings };
  if (v.status === "unauthorized" && rt) {
    const pair = await tryRefreshViaApi(settings.serverUrl, rt);
    if (pair) {
      const next = await updateSettings({
        accessToken: pair.accessToken,
        refreshToken: pair.refreshToken,
      });
      const v2 = await verifyBackendSession(next.serverUrl, pair.accessToken);
      if (v2.status === "ok") return { status: "ok", settings: next };
    }
    await updateSettings({ accessToken: null, refreshToken: null });
    return { status: "unauthorized" };
  }
  if (v.status === "unauthorized") {
    await updateSettings({ accessToken: null, refreshToken: null });
    return { status: "unauthorized" };
  }
  return { status: "network" };
}

/** Persisted so popup/side panel can show busy state after reopen while OAuth runs in the service worker. */
export const OAUTH_FLOW_STORAGE_KEY = "voiceTranscriberOAuthFlow";

export type OAuthFlowSnap = { pending: boolean; lastError: string | null };

export async function readOAuthFlowSnap(): Promise<OAuthFlowSnap | null> {
  return new Promise((resolve) => {
    chrome.storage.local.get([OAUTH_FLOW_STORAGE_KEY], (result) => {
      const raw = result[OAUTH_FLOW_STORAGE_KEY];
      if (!raw || typeof raw !== "object") resolve(null);
      else resolve(raw as OAuthFlowSnap);
    });
  });
}

export async function writeOAuthFlowSnap(snap: OAuthFlowSnap): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.storage.local.set({ [OAUTH_FLOW_STORAGE_KEY]: snap }, () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve();
    });
  });
}

async function fetchWebAlignedExtensionAuthorizeUrl(
  base: string,
  provider: "google" | "yandex",
  redirectUri: string
): Promise<string> {
  const qs = new URLSearchParams({ client: "extension", next: redirectUri });
  const url = `${base}/api/auth/${provider}/extension/authorize-url?${qs.toString()}`;
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`authorize-url failed: ${res.status} ${text}`);
  }
  const data = (await res.json()) as { auth_url?: string };
  const authUrl = data.auth_url;
  if (!authUrl) throw new Error("authorize-url missing auth_url");
  return authUrl;
}

/**
 * OAuth как у Web UI (`redirect_uri` = `/api/auth/{provider}/callback`), финальный редирект на `*.chromiumapp.org` с токенами.
 * Вызывайте из **service worker** (`background`), чтобы `launchWebAuthFlow` не обрывался при закрытии popup.
 */
export async function runOAuthLoginAsync(
  serverUrl: string,
  provider: "google" | "yandex"
): Promise<{ ok: true } | { ok: false; error: string }> {
  const base = serverUrl.replace(/\/+$/, "");
  const redirectUri = chrome.identity.getRedirectURL("oauth2");
  try {
    const authUrl = await fetchWebAlignedExtensionAuthorizeUrl(base, provider, redirectUri);
    const { responseUrl, chromeError } = await launchWebAuthFlowAsync(authUrl, true);
    if (chromeError) throw new Error(chromeError);
    if (!responseUrl) throw new Error("OAuth отменён или нет URL перенаправления");

    const parsed = parseServiceTokensFromOAuthRedirect(responseUrl);
    if (parsed.error) {
      throw new Error(
        parsed.errorDescription ? `${parsed.error}: ${parsed.errorDescription}` : `OAuth error: ${parsed.error}`
      );
    }
    if (!parsed.accessToken || !parsed.refreshToken) {
      throw new Error("OAuth завершён, но отсутствуют access_token или refresh_token");
    }
    await updateSettings({ accessToken: parsed.accessToken, refreshToken: parsed.refreshToken });
    return { ok: true };
  } catch (e) {
    console.error("OAuth error:", e);
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export function registerOAuthMessageListener(): void {
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "oauth_token" && typeof message.accessToken === "string") {
      void updateSettings({
        accessToken: message.accessToken,
        refreshToken:
          typeof message.refreshToken === "string" && message.refreshToken.trim()
            ? message.refreshToken.trim()
            : null,
      }).then(() => {
        sendResponse({ ok: true });
      });
      return true;
    }
    return false;
  });
}
