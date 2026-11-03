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


class EditRecipe(BaseModel):
    """Slider values are in the ranges the UI shows; 0 (or None) means unchanged."""

    model_config = ConfigDict(extra="forbid")

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

    def is_identity(self) -> bool:
        return self == IDENTITY

    def canonical_json(self) -> str:
        """Stable serialisation: equal recipes give equal strings (and hashes)."""
        data = self.model_dump(mode="json")
        return json.dumps(_rounded(data), sort_keys=True, separators=(",", ":"))

    def content_hash(self) -> str:
        """'' for a recipe that changes nothing, so it is treated as "not edited"."""
        if self.is_identity():
            return ""
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()[:16]


def _rounded(value: object) -> object:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


IDENTITY = EditRecipe()
