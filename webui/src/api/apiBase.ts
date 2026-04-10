/**
 * FastAPI mounts routers under `/api`. Accept either `http://host:port` or
 * `http://host:port/api` in VITE_API_BASE_URL without duplicating `/api`.
 */
export function apiBaseUrlFromEnv(): string {
  const raw = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!raw) return "/api";
  const trimmed = raw.replace(/\/+$/, "");
  if (trimmed.endsWith("/api")) return trimmed;
  return `${trimmed}/api`;
}
