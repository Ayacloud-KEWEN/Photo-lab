"""Non-destructive editing: recipes, the renderer, edit history and the develop API."""

from __future__ import annotations

import hashlib
import io
import sqlite3
import uuid
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.develop import engine
from lumen.develop.recipe import IDENTITY, Crop, EditRecipe
from lumen.media.formats import format_for

NOW = "2026-01-01T00:00:00.000Z"


def gradient(width: int = 320, height: int = 200) -> engine.Array:
    """Smooth colour gradients: every adjustment has something to act on."""
    xs, ys = np.meshgrid(np.linspace(0, 1, width), np.linspace(0, 1, height))
    texture = 0.08 * np.sin(xs * 80) * np.sin(ys * 50)  # local detail for clarity
    image = np.stack([xs, ys, 0.3 + 0.4 * xs * ys], axis=2) + texture[..., None]
    return np.clip(image, 0, 1).astype(np.float32)


# --- Recipes --------------------------------------------------------------------------------


def test_identity_recipe_has_no_hash() -> None:
    assert IDENTITY.is_identity()
    assert IDENTITY.content_hash() == ""
    assert EditRecipe(exposure=0.0).content_hash() == ""


def test_recipe_hash_is_stable_and_content_based() -> None:
    a = EditRecipe(exposure=0.5, crop=Crop(x=0.1, y=0, width=0.5, height=1))
    b = EditRecipe.model_validate_json(a.canonical_json())
    assert a.content_hash() == b.content_hash() != ""
    # Rounding keeps float noise from the UI out of the hash.
    assert EditRecipe(exposure=0.50001).content_hash() == EditRecipe(exposure=0.5).content_hash()
    assert EditRecipe(exposure=0.5).content_hash() != EditRecipe(exposure=0.6).content_hash()


def test_recipe_validation() -> None:
    with pytest.raises(ValueError):
        EditRecipe(exposure=9)
    with pytest.raises(ValueError):
        Crop(x=0.6, y=0, width=0.5, height=1)  # leaves the frame
    with pytest.raises(ValueError):
        EditRecipe.model_validate({"unknown": 1})


# --- Renderer -------------------------------------------------------------------------------


def test_identity_render_returns_the_base_unchanged() -> None:
    base = gradient()
    base.setflags(write=False)
    out = engine.render(base, IDENTITY)
    assert out is not base
    assert np.abs(out - base).max() < 1e-6


def test_exposure_and_white_balance() -> None:
    base = gradient() * 0.5
    brighter = engine.render(base, EditRecipe(exposure=1))
    assert brighter.mean() > base.mean() * 1.2
    darker = engine.render(base, EditRecipe(exposure=-1))
    assert darker.mean() < base.mean() * 0.8

    warm = engine.render(base, EditRecipe(temperature=60))
    ratio = lambda img: img[..., 0].mean() / img[..., 2].mean()  # noqa: E731
    assert ratio(warm) > ratio(base) * 1.1
    cool = engine.render(base, EditRecipe(temperature=-60))
    assert ratio(cool) < ratio(base) / 1.1


def test_tone_and_colour_sliders_change_the_image_and_stay_in_range() -> None:
    base = gradient()
    sliders = [
        "contrast", "highlights", "shadows", "whites", "blacks",
        "tint", "vibrance", "saturation", "clarity", "vignette",
    ]  # fmt: skip
    for name in sliders:
        for value in (-100, 100):
            out = engine.render(base, EditRecipe(**{name: value}))
            assert out.min() >= 0 and out.max() <= 1, name
            assert np.abs(out - base).mean() > 1e-3, (name, value)
    out = engine.render(base, EditRecipe(sharpness=100))
    assert out.min() >= 0 and out.max() <= 1


def test_saturation_minus_100_is_greyscale() -> None:
    out = engine.render(gradient(), EditRecipe(saturation=-100))
    assert np.abs(out[..., 0] - out[..., 1]).max() < 1e-4
    assert np.abs(out[..., 1] - out[..., 2]).max() < 1e-4


def test_vignette_darkens_the_corners_only() -> None:
    base = np.full((200, 300, 3), 0.5, dtype=np.float32)
    out = engine.render(base, EditRecipe(vignette=-100))
    assert out[0, 0].mean() < 0.3
    assert abs(out[100, 150].mean() - 0.5) < 1e-3


def test_geometry() -> None:
    base = gradient(320, 200)
    assert engine.render(base, EditRecipe(rotate=1)).shape == (320, 200, 3)
    assert engine.render(base, EditRecipe(rotate=2)).shape == (200, 320, 3)
    # Clockwise: the original's left column becomes the top row.
    turned = engine.render(base, EditRecipe(rotate=1))
    assert np.allclose(turned[0, :, :], base[::-1, 0, :])

    flipped = engine.render(base, EditRecipe(flip_horizontal=True))
    assert np.allclose(flipped, base[:, ::-1])

    cropped = engine.render(base, EditRecipe(crop=Crop(x=0.25, y=0.5, width=0.5, height=0.5)))
    assert cropped.shape == (100, 160, 3)
    assert np.allclose(cropped, base[100:200, 80:240])

    straight = engine.render(base, EditRecipe(straighten=10))
    assert straight.shape == base.shape


