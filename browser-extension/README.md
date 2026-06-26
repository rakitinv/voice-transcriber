## Browser extension (`browser-extension/`)

Chromium (MV3) extension: **shell popup** (login, settings, open side panel, upload window), **side panel** (start/stop recording, live transcript, export), **offscreen** document for microphone capture, **background** service worker (OAuth routing, context menus, session persist).

Канон UX: [`docs/BROWSER_EXTENSION_UI.md`](../docs/BROWSER_EXTENSION_UI.md). Приёмка Phase B: [`docs/PHASE_B_ACCEPTANCE.md`](../docs/PHASE_B_ACCEPTANCE.md).

Параметры **diarization** (в т.ч. повторный ASR по turn vs только спикеры) и **повторный batch ASR** по разговору настраиваются и запускаются из **Web UI** сервера, не из расширения; см. [DIARIZATION_ALIGNMENT_VERSIONING.md](../docs/DIARIZATION_ALIGNMENT_VERSIONING.md) и §10 ТЗ.

### Commands

```bash
npm ci
# Prod (optional): VITE_DEFAULT_SERVER_URL=https://voicer.example.com npm run build
npm run build    # production bundle → dist/
npm run test     # Vitest unit tests (no browser)
npm run dev      # Vite dev server
```

Load **unpacked** extension from `browser-extension/dist/` in `chrome://extensions` (Developer mode).

### Layout (`src/`)

- `background.ts` — conversations API from SW, offscreen start/stop, `chrome.contextMenus`, `tabs` / `windows` lifecycle.
- `popup/` — shell UI (`App` `variant="shell"`) and shared `App` for recording mode.
- `sidepanel/` — entry that mounts `App` with `layout="sidepanel"` (recording UI).
- `offscreen/`, `upload/` — separate extension pages.
- `recorder/`, `websocket/`, `api/`, `auth/`, `settings/`, `recording/` — shared modules.
