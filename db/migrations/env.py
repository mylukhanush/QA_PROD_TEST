"""
Alembic Environment Configuration for Flask-Migrate.
"""
import os
import sys
from logging.config import fileConfig

from flask import current_app
from alembic import context

# Alembic Config object
config = context.config

# Setup logging if config file exists
try:
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)
except Exception:
    pass

# Use Flask-SQLAlchemy's metadata
target_metadata = current_app.extensions['migrate'].db.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
    connectable = current_app.extensions['migrate'].db.engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
