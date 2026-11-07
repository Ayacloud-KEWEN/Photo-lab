"""Configuration management.

All settings come from environment variables prefixed with ``LUMEN_`` (see README).
The desktop shell sets them when it launches the backend; defaults are suitable
for running the backend on its own during development.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal

from platformdirs import user_data_dir
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

APP_DIR_NAME = "LUMEN Studio"
DEFAULT_ALLOWED_ORIGINS = [
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
    "http://localhost:1420",
]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


def default_data_dir() -> Path:
    # %LOCALAPPDATA%\LUMEN Studio on Windows (see docs/ARCHITECTURE.md, ADR-002).
    return Path(user_data_dir(APP_DIR_NAME, appauthor=False, roaming=False))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LUMEN_", extra="ignore")

    data_dir: Path = Field(default_factory=default_data_dir)
    host: str = "127.0.0.1"
    port: int = Field(default=0, ge=0, le=65535)
    token: SecretStr | None = None
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_ORIGINS)
    )
    log_level: LogLevel = "INFO"
    log_to_file: bool = True

    # External media tools; looked up on PATH when not set.
    exiftool_path: Path | None = None
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None
    # Parallel file workers used while ingesting media (decoding photos is CPU bound;
    # reads from a spinning disk are limited separately, see ingest.HDD_READERS).
    ingest_workers: int = Field(
        default_factory=lambda: max(1, min(8, (os.cpu_count() or 2) // 2)), ge=1
    )
    # Background task processing; disabled in some tests.
    run_tasks: bool = True
    # Local AI: "auto" uses the GPU when available; the model is unloaded when idle.
    ai_device: Literal["auto", "cuda", "cpu"] = "auto"
    ai_idle_unload_s: float = Field(default=600, ge=10)
    # Thumbnails and previews (ADR-031): the folder chosen in Settings is applied at startup
    # and when the cache is moved; None means ``<data_dir>/cache``.
    cache_folder: Path | None = None

    @field_validator("host")
    @classmethod
    def _host_must_be_loopback(cls, value: str) -> str:
        # The backend must never listen on a network-reachable interface.
        if value == "localhost":
            return value
        try:
            if ipaddress.ip_address(value).is_loopback:
                return value
        except ValueError:
            pass
        raise ValueError("host must be a loopback address (127.0.0.1, ::1 or localhost)")

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("data_dir")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @cached_property
    def database_path(self) -> Path:
        return self.data_dir / "lumen.db"

    @cached_property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @cached_property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @cached_property
    def default_cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def cache_dir(self) -> Path:
        """Generated thumbnails and previews; safe to delete, rebuilt on demand."""
        return self.cache_folder or self.default_cache_dir

    def tool(self, name: Literal["exiftool", "ffmpeg", "ffprobe"]) -> str | None:
        configured: Path | None = getattr(self, f"{name}_path")
        if configured is not None:
            return str(configured) if configured.exists() else None
        return shutil.which(name)

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.log_dir, self.backup_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)
