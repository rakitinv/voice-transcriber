/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Prod API base URL baked in at `npm run build` (no trailing slash). */
  readonly VITE_DEFAULT_SERVER_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
