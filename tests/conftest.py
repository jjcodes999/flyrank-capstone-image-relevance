"""Integration-test fixtures: a separate Postgres database, migrated with Alembic.

The test database is `<POSTGRES_DB>_test` on the same server, so tests never touch
demo data. If Postgres is unreachable, DB tests are skipped (unit tests still run).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import Settings

TABLES = "reviews, suggestions, post_embeddings, image_embeddings, cost_records, job_items, jobs, image_tags, image_metadata, images, posts, tenants"


def _test_url() -> str:
    base = Settings().database_url
    url = make_url(base)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _test_url()
    admin = create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            name = make_url(url).database
            exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name})
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # no database available: skip integration tests
        pytest.skip(f"Postgres not reachable for integration tests: {exc.__class__.__name__}")
    finally:
        admin.dispose()

    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    return url


@pytest.fixture()
def sessions(db_url):
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(sessions, db_url, monkeypatch):
    """FastAPI TestClient bound to the test database."""
    from fastapi.testclient import TestClient

    from app import db as app_db
    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", db_url)

    def override_db():
        s = sessions()
        try:
            yield s
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[app_db.get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def pytest_configure(config):
    os.environ.setdefault("LOG_LEVEL", "WARNING")
