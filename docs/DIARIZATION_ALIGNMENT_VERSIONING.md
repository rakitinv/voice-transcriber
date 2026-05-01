# Diarization + Alignment + Версионирование транскриптов (Design Doc)

**Статус:** согласовано; **Phase C C1** (post-hoc diarization, versioning, rerun API/UI, автозапуск после успешного batch ASR при `diarization.enabled`, отдельный compose-воркер) — реализовано. **Alignment** (§4.2) остаётся вне MVP.  
**Дата:** 2026-04-20 (обновления по режимам merge и API — 2026-04-26); статус C1 — 2026-04-30  
**Контекст:** обсуждение требований diarization/alignment и история результатов транскрибации.

---

## 1. Цели

- Добавить **post-hoc diarization** (разметка спикеров) как **плагинный** этап, независимый от ASR-провайдера.
- Добавить **настраиваемую склейку** (merge) diarization-таймингов с текстом ASR в единый формат сегментов.
- Зафиксировать правило **истории транскриптов**: хранить *все попытки*, а пользователю отдавать *одну актуальную*.
- Поддержать **повторный запуск diarization** через отдельный endpoint и UI с подтверждением.

**Граница настроек:**

- **Включение этапа diarization в общем pipeline** (постановка задачи после успешного batch ASR при `upload`, `retranscribe` и т.п.) по-прежнему задаётся **только серверной конфигурацией** (`configs/diarization.yaml`: `enabled`, провайдер, воркер). В Web UI **нет** переключателя «всегда с диаризацией / без» в этом смысле.
- **Поведение внутри задачи diarization** (повторный ASR по коротким клипам на каждый turn pyannote **против** только расстановки спикеров по уже готовому тексту ASR): серверный дефолт — `configs/diarization.yaml` → `turn_level_retranscription`, опционально переопределяется при старте через **`VT_DIARIZATION_TURN_LEVEL_RETRANSCRIPTION`**. Пользователь может задать **своё** значение в Web UI (**Settings**), поля в `user.preferences` по аналогии с кастомным VAD; **расширение браузера эти поля не дублирует** (канон — Web UI).
- **Явные действия по разговору:** повтор **только diarization** — §5.2; повтор **полного batch ASR** по уже загруженному аудио — §5.3 (`POST …/retranscribe`, кнопка в Web UI).

Не цели (MVP):

- Real-time diarization в WebSocket потоке (пока только post-hoc).
- Word-level timestamps в публичном API (достаточно `speaker/start/end/text`).
- Forced alignment (WhisperX/MFA) — отдельная фаза после MVP merge.

---

## 2. Определения и контракты

### 2.1. Нормализованный формат сегментов

Минимальный контракт результата, возвращаемый API и используемый UI:

- `speaker: str`
- `start: float` (секунды)
- `end: float`
- `text: str`

Инварианты:

- Сегменты упорядочены по `start`.
- Для каждого сегмента выполняется `start <= end`.
- Число спикеров **не ограничено**; ограничения задаются настройками diarization-провайдера.

### 2.2. Diarization как отдельный этап

Diarization-провайдер получает **аудио** и возвращает speaker turns (тайминг + label).

- Не зависит от того, какой ASR использовался (whisper/faster-whisper/vosk/и т.д.).
- Может использовать дополнительные параметры (device, min/max speakers), но входной контракт — аудио.

### 2.3. Merge (склейка) diarization + ASR

Две реализованные стратегии (выбор — см. §4.1 и эффективное значение для пользователя):

1. **Только расстановка спикеров (рекомендуемый дефолт в YAML):** **segment-level assignment** — ASR segments с `(start,end,text)` не меняются; для каждого сегмента `speaker` по **max-overlap** с turn’ами diarization `(start,end,speaker)`.
2. **Turn-level re-ASR:** при наличии ASR-провайдера и `ffmpeg` на воркере — нарезка аудио по turn’ам pyannote и **повторный вызов ASR** на каждый клип; текст сегментов может отличаться от полного файла (границы turn, padding, короткий контекст).

Опционально (позже): разрезание сегментов по границам смены спикера, word-level.

### 2.4. Docker: CPU vs CUDA образы diarization-воркера

Сборка PyTorch для diarization разделена на два compose-сервиса (`diarization-worker` = CPU wheels по умолчанию, `diarization-worker-gpu` = CUDA, профиль `gpu`). Это **build-time** выбор (build-arg `DIARIZATION_TORCH`), а не переключение в `configs/diarization.yaml`. Параметр `device` в YAML задаёт, как inference использует уже установленный в образе стек.

