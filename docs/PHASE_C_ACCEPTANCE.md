# Приёмка Phase C — блок C7 + родительский C1

**Назначение:** зафиксированный план проверки перед закрытием **родительского C1** (post-hoc diarization + серверный автозапуск в pipeline) и регрессии **C7.x** (OAuth, refresh, PKCE/state расширения, слияние провайдеров в Web UI, политика JWT для WebSocket в prod).

**Канон:** [ROADMAP.md](./ROADMAP.md), [AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md), [DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md), [WEBSOCKET.md](./WEBSOCKET.md), [docker/README.md](../docker/README.md).

**Стек:** API + основной Celery worker + Postgres + Redis + MinIO; для C1 — профиль **`diarization`** (`diarization-worker` или `diarization-worker-gpu`), см. docker/README.

---

## План (порядок работ в следующей сессии)

1. **C7 — идентичность и сессия** (Web UI + при необходимости расширение): вход Google/Yandex, получение `access_token` + `refresh_token`, **`POST /api/auth/refresh`**, повтор запросов после истечения access JWT.
2. **C7 — расширение:** OAuth через **`GET /api/auth/{provider}/extension/start`** → redirect → **`POST .../extension/finalize`**; сессия сохраняется; при 401 — обновление через refresh (если реализовано в клиенте).
3. **C7 — слияние провайдеров (Web UI):** Settings → привязка второго провайдера, конфликт **`409`/redirect с `reason`** — по [AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md).
4. **C7.5 — WebSocket (prod-профиль):** при `VT_ENVIRONMENT=production` токен только **`Sec-WebSocket-Protocol: bearer.<JWT>`**; query при необходимости только с явным override — см. `WEBSOCKET.md`.
5. **C1 — пайплайн diarization:** `configs/diarization.yaml` → **`enabled: true`**, поднят **`docker compose --profile diarization`**; загрузка файла → успешный ASR → в очереди **`diarization`** выполняется задача → активный транскрипт **`asr_diarized`** после success; с **`enabled: false`** автопостановки нет.
6. **C1 — ручные действия:** **Diarize again** и **Transcribe again** — новые ревизии и корректный promote только при success (см. [DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md) §5).

Отметьте пункты после проверки.

---

## Чеклист C7 (OAuth, refresh, слияние, WS)

- [ ] Web UI: вход провайдером, редирект с фрагментом токенов; **`GET /api/auth/me`** с Bearer не даёт **401**.
- [ ] Истечение/ротация: **`POST /api/auth/refresh`** с `refresh_token` возвращает новую пару; старый refresh при ротации недействителен (ожидаемое поведение).
- [ ] Расширение: успешный вход и доступ к API с выданными токенами (см. [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md)).
- [ ] Web UI Settings: привязка провайдера (**Link**), список **`GET /api/settings/oauth-identities`** соответствует ожиданиям.
- [ ] (Если поднимаете prod-режим) WebSocket: подключение только с subprotocol **`bearer.<JWT>`** без query-токена — по документации.

---

## Чеклист C1 (post-hoc + автозапуск в pipeline)

- [ ] Профиль **`diarization`**: воркер слушает очередь **`diarization`**, в логах нет постоянных ошибок импорта задач (**`VT_CELERY_ENABLE_DIARIZATION=1`** на образе diarization-worker).
- [ ] После **upload** (или **retranscribe**) при **`diarization.enabled: true`** задача diarization ставится и завершается; в UI/API активная версия — с спикерами (**`asr_diarized`**) при успехе.
- [ ] При **`enabled: false`** в **`configs/diarization.yaml`** после ASR задача diarization **не** ставится автоматически.
- [ ] **Diarize again** (`POST …/diarize`) с подтверждением в UI создаёт новую ревизию; при ошибке активная версия не ломается.

---

## Автотесты (можно гонять без ручного прохода чеклиста)

| Область | Команда / файл | Условия |
|--------|----------------|---------|
| Юнит сервера | `cd server && poetry run pytest tests/unit/ -v` | Без Docker; для быстрого прогона без скачивания моделей ASR: **`VT_SKIP_ASR_INFERENCE=1`** (см. [TESTING.md](./TESTING.md)) |
| WS auth (unit) | включён в `tests/unit/` (`test_ws_auth.py`) | Без Docker |
| Diarization prefs | `tests/unit/test_diarization_prefs.py` | Без Docker |
| Расширение (Vitest) | `cd browser-extension && npm ci && npm run test` | Node |
| E2E Phase A | `pytest tests/integration/test_phase_a_upload_export_e2e.py -m e2e` | `VT_E2E_BASE_URL`, `VT_E2E_TOKEN`, поднятый стек |
| Audio acceptance | см. [TESTING.md](./TESTING.md) § «Сводный отчёт», `test_audio_acceptance_report.py` | `VT_E2E_*`, опционально файлы |

Интеграционные тесты с **`VT_E2E_*`** без поднятого API помечаются **skipped**, не failure.

---

**Дата подготовки чеклиста:** 2026-04-30  
**Ручная приёмка:** отметьте дату и подпись после прохождения чеклистов выше.
