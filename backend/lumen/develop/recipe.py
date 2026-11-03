"""Edit recipes: the complete, versioned description of how to develop a photo."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RECIPE_VERSION: Literal[1] = 1


class Crop(BaseModel):
    """A rectangle in the rotated and straightened frame, as fractions of its size."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _inside_frame(self) -> Crop:
        if self.x + self.width > 1 + 1e-6 or self.y + self.height > 1 + 1e-6:
            raise ValueError("crop must lie inside the image")
        return self


class _Recipe(BaseModel):
    """Shared by photo and video recipes: identity, stable serialisation and hashing."""

    model_config = ConfigDict(extra="forbid")

    def is_identity(self) -> bool:
        return self == type(self)()

    def canonical_json(self) -> str:
        """Stable serialisation: equal recipes give equal strings (and hashes)."""
        data = self.model_dump(mode="json")
        return json.dumps(_rounded(data), sort_keys=True, separators=(",", ":"))

    def content_hash(self) -> str:
        """'' for a recipe that changes nothing, so it is treated as "not edited"."""
        if self.is_identity():
            return ""
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()[:16]


class EditRecipe(_Recipe):
    """A photo's edit. Slider values are in the ranges the UI shows; 0 (or None) means
    unchanged."""

    version: Literal[1] = RECIPE_VERSION
    # Tone
    exposure: float = Field(default=0, ge=-5, le=5, description="EV")
    contrast: float = Field(default=0, ge=-100, le=100)
    highlights: float = Field(default=0, ge=-100, le=100)
    shadows: float = Field(default=0, ge=-100, le=100)
    whites: float = Field(default=0, ge=-100, le=100)
    blacks: float = Field(default=0, ge=-100, le=100)
    # Colour
    temperature: float = Field(default=0, ge=-100, le=100, description="warmer when positive")
    tint: float = Field(default=0, ge=-100, le=100, description="magenta when positive")
    vibrance: float = Field(default=0, ge=-100, le=100)
    saturation: float = Field(default=0, ge=-100, le=100)
    # Detail and effects
    clarity: float = Field(default=0, ge=-100, le=100)
    sharpness: float = Field(default=0, ge=0, le=100)
    vignette: float = Field(default=0, ge=-100, le=100, description="darker corners when negative")
    # Geometry, applied in this order: quarter turns, flip, straighten, crop.
    rotate: int = Field(default=0, ge=0, le=3, description="quarter turns clockwise")
    flip_horizontal: bool = False
    straighten: float = Field(default=0, ge=-45, le=45, description="degrees, clockwise")
    crop: Crop | None = None


MIN_CLIP_MS = 100


class VideoRecipe(_Recipe):
    """A video's edit: the part to keep, extra quarter turns and whether to drop the sound."""

    version: Literal[1] = RECIPE_VERSION
    kind: Literal["video"] = "video"
    trim_start_ms: int = Field(default=0, ge=0)
    trim_end_ms: int | None = Field(default=None, gt=0, description="null: to the end")
    rotate: int = Field(default=0, ge=0, le=3, description="quarter turns clockwise")
    mute: bool = False

    @model_validator(mode="after")
    def _valid_range(self) -> VideoRecipe:
        if self.trim_end_ms is not None and self.trim_end_ms < self.trim_start_ms + MIN_CLIP_MS:
            raise ValueError("the end must come after the start")
        return self


def parse_recipe(text: str) -> EditRecipe | VideoRecipe:
    """A stored recipe (photo recipes predate ``kind`` and have none)."""
    data = json.loads(text)
    if isinstance(data, dict) and data.get("kind") == "video":
        return VideoRecipe.model_validate(data)
    return EditRecipe.model_validate(data)


def _rounded(value: object) -> object:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


IDENTITY = EditRecipe()