Краткая инструкция по развёртыванию и смене варианта: [docker/README.md](../docker/README.md#diarization-cpu-vs-cuda-images).

---

## 3. Версионирование транскриптов (Scheme 2)

### 3.1. Проблема

- Нужны “перезапуски” (ASR/diarization/будущий alignment), аудит и защита от гонок.
- При повторной обработке пользователь должен видеть **только одну актуальную** версию, но история должна сохраняться.

### 3.2. Решение

Используем **версионирование** результатов и “активный указатель”:

- В таблице `transcripts` храним все версии:
  - `revision` — монотонный номер версии *в рамках одного conversation*
  - `kind` — этап результата (`asr`, `asr_diarized`, …)
  - `status` — `pending|running|success|failed`
  - `meta` — параметры провайдеров/окружения
  - `transcript_json`, `transcript_md`, `summary_md` — полезная нагрузка
- В `conversations` добавляем:
  - `active_transcript_id` — FK на “текущую опубликованную” версию.

Правило актуальности:

- API отдаёт **активный transcript** по `active_transcript_id`.
- “Promote” происходит **только** после `success`.
- Если попытка `failed`, активная версия **не меняется** (пользователь остаётся на предыдущей рабочей).

Выделение `revision`:

- В транзакции блокируем разговор (или его ряд) и создаём `next_revision = max(revision)+1`.
- Это предотвращает коллизии при параллельных задачах (batch + ручной rerun).

---

## 4. Конфигурация (настраиваемость и отключение)

### 4.1. Diarization

Отдельный конфиг `configs/diarization.yaml`:

- `enabled: bool` — глобальное включение/отключение
- `default_provider: str` — например `pyannote`
- `providers.<name>.enabled` — включение конкретного провайдера
- провайдер-специфичные поля (например device, model, hf token env, speaker limits)
- **offline/online модели**:
  - `offline_models: true|false` — если `true`, запрещены сетевые скачивания моделей (HF offline)
  - `model_cache_dir: <path>` — каталог кэша моделей (в Docker рекомендуется volume)
- **`turn_level_retranscription: bool`** — если `false`, после pyannote выполняется только стратегия §2.3 (1); если `true`, допускается стратегия §2.3 (2) при наличии ASR и ffmpeg. Переопределение на старте процесса: переменная окружения **`VT_DIARIZATION_TURN_LEVEL_RETRANSCRIPTION`** (`true`/`false`/`1`/`0` и т.д.). Пользовательский override: **`GET/PATCH /api/settings/user`** — `diarization_turn_level_retranscription_use_custom`, `diarization_turn_level_retranscription`; серверный дефолт для подсказки UI — поле **`diarization_turn_level_retranscription_default`** в **`GET /api/settings/limits`**.

### 4.2. Alignment (план)

Alignment будет оформлен аналогично diarization:

- `enabled`
- `default_provider`: `native|whisperx|mfa|none`
- `providers`: параметры реализации

MVP: alignment отключён и merge работает по segment-level.

---

## 5. API и UX

### 5.1. Автозапуск diarization после batch upload

- После успешного ASR, если `diarization.enabled=true`, ставим задачу diarization в отдельную очередь.
- Результат diarization — **новая версия** `Transcript(kind=asr_diarized)`; после `success` она становится активной.

### 5.2. Ручной повторный запуск diarization

- Endpoint `POST /api/conversations/{id}/diarize` ставит задачу в очередь.
- UI обязан показать confirm:
  - “Будет создана новая версия расшифровки и она станет активной после завершения. Предыдущие версии сохранятся.”

### 5.3. Повторный batch ASR по уже загруженному аудио

- Endpoint **`POST /api/conversations/{id}/retranscribe`** ставит ту же задачу Celery **`transcribe_file`**, что и после **`POST /api/upload`**: новая ревизия `Transcript(kind=asr)`; при **`diarization.enabled`** после успешного ASR снова может поставиться diarization (как при первичной загрузке).
- Требуется, чтобы у разговора было загруженное аудио (`audio_uploaded_at`); иначе **400**. Если уже есть ASR в статусе **`pending`/`running`** — **409**.
- Web UI: явное действие с подтверждением (**Transcribe again** на странице разговора).

---

## 6. Деплой: изоляция diarization worker/image (pyannote)

Рекомендация: держать diarization в отдельном worker/image из-за тяжёлых зависимостей (torch/CUDA).

Типовые риски/решения:

- **CUDA совместимость**: фиксировать базовый образ и версии torch/CUDA; использовать `--gpus` runtime.
- **Модель/кэш**: хранить кэш моделей на volume, иначе cold start.
- **HF токены**: только через env/secrets; на отсутствие — контролируемая ошибка.
- **Offline models**: при `offline_models=true` воркер не скачивает модели; требуются заранее прогретые файлы в `model_cache_dir`.
- **Конвертация аудио**: обеспечить `ffmpeg` внутри image для webm→wav/pcm.
- **Конкурентность**: ограничить concurrency (часто 1 задача/GPU), отдельная очередь Celery.

---

## 7. Acceptance Criteria (MVP)

- История сохраняется: каждый запуск ASR/diarization создаёт новую запись `transcripts` с `revision+1`.
- API/поиск/экспорт используют **активную** версию (`active_transcript_id`).
- `failed` попытки не ломают продукт: активная версия не меняется.
- Есть endpoint rerun diarization и UI подтверждение.
- Есть endpoint повторного batch ASR (`retranscribe`) и UI подтверждение.
- Diarization можно отключить глобально через `configs/diarization.yaml`.

