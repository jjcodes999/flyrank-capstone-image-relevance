"""Secrets stay out of logs and reprs; any password works in the connection URL."""

import pytest
from sqlalchemy.engine import make_url

from app.config import Settings


@pytest.fixture(autouse=True)
def no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_database_password_is_never_shown_in_repr_or_str():
    s = Settings(_env_file=None, postgres_password="super-secret-pw")
    assert "super-secret-pw" not in repr(s)
    assert "super-secret-pw" not in str(s.model_dump())
    assert "super-secret-pw" in s.database_url  # only the connection string sees it


def test_a_full_database_url_is_masked_too(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:very-secret@db:5432/x")
    s = Settings(_env_file=None)
    assert "very-secret" not in repr(s)
    assert s.database_url.endswith("@db:5432/x")


@pytest.mark.parametrize("password", ["audit@host:/#?", "p@ss word", "100%sure"])
def test_passwords_with_url_special_characters_still_connect_to_the_right_host(password):
    url = make_url(Settings(_env_file=None, postgres_password=password, postgres_host="db").database_url)
    assert (url.host, url.password, url.database) == ("db", password, "imagematch")


def test_embed_dim_must_match_the_database_schema():
    with pytest.raises(ValueError, match="vector\(384\)"):
        Settings(_env_file=None, embed_dim=768)
