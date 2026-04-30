import { loadSettings, updateSettings } from "../settings/storage";

function base64UrlEncode(bytes: ArrayBuffer): string {
  const u8 = new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]!);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** RFC 7636 PKCE pair for extension OAuth (C7.3). Exported for unit tests. */
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

/** Silent-step failures that should fall through to interactive OAuth without noisy UI. */
function isBenignSilentOAuthError(oauthError: string | null, chromeError: string | undefined): boolean {
  const blob = `${oauthError ?? ""} ${chromeError ?? ""}`.toLowerCase();
  if (
    blob.includes("login_required") ||
    blob.includes("interaction_required") ||
    blob.includes("consent_required") ||
    blob.includes("account_selection_required") ||
    blob.includes("invalid_grant") ||
    blob.includes("access_denied")
  ) {
    return true;
  }
  if (
    blob.includes("authorization page could not be loaded") ||
    blob.includes("redirect_uri_mismatch") ||
    blob.includes("user did not approve") ||
    blob.includes("canceled") ||
    blob.includes("cancelled")
  ) {
    return true;
  }
  return false;
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

async function fetchExtensionAuthorizeUrl(
  base: string,
  provider: "google" | "yandex",
  redirectUri: string,
  codeChallenge: string,
  uxMode: "silent" | "interactive",
  accountPrompt: "normal" | "force"
): Promise<string> {
  const params = new URLSearchParams({
    redirect_uri: redirectUri,
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    ux_mode: uxMode,
    account_prompt: accountPrompt,
  });
  const url = `${base}/api/auth/${provider}/extension/start?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`extension/start failed: ${res.status} ${text}`);
  }
  const data = (await res.json()) as { auth_url?: string };
  const authUrl = data.auth_url;
  if (!authUrl) throw new Error("extension/start missing auth_url");
  return authUrl;
}

async function finalizeExtensionLogin(
  base: string,
  provider: "google" | "yandex",
  code: string,
  codeVerifier: string,
  state: string
): Promise<void> {
  const qs = new URLSearchParams({
    code,
    code_verifier: codeVerifier,
    state,
  }).toString();
  const finalizeUrl = `${base}/api/auth/${provider}/extension/finalize?${qs}`;
  const finRes = await fetch(finalizeUrl, { method: "POST" });
  if (!finRes.ok) {
    const text = await finRes.text().catch(() => "");
    throw new Error(`Finalize failed: ${finRes.status} ${text}`);
  }
  const data = (await finRes.json()) as { access_token?: string };
  const token = data.access_token;
  if (!token) throw new Error("Finalize did not return access_token");
  await updateSettings({ accessToken: token });
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

async function runExtensionOAuthAttempt(
  base: string,
  provider: "google" | "yandex",
  redirectUri: string,
  uxMode: "silent" | "interactive",
  accountPrompt: "normal" | "force"
): Promise<void> {
  const { verifier, challenge } = await createPkcePair();
  const authUrl = await fetchExtensionAuthorizeUrl(base, provider, redirectUri, challenge, uxMode, accountPrompt);
  const interactive = uxMode !== "silent";
  const { responseUrl, chromeError } = await launchWebAuthFlowAsync(authUrl, interactive);
  if (chromeError) {
    throw new Error(chromeError);
  }
  if (!responseUrl) {
    throw new Error("OAuth failed: no redirect URL");
  }
  const parsed = parseOAuthRedirect(responseUrl);
  if (parsed.error && !parsed.code) {
    throw new Error(
      parsed.errorDescription ? `${parsed.error}: ${parsed.errorDescription}` : `OAuth error: ${parsed.error}`
    );
  }
  if (!parsed.code || !parsed.state) {
    throw new Error("OAuth completed but authorization code or state is missing");
  }
  await finalizeExtensionLogin(base, provider, parsed.code, verifier, parsed.state);
}

/**
 * OAuth2 login for the extension (B2.0 hybrid + C7.3 PKCE):
 * 1) optional silent attempt via server-built authorize URL;
 * 2) interactive fallback.
 * Shift+click (`force: true`) skips (1) and uses interactive flow with stronger account-picker hints.
 */
export function startOAuthLogin(
  serverUrl: string,
  provider: "google" | "yandex",
  onDone?: (err: string | null) => void,
  opts?: { force?: boolean }
): void {
  const base = serverUrl.replace(/\/+$/, "");
  const redirectUri = chrome.identity.getRedirectURL("oauth2");
  const forcePicker = opts?.force === true;

  (async () => {
    if (!forcePicker) {
      const current = await loadSettings();
      const token = (current.accessToken ?? "").trim();
      if (token) {
        const v = await verifyBackendSession(base, token);
        if (v.status === "ok") {
          onDone?.(null);
          return;
        }
        if (v.status === "unauthorized") {
          await updateSettings({ accessToken: null });
        }
      }
    }

    try {
      if (forcePicker) {
        await runExtensionOAuthAttempt(base, provider, redirectUri, "interactive", "force");
        onDone?.(null);
        return;
      }

      try {
        await runExtensionOAuthAttempt(base, provider, redirectUri, "silent", "normal");
        onDone?.(null);
        return;
      } catch (silentErr) {
        const msg = silentErr instanceof Error ? silentErr.message : String(silentErr);
        if (!isBenignSilentOAuthError(msg, undefined)) {
          console.info("[oauth] Silent step note (continuing with interactive):", msg);
        }
      }

      await runExtensionOAuthAttempt(base, provider, redirectUri, "interactive", "normal");
      onDone?.(null);
    } catch (e) {
      console.error("OAuth error:", e);
      onDone?.(e instanceof Error ? e.message : String(e));
    }
  })().catch((e) => {
    console.error("OAuth start error:", e);
    onDone?.(e instanceof Error ? e.message : String(e));
  });
}

export function registerOAuthMessageListener(): void {
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "oauth_token" && typeof message.accessToken === "string") {
      void updateSettings({ accessToken: message.accessToken }).then(() => {
        sendResponse({ ok: true });
      });
      return true;
    }
    return false;
  });
}
