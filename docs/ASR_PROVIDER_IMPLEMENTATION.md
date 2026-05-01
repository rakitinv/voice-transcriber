# Подключение реализаций ASR-провайдеров (Phase B, пункт B1.5)

Канон: [TECHNICAL_SPECIFICATION.md](./TECHNICAL_SPECIFICATION.md) §9, [adr/0001-unified-asr-registry.md](./adr/0001-unified-asr-registry.md).  
Цель: один **registry** отдаёт живой `ASRProvider` для **Celery** (`transcribe_file`) и **realtime** (`core/asr_chunk`, `/ws/audio`), конфиг — `configs/asr.yaml`, без дублирования с `app/asr/factory.py`.

---

## 1. Текущее состояние (после B1.5)

| Компонент | Состояние |
|-----------|-----------|
| `configs/asr.yaml` | `default_provider`, **`recognition_model`** (текущая модель для активного движка), `providers.*`; опционально **`VT_ASR_MODEL`** |
| `plugins/loader.py` | `_load_asr_provider` → **`build_asr_provider`** из `app/asr/factory.py` |
| `app/asr/factory.py` | `build_asr_provider`, для `default_provider` подмешивает `recognition_model` в `config["model"]` |
| `app/asr/*.py` | Провайдеры возвращают **wired** placeholder (текст с `[ASR wired]`, имя модели) до подключения реального inference |
| `workers/tasks/asr.py` | `plugin_registry.get_asr_provider()` → если есть — `transcribe`; иначе классический `STUB_TRANSCRIPT` |
| `core/asr_chunk.py` | Аналогично для chunk |

Дальнейшие шаги: заменить placeholder в `app/asr/whisper.py` (и др.) на реальный вызов библиотеки; образ worker — зависимости GPU/CPU по мере необходимости.

---

## 2. Целевая архитектура

1. **Единая точка:** `PluginRegistry.get_asr_provider()` возвращает экземпляр для `app_config.asr.default_provider` (и опционально fallback по ТЗ/конфигу позже).
2. **Реализация загрузки:** внутри registry вызывать **`app.asr.factory._build_provider(name)`** (или вынести общую функцию в `core/asr_factory.py`, чтобы избежать циклических импортов — см. шаг 3).
3. **Конфиг:** только включённые в YAML провайдеры; для несуществующего `default_provider` — явная ошибка при старте или при первом обращении (лучше fail-fast при загрузке конфига).
4. **Stub:** если ни один провайдер не может быть создан (все `enabled: false` или ошибка зависимостей) — документированный режим: stub + предупреждение в логах (как сейчас), либо жёсткий fail в production по env (опционально).

---

## 3. Пошаговый план работ

### Шаг A — Устранить расхождение registry / factory (ADR 0001)

1. Проанализировать цепочку импортов: `plugins.loader` → `app.asr.factory` → `plugins.asr_base`. При риске цикла вынести минимальную функцию `create_asr_provider(engine_name: str) -> ASRProvider | None` в модуль **`core/asr_factory.py`** (или `plugins/asr_factory.py`), куда переезжает содержимое `_build_provider` + `ENGINE_PROVIDER_MAP` без зависимости от HTTP-слоя.
2. Обновить **`PluginRegistry._load_asr_provider`**: для каждого `enabled` провайдера из `app_config.asr.providers` вызывать фабрику и класть в `self._asr_providers[name]`; при исключении (нет модели, бинарник Vosk) — логировать и **не** регистрировать имя.
3. **`get_asr_provider(name=None)`** возвращает провайдер по `name` или по `default_provider`, если он успешно загружен; иначе `None` (stub).

### Шаг B — Проверить реализации в `app/asr/*.py`

1. **`transcribe(path, language)`** — форматы файлов после upload (webm, mp3, …): убедиться, что выбранный движок читает то, что кладётся во временный файл в `transcribe_file` (при необходимости конвертация через ffmpeg в задаче — отдельный подпункт).
2. **`transcribe_chunk(audio_data, language)`** — для realtime после B3 ожидаются **WAV** (см. `transcribe_pcm_s16le_chunk` / WAV в `core/asr_chunk.py`): проверить совместимость каждого провайдера; при необходимости единая нормализация в базовом классе.
3. Выровнять сигнатуры с `plugins/asr_base.ASRProvider` (без дрейфа).

### Шаг C — Celery worker

1. Убедиться, что **worker** тянет те же зависимости, что и провайдер (например `faster-whisper`, `torch`, модели — объём образа). Обновить **`docker/Dockerfile.worker`** (и при необходимости разделение **профилей** compose: worker-asr vs worker-light).
2. Очередь `asr` уже есть в compose — проверить, что задача `transcribe_file` уходит в worker с GPU/CPU по возможностям хоста (документация в `docker/README.md`).
3. Прогон: upload → лог worker → не-stub `transcript.json` в S3 и запись в БД.

### Шаг D — API и realtime (без отдельного GPU на API)

1. По умолчанию **`core/asr_chunk`** и WebSocket выполняют ASR **в thread pool** на API-процессе: тяжёлая модель на API может быть нежелательна. Зафиксировать политику:
   - **вариант 1:** лёгкий провайдер на API (Vosk small) для WS, тяжёлый только в Celery;
   - **вариант 2:** realtime-чанки тоже через Celery (очередь, задержка) — отдельная задача после B1.5;
   - **вариант 3:** только stub на API до Phase C.
2. Минимум для B1.5: **один** провайдер консистентно работает в worker для upload; для WS — документировать ограничение или включить тот же код с пониманием нагрузки.

### Шаг E — Конфигурация и секреты

1. Расширить **`configs/asr.yaml`** при необходимости: пути к моделям, API keys для облачных движков — через **env** в compose (`VT_ASR_*`), не коммитить секреты.
2. Описать переменные в **`docker/README.md`** или отдельном фрагменте в этом файле.

### Шаг F — Тесты

1. **Unit:** мок `ASRProvider` или минимальный fake, зарегистрированный в registry, проверка что `transcribe_file` не пишет stub (патч хранилища).
2. **Интеграция (опционально):** e2e с реальной моделью за флагом `VT_E2E_ASR=1` и коротким wav fixture.
3. Регрессия: при отключённых провайдерах по-прежнему stub и валидный JSON.

### Шаг G — Документация и приёмка

1. Обновить **`docs/TESTING.md`** / чеклист Phase B: «после B1.5 upload даёт не-stub при включённом провайдере».
2. Отметить **[ ] B1.5** в **`docs/ROADMAP.md`** после выполнения.

---

## 4. Критерий готовности B1.5

- [x] `plugin_registry.get_asr_provider()` возвращает не-`None` при `enabled: true` для `default_provider` (классы в `app/asr`).
- [x] `POST /api/upload` → Celery → текст с маркером **`[ASR wired]`** (или классический stub, если провайдер не загрузился) — см. e2e A3.2.
- [x] Текущая модель задаётся в **`configs/asr.yaml`** (`recognition_model`) и при необходимости **`VT_ASR_MODEL`**.
- [x] Единая фабрика: `build_asr_provider` в `app/asr/factory.py`, loader без дублирующей логики.

Реальный текст распознавания (не placeholder) — следующий этап: inference в `app/asr/*.py`.

---

## 5. Зависимости от других пунктов Phase B

- **B3.x** (PCM, chunk/windowed) уже подготавливают вход для `transcribe_chunk`; B1.5 **подключает** к этому входу реальный движок.
- **B2.x** (расширение браузера) логично начинать после выполнения B1.5, чтобы partial-транскрипт не был вечной заглушкой при демо.
