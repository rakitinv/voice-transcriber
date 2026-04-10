## Voice Transcriber – Project Skeleton

This repository contains the **skeleton** for a production-grade, open-source speech transcription system.  
The current state is focused on **project structure only** – core logic and implementations are intentionally omitted.

### High-level Architecture

- **Backend (`server/`)**: FastAPI API, Celery workers, Redis, PostgreSQL, MinIO-compatible S3, plugin architecture for ASR, diarization, and LLM providers.
- **Web UI (`webui/`)**: React + Vite + TypeScript single-page application.
- **Browser Extension (`browser-extension/`)**: Chromium extension for realtime recording and transcription.
- **CLI Client (`cli/` – planned)**: Command-line uploader for batch transcription.
- **Configs (`configs/`)**: YAML configuration files for server, ASR, LLM, limits.
- **Docker (`docker/`)**: `docker-compose` and service-level Dockerfiles for local deployment.
- **Docs (`docs/`)**: Additional architecture and integration documentation.

Implementation of actual business logic, models, and provider integrations will be added **on top of this skeleton**.

