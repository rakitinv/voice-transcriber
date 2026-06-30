# Приёмка C1.4 — идентификация и переименование спикеров

Чеклист для **S1–S3** ([SPEAKER_IDENTIFICATION.md](./SPEAKER_IDENTIFICATION.md)).

**Дата прогона:** 2026-06-30

---

## Автоматическая приёмка (рекомендуется)

Требуется Postgres (например compose на `127.0.0.1:5435`) и применённая миграция `speaker_labels_c14_013`:

```bash
cd server
set VT_DATABASE_URL=postgresql+psycopg2://voice:voice@127.0.0.1:5435/voice
set VT_S3_ENDPOINT=http://127.0.0.1:9012
set VT_S3_ACCESS_KEY=minioadmin
set VT_S3_SECRET_KEY=minioadmin
poetry run alembic upgrade head
poetry run pytest tests/integration/test_speaker_identification_acceptance.py tests/unit/test_speaker_labels.py tests/unit/test_speaker_identify_llm.py -v
```

Ожидание: **11 passed** (3 acceptance + 8 unit).

Против поднятого API в Docker (после `docker compose build api && docker compose up -d migrate api`):

```bash
set VT_E2E_BASE_URL=http://127.0.0.1:8002
set VT_E2E_TOKEN=<JWT из Web UI>
poetry run pytest tests/integration/test_speaker_identification_acceptance.py -v -m speaker_acceptance
```

---

## S1 — ручное переименование

| # | Шаг | Статус |
|---|-----|--------|
| 1 | После диаризации в `GET /api/conversations/{id}` сегменты содержат `speaker_id` | [x] автотест |
| 2 | `PATCH /api/conversations/{id}/speakers` с `SPEAKER_00` → «Иван» возвращает 200 | [x] автотест |
| 3 | Повторный `GET` — в `transcript[].speaker` отображается «Иван» | [x] автотест |
| 4 | `GET …/export?format=md` содержит `**Иван**`, не сырой `SPEAKER_00` | [x] автотест |
| 5 | `GET …/export?format=json` — `segments[].speaker_id` + `speaker`, `_meta.speaker_labels` | [x] автотест |
| 6 | Web UI: панель «Спикеры», inline rename | [ ] ручная |

---

## S2 — LLM-предложения

| # | Шаг | Статус |
|---|-----|--------|
| 1 | `speaker_identification.enabled` в `configs/llm.yaml` / env | [x] конфиг |
| 2 | После diarization в очередь `llm` ставится `identify_speakers` (если enabled) | [ ] ручная / worker |
| 3 | `POST …/speakers/identify` — 202 при включённом LLM | [ ] ручная |
| 4 | Предложения с `source=llm_suggested` в `GET …/speakers` | [x] автотест (seed + apply) |
| 5 | `POST …/speakers/apply-suggestions` обновляет отображение без rerun diarization | [x] автотест |
| 6 | UI: баннер, confidence, evidence, «Принять» | [ ] ручная |

---

## S3 — summary, auto_apply, embeddings

| # | Шаг | Статус |
|---|-----|--------|
| 1 | Rolling summary ставится **после** identify (цепочка в `schedule_post_diarization_pipeline`) | [x] код |
| 2 | Промпт summary учитывает блок «Участники» | [x] код + unit |
| 3 | `mode: auto_apply` + порог confidence | [x] код |
| 4 | Переиндексация embeddings при PATCH/apply rename | [x] код (`schedule_transcript_embedding`) |
| 5 | `GET /api/settings/limits` → `speaker_identification_enabled` | [x] автотест |

---

## Ручная приёмка Web UI (кратко)

1. Поднять стек: `docker compose up -d` (api, worker, worker с очередью `llm`, при diarization — `diarization-worker`).
2. `alembic upgrade head` (миграция `speaker_labels_c14_013`).
3. Загрузить аудио с ≥2 спикерами, дождаться diarization (`transcript_kind=asr_diarized`).
4. На странице разговора (tier **Final**): панель **Спикеры** → переименовать `SPEAKER_00` → «Иван» → **Сохранить**.
5. Убедиться, что в расшифровке и MD-экспорте везде «Иван».
6. (Опционально) Включить `speaker_identification.enabled: true`, перезапустить worker → **Определить имена (LLM)** или дождаться auto после diarization → **Принять** предложение.

---

## Результат прогона 2026-06-30

| Категория | Результат |
|-----------|-----------|
| Unit (`test_speaker_labels`, `test_speaker_identify_llm`) | 8/8 passed |
| API acceptance in-process | 3/3 passed |
| Миграция БД | `speaker_labels_c14_013` применена |
| Web UI / live LLM / diarization e2e | не прогонялись в этой сессии |

**Итог:** автоматическая приёмка **S1 + S2 (apply) + S3 (limits/flag)** пройдена. Для полного закрытия C1.4 остаётся ручная проверка UI и LLM identify на реальной записи с Ollama/vLLM.
