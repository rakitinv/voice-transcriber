# Версионирование проекта

## Источник истины

| Файл | Назначение |
|------|------------|
| [`VERSION`](../VERSION) | Текущий номер релиза (SemVer, одна строка, напр. `0.2.0`) |
| [`CHANGELOG.md`](../CHANGELOG.md) | Описание изменений по версиям |

Версия дублируется в артефактах (синхронизация скриптом):

- `server/pyproject.toml`
- `cli/pyproject.toml`
- `webui/package.json`, `admin-webui/package.json`, `browser-extension/package.json`

## SemVer (кратко)

- **MAJOR** — несовместимые изменения API/контрактов.
- **MINOR** — новая функциональность с обратной совместимостью.
- **PATCH** — исправления без смены контрактов.

Теги Git: `v0.2.0` (префикс `v` + содержимое `VERSION`).

## Workflow при изменениях (перед commit)

1. Внесите код / конфиг.
2. Откройте [`CHANGELOG.md`](../CHANGELOG.md):
   - добавьте пункты в секцию **`[Unreleased]`** (Added / Changed / Fixed / Removed);
   - при релизе переименуйте `[Unreleased]` в `[X.Y.Z] - ГГГГ-ММ-ДД`, создайте новую пустую `[Unreleased]`.
3. Обновите номер в [`VERSION`](../VERSION), если выпускаете новую версию (не каждый мелкий commit обязан bump — см. ниже).
4. Синхронизируйте версию в пакетах:

   ```powershell
   # Windows
   .\scripts\sync-version.ps1
   ```

   ```bash
   # Linux / Git Bash
   bash scripts/sync-version.sh
   ```

5. Commit (желательно отдельным коммитом для релиза или в том же, что и фича):

   ```text
   release: v0.2.1

   Краткое описание; детали — в CHANGELOG.md.
   ```

6. После push создайте тег и отправьте его:

   ```bash
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```

## Когда менять VERSION

| Ситуация | Действие |
|----------|----------|
| WIP / промежуточные commit | Только `CHANGELOG [Unreleased]` (опционально) |
| Готовый релиз для деплоя | Bump `VERSION`, секция в CHANGELOG, `sync-version`, тег `v*` |
| Только docs / мелкий fix | PATCH (`0.2.0` → `0.2.1`) или накопить в Unreleased |

Release-сборки: в `scripts/release/release.env` задайте `VT_RELEASE_TAG=v$(cat VERSION)` или тег из `git describe`.

## Связь с docker / release

- `VT_RELEASE_TAG` в [`scripts/release/release.env.example`](../scripts/release/release.env.example) должен совпадать с тегом Git / `VERSION`.
- Образы и дистрибутив: `dist/release/voice-transcriber-<tag>/`.
