## Web UI Skeleton (`webui/`)

This directory contains the **React + Vite + TypeScript** frontend skeleton.

### Responsibilities (текущее и план)

- OAuth2 login (Google / Yandex) via backend.
- **Список разговоров:** просмотр, удаление, экспорт транскрипта, скачивание исходного аудио, **загрузка файла для обработки** (`POST /api/upload` — тот же контракт, что у будущего CLI `upload` и у `scripts/phase_a_upload_smoke.py`), а также **запись с микрофона** (MediaRecorder → по остановке тот же `POST /api/upload`, без realtime WS).
- Страница просмотра разговора, поиск, настройки.
- Realtime transcript viewer (WebSocket) — Phase B.
- Settings for ASR / LLM providers, chunking, TTL, and limits.
- Display of diarization, timestamps, and summaries.

### Planned layout

- `src/`
  - `pages/` – Route-level views (`Login`, `Conversations`, `ConversationViewer`, `Search`, `Settings`).
  - `components/` – Reusable UI components.
  - `hooks/` – Data fetching and WebSocket hooks.
  - `api/` – API client wrappers.
  - `config/` – Frontend configuration (runtime / env-based).
  - `types/` – Shared TypeScript types (transcripts, conversations, users).

Implementation is intentionally minimal and will be expanded later.

