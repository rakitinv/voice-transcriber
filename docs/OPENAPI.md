# OpenAPI — источник правды API

Канонический файл: **[`../openapi.yaml`](../openapi.yaml)** (корень репозитория).

## Проверка схемы (Этап 0.2)

Локально, без установки в проект:

```bash
npx --yes @redocly/cli@1 lint openapi.yaml
```

В корне репозитория используется [`.redocly.yaml`](../.redocly.yaml): часть строгих правил отключена на этапе наполнения спецификации; при необходимости вернуть `security-defined` и `operation-operationId`.

Из корня репозитория путь к файлу: `openapi.yaml`.

Альтернатива — [Swagger Editor](https://editor.swagger.io/) (вставить содержимое YAML).

## Синхронизация с реализацией

1. Изменения в контракте сначала вносятся в `openapi.yaml`.
2. Затем реализуются в `server/app/api/` и клиентах (см. [TECHNICAL_SPECIFICATION.md](./TECHNICAL_SPECIFICATION.md) §3).

При добавлении CI достаточно шага `npx @redocly/cli lint openapi.yaml` или валидации через `openapi-spec-validator` в Python.
