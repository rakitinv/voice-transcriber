# Идентификация и переименование спикеров

План доработки: от обезличенных меток pyannote (`SPEAKER_00`, `Speaker 1`) к **отображаемым именам** в расшифровке, экспорте и сводках — с опциональным **предложением имён через LLM** и ручным подтверждением/правкой.

**Связанные документы:** [DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md), [TECHNICAL_SPECIFICATION.md](./TECHNICAL_SPECIFICATION.md), [MODEL_CONFIGURATION.md](./MODEL_CONFIGURATION.md), [ROADMAP.md](./ROADMAP.md).

**Статус:** запланировано (не реализовано).

---

## Цели

| Цель | Описание |
|------|----------|
| **Идентификация** | После диаризации LLM анализирует текст и предлагает соответствие «канонический ID спикера → имя/роль» (с оценкой уверенности). |
| **Переименование** | Пользователь правит предложения или задаёт имена вручную; изменения видны в UI, export и (опционально) пересчитывают summary. |
| **Стабильность** | Повторная диаризация не ломает пользовательские имена без явного сброса (привязка к `speaker_id`, а не к порядку сегментов). |
| **Прозрачность** | В UI различать «ID от pyannote» и «отображаемое имя»; не выдавать выдуманные ФИО за факт без пометки «предположение». |

**Вне scope v1:** распознавание голоса по голосовому отпечатку вне pyannote; автоматическая привязка к контактам CRM; speaker ID между разными разговорами одного пользователя (глобальный адресбук — backlog).

---

## Текущее состояние

- pyannote пишет в `transcript_json.segments[].speaker` строковые метки (`SPEAKER_00`, …).
- `transcript_md` дублирует те же метки: `**SPEAKER_00** (12.0s–15.2s): …`.
- Web UI (`TranscriptViewer`) показывает `seg.speaker` как есть.
- Rolling summary (`summarize_recording_session`) берёт `transcript_md` активного `asr_diarized`; промпт просит упомянуть спикеров **«если видны»** — без структурированной карты имён.
- Отдельного API для смены имён спикеров нет.

---

## Модель данных

### Разделение ID и отображаемого имени

В каждом сегменте `transcript_json`:

```json
{
  "speaker_id": "SPEAKER_00",
  "speaker": "Иван Петров",
  "start": 12.0,
  "end": 15.2,
  "text": "…"
}
```

| Поле | Назначение |
|------|------------|
| `speaker_id` | Стабильный ключ от диаризации (не меняется при rename). |
| `speaker` | Отображаемое имя (после LLM и/или пользователя). До rename = копия `speaker_id` или локализованный `Speaker N`. |

### Карта имён на уровне разговора

Хранить в **`conversations.speaker_labels`** (JSONB) или в `transcripts.meta.speaker_labels` активной `asr_diarized`:

```json
{
  "SPEAKER_00": {
    "display_name": "Иван Петров",
    "source": "llm_suggested",
    "confidence": 0.72,
    "updated_at": "2026-06-25T13:00:00Z",
    "updated_by": "user"
  },
  "SPEAKER_01": {
    "display_name": "Ведущий",
    "source": "manual",
    "confidence": null
  }
}
```

`source`: `diarization` | `llm_suggested` | `llm_auto` | `manual`.

**Рекомендация:** колонка на **`conversations`** — имена относятся к продуктовому объекту «разговор», переживают смену активной ревизии `asr_diarized` при rerun diarization, если `speaker_id` совпали (см. §Сопоставление при rerun).

### Миграция Alembic

- `conversations.speaker_labels JSONB NULL`
- (опционально) `conversations.speaker_identification_status` — `idle` | `pending` | `running` | `success` | `failed` | `skipped`

---

## Применение имён (единая функция)

Модуль `server/core/speaker_labels.py` (или `app/services/speaker_display.py`):

1. `apply_speaker_labels(segments, speaker_labels) -> segments` — подставляет `speaker` из карты по `speaker_id`.
2. `rebuild_transcript_md(segments) -> str` — как в `diarization.py`, но с display names.
3. Вызывать при: GET conversation, export, после PATCH labels, после LLM identify.

