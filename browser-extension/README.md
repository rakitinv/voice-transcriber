## Browser Extension Skeleton (`browser-extension/`)

This directory contains the **Chromium browser extension** skeleton for realtime recording and transcription.

### Planned responsibilities

- Start / stop recording.
- Live transcript display (via backend WebSocket).
- Transcript download and LLM summary trigger.
- Settings panel:
  - Server URL and OAuth login flow.
  - Audio source selection (microphone, tab audio, system audio).
  - Chunk size and realtime mode selection.
  - Language mode (manual / auto-detect).
  - TTL and max conversation duration.

### Planned layout

- `src/`
  - `background/` – Background service worker, connection to backend.
  - `content/` – Optional content scripts (e.g. UI overlays).
  - `popup/` – Popup UI for recording and settings.
  - `types/` – Shared types.

Only manifest and structural stubs should be placed here at this stage.

