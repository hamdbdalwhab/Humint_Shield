"""Alembic environment (async).

Reads ``DATABASE_URL`` from application settings and runs migrations against
the async engine, so the same configuration drives both the app and Alembic.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import inspect, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401  (registers all models on Base.metadata)
from alembic import context
from app.config import get_settings
from app.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure the context and run migrations on a live connection."""
    _widen_version_table(connection)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def _widen_version_table(connection: Connection) -> None:
    """Widen ``alembic_version.version_num`` on PostgreSQL.

    Alembic creates the column as ``VARCHAR(32)``.  Several revision ids in this
    project are longer (``0016_usb_ledger_nullable_employee`` is 33 characters),
    which SQLite silently accepts but PostgreSQL rejects with
    ``StringDataRightTruncationError`` — the container would then restart
    forever on a managed Postgres.  The column is widened in place before
    Alembic reads or writes it; on SQLite this is a no-op.

    Args:
        connection: Active (synchronous wrapper) migration connection.
    """
    if connection.dialect.name != "postgresql":
        return
    # Pre-create the table with a wide column so a *first* migration run never
    # hits the 32-character default; Alembic skips creation when it exists.
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        "version_num VARCHAR(255) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    columns = {
        column["name"]: column
        for column in inspect(connection).get_columns("alembic_version")
    }
    version_column = columns.get("version_num")
    length = getattr(version_column["type"], "length", None) if version_column else None
    if length is not None and length < 255:
        connection.exec_driver_sql(
            "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"
        )
    # SQLAlchemy 2.0 connections start a transaction implicitly: without this
    # commit both statements are rolled back when the migration run ends.
    connection.commit()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for 'online' migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
