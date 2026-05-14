/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Admin API base (Bearer calls). */
  readonly VITE_ADMIN_API_BASE_URL: string;
  /** Product API base for OAuth start + POST /api/auth/refresh (browser). */
  readonly VITE_PUBLIC_API_BASE_URL: string;
  /**
   * Origin of this admin SPA as seen in the browser (must match API ``VT_ADMIN_WEBUI_ORIGIN``).
   * If unset, ``window.location.origin`` is used (OK for local Vite; set explicitly in Docker build).
   */
  readonly VITE_ADMIN_WEBUI_SELF_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
