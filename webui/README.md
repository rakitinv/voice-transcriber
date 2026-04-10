## Web UI Skeleton (`webui/`)

This directory contains the **React + Vite + TypeScript** frontend skeleton.

### Planned responsibilities

- OAuth2 login (Google / Yandex) via backend.
- Conversation list, viewer, and search pages.
- Realtime transcript viewer (WebSocket).
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

