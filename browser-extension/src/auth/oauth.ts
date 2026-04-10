import { updateSettings } from "../settings/storage";

/**
 * Start OAuth2 login flow by opening backend auth page in a new tab.
 *
 * This is a simplified helper; the full flow should:
 * - redirect to backend /api/auth/{provider}
 * - on completion, backend redirects to a page that can send the access token
 *   back to the extension via chrome.runtime.sendMessage or URL fragment.
 */
export function startOAuthLogin(serverUrl: string, provider: "google" | "yandex"): void {
  const url = `${serverUrl.replace(/\/+$/, "")}/api/auth/${provider}`;
  chrome.tabs.create({ url });
}

/**
 * Handle messages from OAuth completion page.
 *
 * Expected payload shape:
 * { type: "oauth_token", accessToken: "..." }
 */
export function registerOAuthMessageListener(): void {
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "oauth_token" && typeof message.accessToken === "string") {
      void updateSettings({ accessToken: message.accessToken }).then(() => {
        sendResponse({ ok: true });
      });
      return true; // async response
    }
    return false;
  });
}

