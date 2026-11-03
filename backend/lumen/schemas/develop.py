from __future__ import annotations

from pydantic import BaseModel, Field

from lumen.develop.recipe import EditRecipe

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


class EditSelect(BaseModel):
    edit_id: int | None = Field(description="Step to return to; null for the original")


class DevelopPreviewRequest(BaseModel):
    recipe: EditRecipe
    edge: int = Field(default=1600, ge=PREVIEW_MIN_EDGE, le=PREVIEW_MAX_EDGE)
