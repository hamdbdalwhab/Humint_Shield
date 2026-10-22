"""Tests for settings parsing (environment and ``.env`` sources)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_cors_origins_accepts_comma_separated(monkeypatch) -> None:
    """The documented CSV form must not crash startup.

    ``pydantic-settings`` JSON-decodes list fields before validators run, so this
    used to raise ``SettingsError`` and prevented the application from booting.
    """
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    settings = Settings()
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_accepts_single_value(monkeypatch) -> None:
    """A lone origin (no separator) yields a one element list."""
    monkeypatch.setenv("CORS_ORIGINS", "http://only.test")
    assert Settings().cors_origins == ["http://only.test"]


def test_cors_origins_accepts_json_array(monkeypatch) -> None:
    """The JSON array form keeps working."""
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.test", "http://b.test"]')
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_ignores_blank_entries(monkeypatch) -> None:
    """Trailing separators and spaces do not produce empty origins."""
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test,  ,http://b.test,")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_rejects_malformed_json(monkeypatch) -> None:
    """A malformed JSON array is reported rather than silently mangled."""
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.test"')
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert "CORS_ORIGINS" in str(excinfo.value)


def test_cors_origins_default_when_unset(monkeypatch) -> None:
    """An unset value falls back to the local frontend origin."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_origins == ["http://localhost:5173"]
