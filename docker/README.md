# Docker deployment – Voice Transcriber

Run the full speech transcription stack locally with Docker Compose.

## Services

| Service  | Port(s)      | Description        |
|----------|--------------|--------------------|
| **api**  | 8000         | FastAPI backend    |
| **webui**| 3000         | React frontend     |
| **worker** | —         | Celery worker (ASR, diarization, LLM, cleanup) |
| **postgres** | 5432     | PostgreSQL 16      |
| **redis**  | 6379       | Redis 7            |
| **minio**  | 9000, 9001  | MinIO (S3-compatible storage and console) |

## Quick start

From the **repository root** (parent of `docker/`):

```bash
cd docker
docker compose up --build
```

- **Web UI:** http://localhost:3000  
- **API:** http://localhost:8000  
- **API health:** http://localhost:8000/health  
- **MinIO console:** http://localhost:9001 (minioadmin / minioadmin)

## Configuration

The API and worker use environment variables set in `docker-compose.yml`. You can override them without changing YAML configs:

- `VT_DATABASE_URL` – PostgreSQL connection string  
- `VT_REDIS_URL` – Redis connection string  
- `VT_S3_ENDPOINT`, `VT_S3_BUCKET`, `VT_S3_ACCESS_KEY`, `VT_S3_SECRET_KEY` – MinIO/S3  
- `VT_ENVIRONMENT` – e.g. `production`

The `configs/` directory is mounted read-only into the API and worker. Ensure `configs/server.yaml` exists; Docker env vars override matching values from that file.

## First-time setup

### MinIO bucket

The app expects a bucket named `voice-transcriber`. Create it once via the MinIO console:

1. Open http://localhost:9001 and log in (minioadmin / minioadmin).  
2. Create a bucket named `voice-transcriber`.

### Database migrations

If the server uses Alembic, run migrations after Postgres is up:

```bash
docker compose run --rm api alembic -c /app/server/alembic.ini upgrade head
```

Adjust the path to `alembic.ini` if your layout differs.

## Building the Web UI for a different API URL

To point the frontend at another API (e.g. in production), pass the URL at build time:

```yaml
# In docker-compose.yml, under webui build args:
args:
  VITE_API_BASE_URL: https://api.example.com
```

Then rebuild the webui image: `docker compose build webui`.

## Volumes

- `postgres-data` – PostgreSQL data  
- `redis-data` – Redis data  
- `minio-data` – MinIO object storage  

Server logs are written to `../server/logs` (mounted from the host).

## Commands

```bash
# Start in background
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down

# Stop and remove volumes
docker compose down -v
```
