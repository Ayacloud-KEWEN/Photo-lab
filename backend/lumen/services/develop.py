"""Non-destructive editing: the history of edit recipes per asset, and develop previews.

History is linear, like an editor's undo stack: the asset points at the step in effect
(or at nothing, showing the original). Saving after an undo discards the undone steps.
"""

from __future__ import annotations

import io
import sqlite3

from lumen.core.errors import NotFoundError
from lumen.db.connection import transaction, utc_now
from lumen.develop import engine
from lumen.develop.recipe import IDENTITY, EditRecipe
from lumen.schemas.develop import EditState, EditStep
from lumen.services.assets import (
    DevelopUnavailableError,
    develop_source,
    rendition_version,
)

MAX_STEPS = 100
PREVIEW_QUALITY = 85


def _steps(conn: sqlite3.Connection, asset_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, recipe, recipe_hash, created_at FROM edit_history "
        "WHERE asset_id = ? ORDER BY id",
        (asset_id,),
    ).fetchall()


def _asset(conn: sqlite3.Connection, asset_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT a.id, a.current_edit_id, c.fingerprint FROM media_assets a
        LEFT JOIN media_files c ON c.id = a.cover_file_id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("Asset not found", details={"id": asset_id})
    asset: sqlite3.Row = row
    return asset


def _changes(before: EditRecipe, after: EditRecipe) -> list[str]:
    old, new = before.model_dump(), after.model_dump()
    return [key for key in new if new[key] != old[key]]


def get_edit_state(conn: sqlite3.Connection, asset_id: int) -> EditState:
    asset = _asset(conn, asset_id)
    source = develop_source(conn, asset_id)
    rows = _steps(conn, asset_id)
    current_id = asset["current_edit_id"]

    steps: list[EditStep] = []
    recipe, previous = IDENTITY, IDENTITY
    current_index = -1
    for index, row in enumerate(rows):
        step_recipe = EditRecipe.model_validate_json(row["recipe"])
        changes = _changes(previous, step_recipe)
        steps.append(EditStep(id=row["id"], created_at=row["created_at"], changes=changes))
        previous = step_recipe
        if row["id"] == current_id:
            recipe, current_index = step_recipe, index
    edit_hash = recipe.content_hash()
    return EditState(
        asset_id=asset_id,
        recipe=recipe,
        current_edit_id=current_id if current_index >= 0 else None,
        steps=steps,
        can_undo=current_index >= 0,
        can_redo=current_index < len(steps) - 1,
        is_edited=bool(edit_hash),
        source_format=source.extension.upper(),
        is_raw=source.format.is_raw,
        rendition_version=rendition_version(asset["fingerprint"], edit_hash) or None,
    )


def save_edit(conn: sqlite3.Connection, asset_id: int, recipe: EditRecipe) -> EditState:
    """Append ``recipe`` as the step in effect (nothing happens if it is already in effect)."""
    develop_source(conn, asset_id)  # only photos with an available original are edited
    with transaction(conn):
        asset = _asset(conn, asset_id)
        current_id = asset["current_edit_id"]
        current = IDENTITY
        if current_id is not None:
            row = conn.execute(
                "SELECT recipe FROM edit_history WHERE id = ?", (current_id,)
            ).fetchone()
            current = EditRecipe.model_validate_json(row["recipe"])
        if recipe == current:
            return get_edit_state(conn, asset_id)

        # Steps after the one in effect were undone: a new edit replaces them.
        conn.execute(
            "DELETE FROM edit_history WHERE asset_id = ? AND id > ?",
            (asset_id, current_id if current_id is not None else 0),
        )
        now = utc_now()
        cursor = conn.execute(
            "INSERT INTO edit_history (asset_id, recipe, recipe_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (asset_id, recipe.canonical_json(), recipe.content_hash(), now),
        )
        conn.execute(
            "UPDATE media_assets SET current_edit_id = ?, updated_at = ? WHERE id = ?",
            (cursor.lastrowid, now, asset_id),
        )
        conn.execute(
            """
            DELETE FROM edit_history WHERE asset_id = ? AND id NOT IN (
                SELECT id FROM edit_history WHERE asset_id = ? ORDER BY id DESC LIMIT ?)
            """,
            (asset_id, asset_id, MAX_STEPS),
        )
    return get_edit_state(conn, asset_id)


def select_edit(conn: sqlite3.Connection, asset_id: int, edit_id: int | None) -> EditState:
    """Put a saved step (or the original, for ``None``) in effect, keeping the history."""
    with transaction(conn):
        _asset(conn, asset_id)
        if edit_id is not None:
            found = conn.execute(
                "SELECT 1 FROM edit_history WHERE id = ? AND asset_id = ?", (edit_id, asset_id)
            ).fetchone()
            if found is None:
                raise NotFoundError("Edit step not found", details={"id": edit_id})
        conn.execute(
            "UPDATE media_assets SET current_edit_id = ?, updated_at = ? WHERE id = ?",
            (edit_id, utc_now(), asset_id),
        )
    return get_edit_state(conn, asset_id)


def step_edit(conn: sqlite3.Connection, asset_id: int, offset: int) -> EditState:
    """Undo (``-1``) or redo (``+1``) one step."""
    asset = _asset(conn, asset_id)
    ids: list[int | None] = [None, *(row["id"] for row in _steps(conn, asset_id))]
    current = asset["current_edit_id"] if asset["current_edit_id"] in ids else None
    target = ids.index(current) + offset
    if not 0 <= target < len(ids):
        return get_edit_state(conn, asset_id)
    return select_edit(conn, asset_id, ids[target])


def render_preview(
    conn: sqlite3.Connection, asset_id: int, recipe: EditRecipe, edge: int
) -> tuple[bytes, list[list[int]]]:
    """A JPEG of the photo developed with ``recipe`` (which need not be saved), and its
    RGB histogram."""
    source = develop_source(conn, asset_id)
    try:
        image = engine.develop(source.path, source.format, recipe, edge)
    except engine.DevelopError as exc:
        raise DevelopUnavailableError(f"Cannot develop the photo: {exc}") from exc
    out = io.BytesIO()
    image.save(out, "JPEG", quality=PREVIEW_QUALITY)
    return out.getvalue(), engine.histogram(image)
