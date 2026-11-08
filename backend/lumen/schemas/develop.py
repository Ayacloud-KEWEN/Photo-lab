from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

from lumen.develop.recipe import EditRecipe, VideoRecipe

PREVIEW_MIN_EDGE = 256
PREVIEW_MAX_EDGE = 2560


class EditStep(BaseModel):
    id: int
    created_at: str
    changes: list[str] = Field(description="Recipe fields changed by this step (empty for a reset)")


class EditState(BaseModel):
    asset_id: int
    recipe: EditRecipe = Field(description="The recipe in effect (all defaults if unedited)")
    current_edit_id: int | None = Field(description="Step in effect; null shows the original")
    steps: list[EditStep] = Field(description="Saved steps, oldest first")
    can_undo: bool
    can_redo: bool
    is_edited: bool
    source_format: str = Field(description="Upper-case extension of the developed file")
    is_raw: bool
    rendition_version: str | None


RecipeField = Literal[
    "exposure", "contrast", "highlights", "shadows", "whites", "blacks",
    "temperature", "tint", "vibrance", "saturation", "clarity", "sharpness", "vignette",
    "rotate", "flip_horizontal", "straighten", "crop",
]  # fmt: skip
# Live Photo fields belong to one clip and are not copied to other photos.
assert set(get_args(RecipeField)) == set(EditRecipe.model_fields) - {
    "version",
    "live_frame_ms",
    "live_effect",
}


class EditBatch(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=20_000)
    recipe: EditRecipe = Field(description="Source of the values (copied settings, a preset)")
    fields: list[RecipeField] = Field(min_length=1, description="Which values to apply")


class EditBatchResult(BaseModel):
    updated: int
    skipped: int = Field(description="Videos, and photos whose original is unavailable")


class EditSelect(BaseModel):
    edit_id: int | None = Field(description="Step to return to; null for the original")


class DevelopPreviewRequest(BaseModel):
    recipe: EditRecipe
    edge: int = Field(default=1600, ge=PREVIEW_MIN_EDGE, le=PREVIEW_MAX_EDGE)


class VideoEditState(BaseModel):
    asset_id: int
    recipe: VideoRecipe = Field(description="The edit in effect (defaults if unedited)")
    duration_ms: int | None
    is_edited: bool
    rendition_version: str | None


class FrameExport(BaseModel):
    time_ms: int = Field(ge=0, description="Position in the original video")
    destination: str = Field(min_length=1, description="An existing folder (absolute path)")
    quality: int = Field(default=92, ge=50, le=100)


class FrameExportResult(BaseModel):
    path: str


class LiveFrame(BaseModel):
    time_ms: int
    sharpness: float = Field(description="0..1, relative to the sharpest frame")


class LiveInfo(BaseModel):
    """A Live Photo's clip, for choosing a frame (see /live/strip for its thumbnails)."""

    asset_id: int
    width: int = Field(description="Frame size, upright")
    height: int
    duration_ms: int
    still_ms: int | None = Field(description="Where the still was taken, when recorded")
    recommended_ms: int | None = Field(description="The sharpest frame")
    frames: list[LiveFrame]
    strip_tiles: int = Field(description="Frames in the strip image, evenly spaced in time")
