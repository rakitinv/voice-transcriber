## Server (Backend) Skeleton

This directory contains the **backend skeleton** for the voice transcription system.

### Tech stack

- **Language**: Python
- **Web framework**: FastAPI
- **Task queue**: Celery
- **Broker**: Redis
- **Database**: PostgreSQL
- **Object storage**: S3-compatible (MinIO)

### Planned responsibilities

- OAuth2 authentication (Google, Yandex).
- Realtime transcription via WebSocket.
- Batch transcription via file upload.
- Multi-thread / chunked transcription for long audio.
- Speaker diarization (post-processing only).
- LLM-based conversation summaries.
- Transcript and embeddings search (PostgreSQL full-text + semantic).
- Per-user encrypted storage and TTL cleanup.

### Current layout (skeleton)

- `app/` – FastAPI app package and API routers.
- `workers/` – Celery workers for ASR, diarization, and LLM.
- `config/` – Server-side configuration loading and models.
- `core/` – Security, database, S3, logging, and utilities.
- `plugins/` – Pluggable ASR, diarization, and LLM providers.
- `migrations/` – Database migrations (e.g. Alembic).
- `tests/` – Backend tests (to be added later).

At this stage, only **minimal stubs** and module placeholders exist; application logic is not yet implemented.

