# Release-oriented targets (Linux/macOS/Git Bash). На Windows без make — см. команды в docs/RELEASE_BUILD_AND_DEPLOY.md.
.PHONY: help docker-build release-cli release-extension release-artifacts sbom-api

help:
	@echo "make docker-build        — docker compose build (каталог docker/)"
	@echo "make release-cli         — wheel/sdist в cli/dist/"
	@echo "make release-extension   — production bundle в browser-extension/dist/"
	@echo "make release-artifacts   — CLI + расширение подряд"
	@echo "make sbom-api            — пример SBOM (нужен локальный тег образа API)"

docker-build:
	cd docker && docker compose build

release-cli:
	cd cli && python -m pip install -q build && python -m build

release-extension:
	cd browser-extension && npm ci && npm run build

release-artifacts: release-cli release-extension

# Подставьте имя локального образа API после docker compose build (docker images).
sbom-api:
	@echo "Пример: docker scout quickview \$$IMAGE  или  trivy image \$$IMAGE"
