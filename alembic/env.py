from logging.config import fileConfig

from sqlalchemy import create_engine

from alembic import context
from app.config import get_settings

config = context.config
if config.config_file_name is not None:
    # keep loggers created before migrations (tests run alembic in-process)
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_online() -> None:
    # tests pass their own URL through the alembic config; otherwise use app settings
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
