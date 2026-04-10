import { apiBaseUrlFromEnv } from "../api/apiBase";
import { api } from "../api/client";

/** OAuth login: redirect to backend auth URL (Google/Yandex). */
export function getLoginUrl(provider: "google" | "yandex"): string {
  return `${apiBaseUrlFromEnv()}/auth/${provider}`;
}

export function loginWithGoogle(): void {
  window.location.href = getLoginUrl("google");
}

export function loginWithYandex(): void {
  window.location.href = getLoginUrl("yandex");
}

export function logout(): void {
  localStorage.removeItem("access_token");
  delete api.defaults.headers.common.Authorization;
}
