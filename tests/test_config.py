"""Secrets stay out of logs and reprs."""

from app.config import Settings


def test_database_password_is_never_shown_in_repr_or_str():
    s = Settings(_env_file=None, postgres_password="super-secret-pw")
    assert "super-secret-pw" not in repr(s)
    assert "super-secret-pw" not in str(s.model_dump())
    assert "super-secret-pw" in s.database_url  # only the connection string sees it
