# Приёмка Phase A (ручной чеклист)

**Канон сценария:** [TECHNICAL_SPECIFICATION.md §8](./TECHNICAL_SPECIFICATION.md) и [ROADMAP.md](./ROADMAP.md) (Phase A).

Стек: [docker/README.md](../docker/README.md) (`docker compose up` из каталога `docker/`) или эквивалентный локальный запуск API + worker + Postgres + Redis + MinIO.

Отметьте пункты после проверки.

## 1. Доступность сервисов

- [x] **API** отвечает: `GET http://localhost:8002/health` → `200`, тело со `status` (порт по умолчанию из `docker-compose`: **8002** → контейнер 8000).
- [x] **Web UI** открывается: `http://localhost:3002` (порт **3002** → контейнер 3000).
- [x] **Worker** в логах подписан на очереди (`asr`, …): `docker compose logs worker` (без постоянных traceback).

## 2. Аутентификация

- [x] Логин через провайдера (Google/Yandex) завершается редиректом в UI с токеном / сессией.
- [x] Запросы к API с `Authorization: Bearer <JWT>` (токен из `localStorage` → `access_token`) не дают **401** на `GET /api/auth/me`.

## 3. Пакетная загрузка и транскрипт (stub ASR допустим)

- [x] На странице **списка разговоров** кнопка загрузки отправляет файл; появляется новый разговор (или обновляется после обработки).
- [x] На странице **списка разговоров** запись с микрофона («Record from microphone» → «Stop & upload») формирует аудиофайл и отправляет его тем же **`POST /api/upload`**.
- [x] На странице **просмотра разговора** виден транскрипт (в т.ч. stub-текст Phase A, пока нет реального ASR).
- [x] **Экспорт** md/json работает (кнопка Download / экспорт из UI).

## 4. Список, поиск, лимиты

- [x] **Список** разговоров отображается.
- [x] **Поиск** (`/search`) с запросом возвращает релевантные фрагменты (fulltext).
- [x] **Настройки**: лимиты с сервера (`GET /api/settings/limits`) отображаются; поля пользователя согласованы с API.

## 5. CLI (опционально)

- [x] `transcriber me` с тем же JWT, что Web UI, успешен.
- [x] `transcriber upload` (или smoke-скрипт) даёт `conversation_id` и после обработки — непустой export.

## 6. Автоматический e2e (при наличии JWT)

См. [TESTING.md](./TESTING.md): `VT_E2E_BASE_URL`, `VT_E2E_TOKEN`, pytest.

---

**Дата прохождения:** 19.04.2026  
**Подпись / примечания:** Автотест из п.6 не выполнял
