from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lumen.ai.models import DEFAULT_MODEL, MODELS


def _check_model(value: str | None) -> str | None:
    if value is not None and value not in MODELS:
        raise ValueError(f"unknown model, expected one of: {', '.join(MODELS)}")
    return value


def _check_url(value: str | None) -> str | None:
    if value is not None and not value.startswith("https://"):
        raise ValueError("the API base URL must use https")
    return value.rstrip("/") if value else value


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

    @field_validator("ai_model")
    @classmethod
    def _valid_model(cls, value: str | None) -> str | None:
        return _check_model(value)

    @field_validator("cloud_base_url")
    @classmethod
    def _valid_url(cls, value: str | None) -> str | None:
        return _check_url(value)
