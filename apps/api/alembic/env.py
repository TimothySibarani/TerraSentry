import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config
from terrasentry_api.config import settings
from terrasentry_api.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Settings normalizes relative paths identically for API, migration and rehearsal.
database_url = settings.database_url
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI)."""
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
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    path = make_url(database_url).database
    if path and path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            # Batch rebuilds replace referenced tables; only this migration connection skips FKs.
            await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            await connection.commit()
            await connection.run_sync(do_run_migrations)
            violations = (await connection.exec_driver_sql("PRAGMA foreign_key_check")).fetchall()
            if violations:
                raise RuntimeError(f"migration left foreign key violations: {violations}")
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode through the async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