def test_straighten_never_shows_empty_corners() -> None:
    base = np.ones((200, 300, 3), dtype=np.float32)
    out = engine.render(base, EditRecipe(straighten=-30))
    assert out.min() > 0.99  # the zoom keeps the corners inside the photo
    assert engine.straighten_scale(300, 200, 0) == 1


def test_load_base_decodes_once_and_fits_the_edge(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (1200, 800), (200, 100, 50)).save(source)
    jpeg = format_for("jpg")
    assert jpeg is not None
    engine.clear_cache()
    base = engine.load_base(source, jpeg, 600)
    assert base.shape == (400, 600, 3)
    assert not base.flags.writeable
    assert engine.load_base(source, jpeg, 600) is base  # cached
    assert engine.load_base(source, jpeg, None).shape == (800, 1200, 3)


def test_undecodable_originals_raise_develop_error(tmp_path: Path) -> None:
    raw = tmp_path / "IMG_0001.CR2"
    raw.write_bytes(b"II*\x00 not a raw file")
    raw_format = format_for("cr2")
    assert raw_format is not None
    with pytest.raises(engine.DevelopError):
        engine.load_base(raw, raw_format, 600)


# --- History and API ------------------------------------------------------------------------


def add_photo(conn: sqlite3.Connection, root: Path, name: str, media_type: str = "photo") -> int:
    """A processed asset backed by a real JPEG; returns the asset id."""
    path = root / name
    Image.new("RGB", (800, 600), (180, 120, 60)).save(path, "JPEG")
    fingerprint = "xxh128:" + hashlib.md5(name.encode()).hexdigest()
    asset_id = conn.execute(
        "INSERT INTO media_assets (uuid, media_type, capture_time, created_at, updated_at) "
        "VALUES (?, ?, '2025-01-01T10:00:00', ?, ?)",
        (str(uuid.uuid4()), media_type, NOW, NOW),
    ).lastrowid
    file_id = conn.execute(
        """
        INSERT INTO media_files (storage_root_id, relative_path, relative_path_key, file_name,
            extension, asset_id, size_bytes, modified_at, ingest_state, fingerprint,
            mime_type, created_at, updated_at)
        VALUES (1, ?, ?, ?, 'jpg', ?, 1, ?, 'done', ?, 'image/jpeg', ?, ?)
        """,
        (name, name.lower(), name, asset_id, NOW, fingerprint, NOW, NOW),
    ).lastrowid
    conn.execute("UPDATE media_assets SET cover_file_id = ? WHERE id = ?", (file_id, asset_id))
    assert asset_id is not None
    return asset_id


@pytest.fixture
def api(client: TestClient, settings: Settings, tmp_path: Path) -> tuple[TestClient, int, int]:
    """The API with one photo and one video asset; returns (client, photo id, video id)."""
    root = tmp_path / "Photos"
    root.mkdir()
    with Database(settings.database_path).session() as conn:
        conn.execute(
            "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, "
            "updated_at) VALUES (1, ?, ?, 'Photos', ?, ?)",
            (str(root), str(root).lower(), NOW, NOW),
        )
        photo = add_photo(conn, root, "IMG_0001.JPG")
        video = add_photo(conn, root, "clip.jpg", media_type="video")
    return client, photo, video


