"""
Alembic environment configuration.

This file is used by Alembic to generate database migrations.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, pool

from alembic import context

# Import your models and config
from app.models import Base


def _database_url_for_migrations() -> str:
    """
    URL для миграций.

    В `configs/server.yaml` по умолчанию хост `postgres` — он доступен только внутри Docker-сети.
    Запуск `alembic upgrade head` **на хосте** (Windows/Linux) задайте один из вариантов:

    - `VT_DATABASE_URL` — тот же override, что у API (рекомендуется);
    - `ALEMBIC_DATABASE_URL` — только для Alembic, если не хотите трогать VT_*.

    Пример при Postgres из `docker compose` см. server/README.md (порт хоста: POSTGRES_PUBLISH_PORT, по умолчанию 5435).
    """
    url = (os.environ.get("VT_DATABASE_URL") or os.environ.get("ALEMBIC_DATABASE_URL") or "").strip()
    if url:
        return url
    from core.config import load_app_config

    resolved = load_app_config().database.url
    # Вне контейнера DNS-имя сервиса compose `postgres` не резолвится.
    host = urlparse(resolved).hostname
    if host == "postgres" and not Path("/.dockerenv").exists():
        raise RuntimeError(
            "Database URL указывает на хост `postgres` (только внутри docker-compose). "
            "Задайте переменную окружения перед `alembic upgrade head`, например:\n"
            '  PowerShell: $env:VT_DATABASE_URL = "postgresql+psycopg2://voice:voice@127.0.0.1:5435/voice"\n'
            "  (порт хоста по умолчанию 5435 — см. POSTGRES_PUBLISH_PORT в docker-compose.yml.)"
        )
    return resolved


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Set the database URL (Docker hostname vs localhost — см. docstring выше)
config.set_main_option("sqlalchemy.url", _database_url_for_migrations())

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Не используем engine_from_config(get_section): секция из alembic.ini может
    # перетирать URL, заданный выше через set_main_option (VT_DATABASE_URL / YAML).
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url is not set in Alembic config.")
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
