/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Admin API base (Bearer calls). */
  readonly VITE_ADMIN_API_BASE_URL: string;
  /** Product API base for OAuth start + POST /api/auth/refresh (browser). */
  readonly VITE_PUBLIC_API_BASE_URL: string;
  /**
   * Landing URL after OAuth (e.g. ``https://host/admin``). API allowlist uses origin only
   * (``VT_ADMIN_WEBUI_ORIGIN``). If unset, ``window.location`` + Vite ``base`` is used.
   */
  readonly VITE_ADMIN_WEBUI_SELF_URL: string;
  /** Vite public path prefix when SPA is not at site root (e.g. ``/admin/``). */
  readonly VITE_ADMIN_WEBUI_BASE_PATH?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