def test_edit_history_undo_redo_and_branching(api: tuple[TestClient, int, int]) -> None:
    client, photo, _ = api
    state = client.get(f"/api/v1/assets/{photo}/edit").json()
    assert state["recipe"]["exposure"] == 0
    assert state == state | {"is_edited": False, "can_undo": False, "can_redo": False}
    assert state["source_format"] == "JPG" and not state["is_raw"]
    original_version = state["rendition_version"]

    first = client.put(f"/api/v1/assets/{photo}/edit", json={"exposure": 1}).json()
    assert first["is_edited"] and first["can_undo"] and not first["can_redo"]
    assert first["rendition_version"] != original_version
    assert [s["changes"] for s in first["steps"]] == [["exposure"]]
    # Saving the recipe already in effect adds no step.
    again = client.put(f"/api/v1/assets/{photo}/edit", json={"exposure": 1}).json()
    assert len(again["steps"]) == 1

    second = client.put(f"/api/v1/assets/{photo}/edit", json={"exposure": 1, "contrast": 20})
    assert [s["changes"] for s in second.json()["steps"]] == [["exposure"], ["contrast"]]

    undone = client.post(f"/api/v1/assets/{photo}/edit/undo").json()
    assert undone["recipe"]["contrast"] == 0 and undone["can_redo"]
    to_original = client.post(f"/api/v1/assets/{photo}/edit/undo").json()
    assert not to_original["is_edited"] and to_original["current_edit_id"] is None
    assert to_original["rendition_version"] == original_version
    assert client.post(f"/api/v1/assets/{photo}/edit/undo").json()["current_edit_id"] is None
    redone = client.post(f"/api/v1/assets/{photo}/edit/redo").json()
    assert redone["recipe"]["exposure"] == 1 and redone["recipe"]["contrast"] == 0

    # A new edit after an undo replaces the undone step.
    branched = client.put(f"/api/v1/assets/{photo}/edit", json={"exposure": 1, "vibrance": 30})
    assert [s["changes"] for s in branched.json()["steps"]] == [["exposure"], ["vibrance"]]
    assert not branched.json()["can_redo"]

    jumped = client.post(
        f"/api/v1/assets/{photo}/edit/select", json={"edit_id": first["steps"][0]["id"]}
    ).json()
    assert jumped["recipe"]["vibrance"] == 0 and len(jumped["steps"]) == 2

    # A reset is a step too; it shows the original.
    reset = client.put(f"/api/v1/assets/{photo}/edit", json={}).json()
    assert not reset["is_edited"] and reset["can_undo"]
    assert reset["rendition_version"] == original_version


def test_edits_show_up_in_lists_and_renditions(api: tuple[TestClient, int, int]) -> None:
    client, photo, _ = api
    query = {"date_from": "2000-01-01"}

    def summary() -> dict[str, object]:
        items = client.get("/api/v1/assets", params=query).json()["items"]
        return next(item for item in items if item["id"] == photo)

    def thumbnail(variant: str) -> Image.Image:
        response = client.get(f"/api/v1/assets/{photo}/thumbnail", params={"variant": variant})
        assert response.status_code == 200
        return Image.open(io.BytesIO(response.content))

    assert summary()["is_edited"] is False
    original = np.asarray(thumbnail("preview"), dtype=np.float32).mean()

    client.put(f"/api/v1/assets/{photo}/edit", json={"exposure": -2, "rotate": 1})
    edited = summary()
    assert edited["is_edited"] is True
    assert client.get(f"/api/v1/assets/{photo}").json()["is_edited"] is True
    preview = thumbnail("preview")
    assert preview.size == (600, 800)  # turned a quarter
    assert np.asarray(preview, dtype=np.float32).mean() < original * 0.7
    assert max(thumbnail("thumb").size) == 400


def test_develop_preview_renders_unsaved_recipes(api: tuple[TestClient, int, int]) -> None:
    client, photo, video = api
    response = client.post(
        f"/api/v1/assets/{photo}/develop/preview",
        json={"recipe": {"crop": {"x": 0, "y": 0, "width": 0.5, "height": 0.5}}, "edge": 400},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(response.content)).size == (200, 150)
    channels = [list(map(int, c.split(","))) for c in response.headers["x-histogram"].split(";")]
    assert [len(c) for c in channels] == [64, 64, 64]
    assert all(sum(c) == 200 * 150 for c in channels)
    # Nothing was saved.
    assert client.get(f"/api/v1/assets/{photo}/edit").json()["steps"] == []

    assert client.get(f"/api/v1/assets/{video}/edit").status_code == 409
    assert client.put(f"/api/v1/assets/{video}/edit", json={}).status_code == 409
    assert client.get("/api/v1/assets/999/edit").status_code == 404
    bad = client.post(f"/api/v1/assets/{photo}/develop/preview", json={"recipe": {}, "edge": 9})
    assert bad.status_code == 422


def test_unavailable_original_cannot_be_developed(
    api: tuple[TestClient, int, int], settings: Settings
) -> None:
    client, photo, _ = api
    with Database(settings.database_path).session() as conn:
        conn.execute("UPDATE media_files SET status = 'missing' WHERE asset_id = ?", (photo,))
    response = client.get(f"/api/v1/assets/{photo}/edit")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "develop_unavailable"


def test_full_size_renditions(api: tuple[TestClient, int, int]) -> None:
    client, photo, video = api

    def full(asset_id: int) -> Image.Image:
        response = client.get(f"/api/v1/assets/{asset_id}/thumbnail", params={"variant": "full"})
        assert response.status_code == 200
        return Image.open(io.BytesIO(response.content))

    assert full(photo).size == (800, 600)  # the original's size, not the 2048 px preview
    client.put(
        f"/api/v1/assets/{photo}/edit",
        json={"rotate": 1, "crop": {"x": 0, "y": 0, "width": 0.5, "height": 1}},
    )
    assert full(photo).size == (300, 800)  # turned, then cropped: the edit at full size
    client.put(f"/api/v1/assets/{photo}/edit", json={})
    assert full(photo).size == (800, 600)  # back to the original (cached)
    assert full(video).size == (800, 600)  # videos answer with their preview
