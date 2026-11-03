from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from lumen.core.config import Settings


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_hosts_are_allowed(host: str) -> None:
    assert Settings(host=host).host == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_non_loopback_hosts_are_rejected(host: str) -> None:
    with pytest.raises(ValidationError, match="loopback"):
        Settings(host=host)


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LUMEN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LUMEN_TOKEN", "secret")
    monkeypatch.setenv("LUMEN_ALLOWED_ORIGINS", "http://a.test, http://b.test")
    settings = Settings()
    assert settings.data_dir == tmp_path.resolve()
    assert settings.database_path == tmp_path.resolve() / "lumen.db"
    assert settings.token is not None and settings.token.get_secret_value() == "secret"
    assert settings.allowed_origins == ["http://a.test", "http://b.test"]


def test_default_data_dir_is_per_user() -> None:
    assert Settings().data_dir.name == "LUMEN Studio"
