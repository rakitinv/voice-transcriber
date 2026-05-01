# Приёмка Phase B (ручный чеклист + автотесты)

**Канон:** [ROADMAP.md](./ROADMAP.md) (Phase B), [WEBSOCKET.md](./WEBSOCKET.md), [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md), [TECHNICAL_SPECIFICATION.md §8](./TECHNICAL_SPECIFICATION.md).

**Стек:** API + worker + Postgres + Redis + MinIO ([docker/README.md](../docker/README.md)); Chromium (Chrome / Edge) для расширения.

**Автотесты расширения (без браузера):** каталог `browser-extension/`, команда `npm run test` — см. [TESTING.md](./TESTING.md).

Отметьте пункты после проверки.

---

## 1. Сервисы и аутентификация

- [ ] **API** отвечает (`GET …/health` или эквивалент), порт согласован с `Server URL` в расширении.
- [ ] **JWT** валиден: в Web UI или расширении выполнен вход; `GET /api/auth/me` с тем же токеном не даёт **401**.

---

## 2. WebSocket realtime (backend + Web UI или CLI)

- [ ] Создан разговор (`POST /api/conversations`), к разговору подключаются **`/ws/audio/{id}`** и при необходимости **`/ws/transcript/{id}`** с JWT (**`bearer.<JWT>`** в subprotocol или query по [WEBSOCKET.md](./WEBSOCKET.md)).
- [ ] После короткой записи и закрытия audio-WS сервер **не зависает** в «вечной записи»: при разрыве соединения выполняется **best-effort flush** буфера в `websocket_audio` (см. `server/app/api/websocket.py`). Для полной постановки **final** ASR по ТЗ §17 клиент дополнительно отправляет JSON **`finalize`** с **`finalize_id`** ([WEBSOCKET.md](./WEBSOCKET.md)).
- [ ] Частичный транскрипт доходит до клиента (канал transcript или ответы ASR в логах).

---

## 3. Расширение Chromium — popup (лёгкий вход)

- [ ] По клику на иконку открывается **короткий popup**: статус входа, **Settings**, кнопка **Open recording side panel**, **Upload audio file…** (отдельное окно).
- [ ] **OAuth:** первый вход без лишних ошибок при ожидаемом провале silent-шага; при необходимости — интерактивный вход (Google: `prompt=none` затем интерактив; Shift — форс-пикер).
- [ ] **Settings:** Server URL, источник аудио, chunk/TTL и т.д. сохраняются; логин Google/Yandex из модалки.
- [ ] После старта **микрофонной** записи из side panel popup может показывать предупреждение об активной offscreen-сессии; остановка — из меню иконки или side panel.

---

## 4. Расширение — Side Panel (основная поверхность)

- [ ] **Side panel** открывается (кнопка из popup, пункт меню иконки, или контекстное меню).
- [ ] **Start / Stop recording:** создаётся разговор, включается выбранный источник (**микрофон** через offscreen **или** **tab** из панели).
- [ ] **Live transcript** обновляется; кнопка **Reconnect transcript** пересоздаёт WS-подписку.
- [ ] **Refresh from server** подтягивает сегменты из **`GET /api/conversations/{id}`** (источник истины после ASR).
- [ ] **Export final (MD)** и **Export final (JSON)** вызывают **`GET /api/conversations/{id}/export?…&tier=final`** (канон §17.9 / §12; кнопки неактивны, пока **`tier=final`** не в статусе успеха на сервере).
- [ ] **Save live text** сохраняет накопленный в панели **live/fast** текст в локальный файл (не смешивать с каноническим export **final**).
- [ ] Закрытие **самой панели** не останавливает запись; повторное открытие показывает ту же сессию (badge на иконке при активной записи).

---

## 5. Контекстное меню иконки расширения (`action`)

- [ ] **Start recording…** — открывает side panel у последнего сфокусированного окна и инициирует старт (идемпотентно: при уже активной записи пункт **disabled**).
- [ ] **Open recording side panel** — только открытие панели.
- [ ] **Upload audio file…** — окно загрузки.
- [ ] **Open settings (popup)…** — открывает popup (требуется `default_popup` в manifest; жест пользователя — клик по меню).
- [ ] **Stop recording (microphone)** — **enabled** только при активной **offscreen** микрофонной записи; выполняет безопасную остановку.

---

## 6. Жизненный цикл и хранилище (B2.8 / persist)

- [ ] При **tab capture** закрытие **захваченной вкладки** останавливает запись и очищает сессию в `chrome.storage`.
- [ ] Закрытие **окна браузера**, в котором шла offscreen-микрофонная запись с привязкой `windowId`, инициирует остановку через service worker.
- [ ] **Миграция** со старых ключей `vtRecordingActive` / `vtRecordingConversationId` на **`vtRecordingSession`** при чтении сессии (проверяется логикой `readRecordingSession`; регрессия — автотест `sessionPersist.test.ts`).

### Известные ограничения Phase B (зафиксировать при приёмке)

- [ ] **Полный сценарий §17:** клиент расширения при остановке записи должен отправлять **`finalize`** (см. [WEBSOCKET.md](./WEBSOCKET.md)); без этого **final** ASR на сервере может не поставиться (останется только flush при закрытии WS и live **fast**).
- [ ] **Несколько вкладок-контекстов** с отдельными «чипами» в UI и капом превью на вкладку ([BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md) §3) **не входят** в минимальный объём Phase B; активна **одна** запись на профиль с полями `windowId` / `capturedTabId` в `RecordingSessionV1`.

---

## 7. Автотесты (обязательный минимум перед «Phase B закрыта»)

Из корня репозитория:

```bash
cd browser-extension && npm ci && npm run test && npm run build
```

Из корня сервера (без тяжёлого ASR при необходимости):

```bash
cd server && poetry run pytest tests/unit/ -v
```

При наличии стека и JWT — e2e Phase A как регрессия REST (см. [TESTING.md](./TESTING.md)).

---

**Дата прохождения:** ___________  
**Подпись / примечания:** ___________
