from __future__ import annotations

from pathlib import PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lumen.ai.models import DEFAULT_MODEL, MODELS


def _check_model(value: str | None) -> str | None:
    if value is not None and value not in MODELS:
        raise ValueError(f"unknown model, expected one of: {', '.join(MODELS)}")
    return value


def _check_folder(value: str | None) -> str | None:
    if value and not (PureWindowsPath(value).is_absolute() or value.startswith("/")):
        raise ValueError("the backup folder must be an absolute path")
    return value


def _check_url(value: str | None) -> str | None:
    if value is not None and not value.startswith("https://"):
        raise ValueError("the API base URL must use https")
    return value.rstrip("/") if value else value


def _check_mapweb_url(value: str | None) -> str | None:
    """MapWeb runs on the user's own machine (a Raspberry Pi at home, reached on the local
    network or over Tailscale), so plain http is allowed here."""
    if value is None:
        return None
    value = value.strip().rstrip("/")
    if not value:
        return ""
    if not value.startswith(("http://", "https://")) or len(value) <= len("https://"):
        raise ValueError("the MapWeb address must start with http:// or https://")
    return value


# Basemap styles. Online they are OpenFreeMap styles of the same name; offline "dark" uses
# the dark country map and the others the light one.
MapStyle = Literal["dark", "liberty", "bright", "positron"]


class AppSettings(BaseModel):
    map_online_tiles: bool = Field(
        default=False,
        description="Use the online street map (sends map viewport requests to OpenFreeMap)",
    )
    map_style: MapStyle = Field(default="dark", description="Basemap style")
    ai_enabled: bool = Field(default=False, description="Index photos with the local AI model")
    ai_model: str = Field(default=DEFAULT_MODEL, description="Local embedding model id")
    cloud_enabled: bool = Field(default=False, description="Allow (confirmed) cloud analysis")
    cloud_model: str = Field(default="deepseek-flash", max_length=100)
    cloud_base_url: str = Field(default="https://api.deepseek.com", max_length=200)
    cloud_include_location: bool = Field(
        default=False, description="Default for sending GPS coordinates with a cloud request"
    )
    backup_auto: bool = Field(default=True, description="Back up the database automatically")
    backup_interval_days: int = Field(default=7, ge=1, le=90)
    backup_keep: int = Field(default=10, ge=1, le=100, description="Automatic backups kept")
    backup_folder: str | None = Field(
        default=None, description="Backup folder (default: the data folder's backups)"
    )
    mapweb_url: str | None = Field(
        default=None,
        description="Address of the user's MapWeb (e.g. http://kevin:8788); photos are sent "
        "there only when the user asks",
    )


class AppSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_online_tiles: bool | None = None
    map_style: MapStyle | None = None
    ai_enabled: bool | None = None
    ai_model: str | None = None
    cloud_enabled: bool | None = None
    cloud_model: str | None = Field(default=None, min_length=1, max_length=100)
    cloud_base_url: str | None = Field(default=None, max_length=200)
    cloud_include_location: bool | None = None
    backup_auto: bool | None = None
    backup_interval_days: int | None = Field(default=None, ge=1, le=90)
    backup_keep: int | None = Field(default=None, ge=1, le=100)
    backup_folder: str | None = Field(
        default=None, max_length=500, description="An empty string goes back to the default"
    )
    mapweb_url: str | None = Field(
        default=None, max_length=300, description="An empty string removes the address"
    )

    @field_validator("backup_folder")
    @classmethod
    def _valid_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _check_folder(value.strip()) if value.strip() else ""

    @field_validator("ai_model")
    @classmethod
    def _valid_model(cls, value: str | None) -> str | None:
        return _check_model(value)

    @field_validator("mapweb_url")
    @classmethod
    def _valid_mapweb_url(cls, value: str | None) -> str | None:
        return _check_mapweb_url(value)

    @field_validator("cloud_base_url")
    @classmethod
    def _valid_url(cls, value: str | None) -> str | None:
        return _check_url(value)
