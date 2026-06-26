import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

/** Vite `base` must end with `/`. Default `/` — local dev and compose on :3003. Prod behind `/admin/`: `VITE_ADMIN_WEBUI_BASE_PATH=/admin/`. */
function viteBasePath(): string {
  const raw = (process.env.VITE_ADMIN_WEBUI_BASE_PATH ?? "/").trim();
  if (!raw || raw === "/") return "/";
  const withLeading = raw.startsWith("/") ? raw : `/${raw}`;
  return withLeading.endsWith("/") ? withLeading : `${withLeading}/`;
}

export default defineConfig({
  base: viteBasePath(),
  plugins: [react()],
  server: {
    port: 5174,
  },
});