**Обратная совместимость:** если `speaker_id` отсутствует, использовать `speaker` как ID (старые транскрипты).

---

## LLM: выявление спикеров

### Когда запускать

После `diarization_completed` и promote `asr_diarized`, если:

- `configs/llm.yaml` → `speaker_identification.enabled: true` (новый блок);
- есть ≥2 уникальных `speaker_id` (опционально: и при 1 спикере — только роль «Ведущий»);
- очередь **`llm`** (тот же воркер, что summary).

Задача Celery: `workers.tasks.llm.identify_speakers(user_id, conversation_id)`.

**Порядок относительно summary:** identify → затем `schedule_recording_session_summary` (чтобы сводка уже видела имена). Сейчас summary ставится сразу после diarization — изменить цепочку: summary после identify **или** повторная постановка summary после apply labels.

### Вход для LLM

Сэмпл по спикерам (лимит токенов, напр. 8000 символов):

- для каждого `speaker_id`: 3–5 реплик (начало, середина, конец записи);
- длительность участия, доля речи;
- язык из транскрипта.

Не передавать аудио в v1 — только текст.

### Выход (строгий JSON)

```json
{
  "speakers": [
    {
      "speaker_id": "SPEAKER_00",
      "suggested_name": "Иван",
      "role": "клиент",
      "confidence": 0.65,
      "evidence": "в 02:15 говорит «меня зовут Иван»"
    }
  ],
  "notes": "второй участник не представился"
}
```

Промпт: **не выдумывать** ФИО; при отсутствии сигналов — `suggested_name: null` или нейтральная роль (`Участник 1`). Язык ответа — как у `llm_summary_output_language`.

### Режимы применения (`speaker_identification.mode`)

| Режим | Поведение |
|-------|-----------|
| `suggest` (default) | Записать предложения в `speaker_labels` с `source=llm_suggested`, **не** менять отображение до подтверждения пользователя; UI — баннер «Предложены имена спикеров». |
| `auto_apply` | При `confidence >= threshold` (напр. 0.8) сразу `display_name` + пересборка `transcript_md`; иначе как `suggest`. |
| `off` | Только ручное переименование. |

Порог и режим — `configs/llm.yaml` + env `VT_SPEAKER_IDENTIFICATION_*`.

---

## API (сначала OpenAPI)

| Метод | Путь | Назначение |
|-------|------|------------|
| `GET` | `/api/conversations/{id}/speakers` | Карта `speaker_labels` + список `speaker_id` из активного транскрипта, статус identify. |
| `PATCH` | `/api/conversations/{id}/speakers` | Обновление `display_name` по `speaker_id`; `source=manual`; пересборка md/json активного транскрипта. |
| `POST` | `/api/conversations/{id}/speakers/identify` | Повторный запуск LLM identify (как retry summary). |
| `POST` | `/api/conversations/{id}/speakers/apply-suggestions` | Принять все или выбранные LLM-предложения. |

Расширить `GET /api/conversations/{id}`: поле `speaker_labels`, `speaker_identification_status`.

Export `md`/`json`: отображаемые имена; в JSON `_meta.speaker_labels` и сохранённые `speaker_id`.

---

## Web UI

### Страница разговора

1. Над расшифровкой — панель **«Спикеры»**: чипы `SPEAKER_00 → [Иван ▾]` с inline edit.
2. Если есть `llm_suggested` без подтверждения — кнопки «Принять», «Изменить», «Отклонить» по каждому спикеру.
3. Кнопка «Определить имена (LLM)» при `speaker_identification.enabled`.
4. `TranscriptViewer` — только `speaker` (уже с подставленным именем).

### Настройки пользователя (опционально v2)

В `GET/PATCH /api/settings/user`: `speaker_identification_auto_apply: bool` — переопределение серверного default.

---

## Интеграция с summary и поиском

