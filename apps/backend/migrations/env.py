from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Only part of the schema has ORM models: the matching/catalog/offers tables are created by
# hand-written migrations with no SQLAlchemy model behind them. Without this filter,
# --autogenerate sees them as "tables not in the metadata" and emits drop_table() for every one
# of them. Restrict comparison to the tables Base actually owns.
OWNED_TABLES = frozenset(Base.metadata.tables)

# Stable PostgreSQL advisory-lock key (ASCII "ALLOCURA"). All online migration
# commands share it so concurrently starting containers cannot race on the schema.
MIGRATION_LOCK_ID = 0x414C4C4F43555241


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    if type_ == "table":
        return name in OWNED_TABLES

    parent_table = getattr(object_, "table", None)
    parent_name = getattr(parent_table, "name", None)
    if parent_name is not None:
        return parent_name in OWNED_TABLES

    return True


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )

    with context.begin_transaction():
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": MIGRATION_LOCK_ID},
        )
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_settings().database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())