| Компонент | Изменение |
|-----------|-----------|
| `summarize_recording_session` | После apply labels; в bundle явный блок «Участники: …» из `speaker_labels`. |
| Промпт summary | Требовать секцию **«Участники»** при наличии карты имён (не «если видны»). |
| Semantic search / embeddings | При PATCH speakers — переиндексация сегментов с новым `speaker` в тексте чанка (очередь `llm`). |
| Admin API | Snapshot: флаг `speaker_identification.enabled`, статистика identify. |

---

## Rerun diarization и сопоставление ID

При новой ревизии `asr_diarized` pyannote может переназначить `SPEAKER_00` ↔ `SPEAKER_01`.

**v1 (простой):** при успешном rerun diarization сбрасывать `speaker_labels` и `speaker_identification_status` (предупреждение в UI).

**v2 (backlog):** эвристическое сопоставление по overlap временных интервалов + текстовое сходство; перенос display names на новые `speaker_id`.

---

## Фазы реализации

### Фаза S1 — Ручное переименование (MVP)

- [ ] Alembic: `conversations.speaker_labels`
- [ ] `speaker_id` в сегментах при записи diarization (сохранять pyannote label в `speaker_id`, `speaker` = display)
- [ ] `core/speaker_labels.py`: apply + rebuild md
- [ ] `GET/PATCH …/speakers`, OpenAPI
- [ ] Web UI: панель спикеров + inline rename
- [ ] Export и GET conversation с display names
- [ ] Unit-тесты: apply labels, export md

**Приёмка:** после diarization пользователь переименовывает `SPEAKER_00` → «Иван»; в расшифровке и MD-экспорте везде «Иван».

### Фаза S2 — LLM-предложения имён

- [ ] `configs/llm.yaml`: блок `speaker_identification`
- [ ] Celery `identify_speakers`, провайдерный метод `suggest_speaker_names` в `LLMProvider`
- [ ] Цепочка после diarization; `POST …/identify`, `POST …/apply-suggestions`
- [ ] UI: баннер предложений, confidence, evidence
- [ ] Тесты с мок LLM

**Приёмка:** на записи с фразой «меня зовут …» LLM предлагает имя; пользователь принимает — отображение обновляется без rerun diarization.

### Фаза S3 — Summary, авто-режим, полировка

- [ ] Summary после identify / обновление промпта с секцией «Участники»
- [ ] Режим `auto_apply` + threshold
- [ ] Переиндексация embeddings при rename
- [ ] Документация `MODEL_CONFIGURATION.md`, env example
- [ ] Чеклист приёмки в `PHASE_C_ACCEPTANCE.md` или `SPEAKER_IDENTIFICATION_ACCEPTANCE.md`

---

## Конфигурация (черновик)

`configs/llm.yaml`:

```yaml
speaker_identification:
  enabled: false
  mode: suggest          # suggest | auto_apply | off
  auto_apply_min_confidence: 0.8
  max_input_chars_per_speaker: 2000
  max_speakers: 8
```

Env: `VT_SPEAKER_IDENTIFICATION_ENABLED`, `VT_SPEAKER_IDENTIFICATION_MODE`, …

---

## Риски и ограничения

| Риск | Митигация |
|------|-----------|
| LLM выдумывает имена | Жёсткий промпт + `confidence` + default `suggest` |
| Длинные записи (как 29 мин) | Сэмплирование реплик, не весь текст |
| Один спикер в UI | Не запускать identify или предлагать только роль |
| GDPR / персональные данные | Имена хранятся у пользователя; не логировать полный prompt в prod |
| Стоимость/latency | Очередь `llm`, один вызов на разговор, кэш по `conversation_id` + revision |

---

## Критерии готовности продукта

1. В расшифровке после diarization можно задать **человекочитаемые** имена без повторного ASR/diarization.
2. LLM **предлагает** имена там, где они явно звучат в тексте; иначе — нейтральные подписи.
3. Export MD/JSON и session summary используют **display names**, сохраняя `speaker_id` в JSON.
4. Поведение документировано; feature flag на сервере.

---

## История

| Дата | Изменение |
|------|-----------|
| 2026-06-25 | Первоначальный план (S1–S3) |
