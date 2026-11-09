"""3D LUTs (ADR-039): reading .cube files, grading pictures and videos, the LUT library."""

from __future__ import annotations

import io
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.develop import engine, lut
from lumen.develop.recipe import EditRecipe, VideoRecipe
from lumen.develop.video import VideoOptions, build_command
from tests.conftest import TOKEN
from tests.media_factory import make_jpeg, make_video
from tests.test_pipeline import wait_idle

Mapping = Callable[[np.ndarray, np.ndarray, np.ndarray], tuple[np.ndarray, ...]]


def cube_text(size: int, mapping: Mapping, title: str = "test") -> str:
    """A .cube file of ``mapping`` (red changes fastest, as the format says)."""
    lines = [f'TITLE "{title}"', "# a comment", f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0 0 0",
             "DOMAIN_MAX 1 1 1"]  # fmt: skip
    steps = np.linspace(0, 1, size)
    for b in steps:
        for g in steps:
            for r in steps:
                out = mapping(np.array(r), np.array(g), np.array(b))
                lines.append(" ".join(f"{float(v):.6f}" for v in out))
    return "\n".join(lines) + "\n"


def identity(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, ...]:
    return r, g, b


def invert(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, ...]:
    return 1 - r, 1 - g, 1 - b


def warm(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, ...]:
    return np.minimum(r * 1.2, 1), g, b * 0.8


def pixels(seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).random((60, 80, 3)).astype(np.float32)


# --- Reading .cube files ----------------------------------------------------------------------


def test_parse_cube() -> None:
    cube = lut.parse_cube(cube_text(5, invert, "Night").encode())
    assert (cube.title, cube.size, cube.table.shape) == ("Night", 5, (5, 5, 5, 3))
    # Red changes fastest: the entry after the first is (r = 1/4, 0, 0) inverted.
    assert np.allclose(cube.table[0, 0, 1], [0.75, 1, 1])
    with pytest.raises(lut.LutError, match="1D"):
        lut.parse_cube(b"LUT_1D_SIZE 4\n0 0 0\n")
    with pytest.raises(lut.LutError, match="entries"):
        lut.parse_cube(b"LUT_3D_SIZE 2\n0 0 0\n1 1 1\n")
    with pytest.raises(lut.LutError, match="no LUT_3D_SIZE"):
        lut.parse_cube(b"0 0 0\n")


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("Lens Distortions - Finishing LUTS/LD - Pacific Coast 2.cube", "look"),
        ("Hollywood/Logan.cube", "look"),
        ("Hollywood/No Time to Die.cube", "look"),
        ("Film Looks/Kodak2393 - Rec709.cube", "look"),
        ("Looks/M31 - Rec.709.cube", "look"),
        ("Film Looks/Kodak2393 - LOG.cube", "log"),
        ("科幻片 Log LUT/星际穿越Interstellar - Log-C.cube", "log"),
        ("Apple Log To Rec709.cube", "log"),
        ("巴高司影视LUT_01_AlogIN.cube", "log"),
        ("FilmLook_1_Vision_Slog2_G11.cube", "log"),
        ("Phntm_ARRI_Jamaica_G11_Sl2sg3cine.cube", "log"),
        ("Canon_LOG2_Rec709_WDR.cube", "log"),
        ("GH4 Cinelike D to Rec709.cube", "log"),
        ("CineStyle S Curve.cube", "log"),
        ("ATOMOS Pre-LUT.cube", "log"),
        ("7. FLOG TO AROUND THE WORLD .CUBE", "log"),
        ("BT2020-BT709/Rec2020ToRec709_CSTDefault.cube", "transform"),
    ],
)
def test_kind_from_the_name(path: str, kind: str) -> None:
    assert lut.kind_of(path) == kind


# --- Grading ----------------------------------------------------------------------------------


def test_identity_and_inverse() -> None:
    image = pixels()
    same = lut.parse_cube(cube_text(9, identity).encode())
    assert np.abs(lut.apply(image, same, "rec709", "srgb", 1) - image).max() < 1e-5
    inverse = lut.parse_cube(cube_text(9, invert).encode())
    assert np.abs(lut.apply(image, inverse, "rec709", "srgb", 1) - (1 - image)).max() < 1e-5
    half = lut.apply(image, inverse, "rec709", "srgb", 0.5)
    assert np.abs(half - 0.5).max() < 1e-5  # halfway between x and 1 - x


def test_torch_and_numpy_agree() -> None:
    if lut._torch() is None:
        pytest.skip("torch is not installed")
    image = pixels(1)
    cube = lut.parse_cube(cube_text(17, warm).encode())
    assert np.abs(lut._apply_numpy(image, cube) - lut.apply_cube(image, cube)).max() < 1e-5


def test_a_p3_picture_through_a_rec709_lut_keeps_its_colours() -> None:
    # A saturated P3 green lies outside Rec.709: an identity LUT must leave it as it is.
    image = np.zeros((4, 4, 3), np.float32)
    image[..., 1] = 0.9
    image[0, 0] = (0.5, 0.5, 0.5)
    same = lut.parse_cube(cube_text(17, identity).encode())
    out = lut.apply(image, same, "rec709", "p3", 1)
    assert np.abs(out - image).max() < 2e-3
    # A warming LUT made for Rec.709 still warms a P3 picture.
    grey = np.full((2, 2, 3), 0.5, np.float32)
    warmed = lut.apply(grey, lut.parse_cube(cube_text(17, warm).encode()), "rec709", "p3", 1)
    assert warmed[0, 0, 0] > 0.55 > warmed[0, 0, 2]


def test_the_engine_grades_after_the_colour_settings(tmp_path: Path) -> None:
    lut.configure(tmp_path)
    data = cube_text(9, invert).encode()
    lut_id = lut.content_id(data)
    (tmp_path / f"{lut_id}.cube").write_bytes(data)
    base = np.full((10, 10, 3), 0.25, np.float32)
    graded = engine.render(base, EditRecipe(lut=lut.ref_of(lut_id, "rec709")))
    assert np.allclose(graded, 0.75, atol=1e-4)
    softer = engine.render(base, EditRecipe(lut=lut.ref_of(lut_id, "rec709"), lut_strength=50))
    assert np.allclose(softer, 0.5, atol=1e-4)
    with pytest.raises(engine.DevelopError, match="missing"):
        engine.render(base, EditRecipe(lut="0" * 16 + ".rec709"))
    # Older edits keep their hash: the new fields are left out at their defaults.
    assert "lut" not in EditRecipe(exposure=1).canonical_json()


def test_video_export_grades_with_lut3d(tmp_path: Path) -> None:
    lut.configure(tmp_path / "Lumen Data")
    recipe = VideoRecipe(lut="0123456789abcdef.rec709")
    copy = VideoOptions(mode="copy", include_metadata=False, include_location=False)
    command = build_command("ffmpeg", Path("in.mov"), Path("out.mp4"), recipe, copy)
    filters = command[command.index("-vf") + 1]
    assert "libx264" in command  # a LUT needs re-encoding, whatever the option
    assert "lut3d=file='" in filters and "0123456789abcdef.cube'" in filters
    assert "\\:" in filters or ":" not in str(tmp_path)[:2]  # the drive colon is escaped
    half = build_command(
        "ffmpeg", Path("in.mov"), Path("out.mp4"),
        VideoRecipe(lut="0123456789abcdef.rec709", lut_strength=40), copy,
    )  # fmt: skip
    # The graded picture goes first: blend's opacity is that of its first input.
    assert (
        "[lumen_g][lumen_a]blend=all_mode=normal:all_opacity=0.400" in half[half.index("-vf") + 1]
    )


# --- The library and the API ------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        yield test_client


def write_pack(folder: Path) -> None:
    (folder / "Pack A" / "Looks").mkdir(parents=True)
    (folder / "Pack A" / "Looks" / "Night.cube").write_text(cube_text(5, invert))
    (folder / "Pack A" / "Looks" / "Warm P3.cube").write_text(cube_text(5, warm))
    (folder / "Pack A" / "Spare").mkdir()
    (folder / "Pack A" / "Spare" / "Night again.cube").write_text(cube_text(5, invert))  # same
    (folder / "Pack A" / "Sunset - Log-C.cube").write_text(cube_text(5, warm, "sun"))
    (folder / "Pack A" / "broken.cube").write_text("LUT_3D_SIZE 4\n0 0 0\n")
    (folder / "__MACOSX").mkdir()
    (folder / "__MACOSX" / "._Night.cube").write_bytes(b"\x00\x05")
    (folder / "Single.cube").write_text(cube_text(3, identity))


def test_importing_a_folder(client: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "LUT"
    write_pack(folder)
    result = client.post("/api/v1/luts/import", json={"paths": [str(folder)]}).json()
    assert (result["imported"], result["already"]) == (4, 1)
    assert len(result["failed"]) == 1 and "broken.cube" in result["failed"][0]
    items = {item["name"]: item for item in client.get("/api/v1/luts").json()["items"]}
    assert set(items) == {"Night", "Warm P3", "Sunset - Log-C", "Single"}
    assert items["Night"]["pack"] == "Pack A" and items["Single"]["pack"] == "LUT"
    assert items["Sunset - Log-C"]["kind"] == "log" and items["Night"]["kind"] == "look"
    assert items["Warm P3"]["color_space"] == "p3"  # said in its name
    night = items["Night"]
    assert night["ref"] == f"{night['id']}.rec709"
    copied = tmp_path / "data" / "luts" / f"{night['id']}.cube"
    assert copied.is_file()

    again = client.post("/api/v1/luts/import", json={"paths": [str(folder / "Single.cube")]})
    assert again.json()["already"] == 1
    missing = client.post("/api/v1/luts/import", json={"paths": [str(tmp_path / "nope")]})
    assert missing.json()["failed"] == [f"{tmp_path / 'nope'}: not found"]

    changed = client.patch(f"/api/v1/luts/{night['id']}", json={"color_space": "p3"}).json()
    assert changed["ref"] == f"{night['id']}.p3"


def test_grading_a_photo_and_deleting_luts(client: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "LUT"
    write_pack(folder)
    client.post("/api/v1/luts/import", json={"paths": [str(folder)]})
    items = {item["name"]: item for item in client.get("/api/v1/luts").json()["items"]}
    photos = tmp_path / "Photos"
    make_jpeg(photos / "grey.jpg", color=(64, 64, 64))
    client.post("/api/v1/storage-roots", json={"path": str(photos)})
    wait_idle(client.app.state.db)  # type: ignore[attr-defined]
    asset = client.get("/api/v1/assets").json()["items"][0]["id"]

    # The develop grid's small preview, as an <img> asks for it.
    night = items["Night"]
    preview = TestClient(client.app).get(
        f"/api/v1/assets/{asset}/lut-preview",
        params={"lut": night["ref"], "token": TOKEN},
    )
    assert preview.status_code == 200
    with Image.open(io.BytesIO(preview.content)) as image:
        assert max(image.size) == 256
        assert np.asarray(image.convert("RGB")).mean() > 150  # dark grey turned light

    state = client.put(f"/api/v1/assets/{asset}/edit", json={"lut": night["ref"]}).json()
    thumb = client.get(
        f"/api/v1/assets/{asset}/thumbnail", params={"v": state["rendition_version"]}
    )
    with Image.open(io.BytesIO(thumb.content)) as image:
        assert np.asarray(image.convert("RGB")).mean() > 150
    used = {i["name"]: i["used"] for i in client.get("/api/v1/luts").json()["items"]}
    assert used["Night"] == 1

    # A LUT an edit uses is only hidden; an unused one is deleted with its file.
    assert client.delete(f"/api/v1/luts/{night['id']}").status_code == 204
    hidden = {i["name"]: i for i in client.get("/api/v1/luts").json()["items"]}
    assert hidden["Night"]["hidden"] is True
    single = items["Single"]
    client.delete(f"/api/v1/luts/{single['id']}")
    assert "Single" not in {i["name"] for i in client.get("/api/v1/luts").json()["items"]}
    assert not (tmp_path / "data" / "luts" / f"{single['id']}.cube").exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_grading_a_video(client: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "LUT"
    write_pack(folder)
    client.post("/api/v1/luts/import", json={"paths": [str(folder)]})
    night = next(i for i in client.get("/api/v1/luts").json()["items"] if i["name"] == "Night")
    videos = tmp_path / "Videos"
    make_video(videos / "clip.mp4", seconds=2)
    client.post("/api/v1/storage-roots", json={"path": str(videos)})
    wait_idle(client.app.state.db)  # type: ignore[attr-defined]
    asset = client.get("/api/v1/assets").json()["items"][0]["id"]
    before = TestClient(client.app).get(
        f"/api/v1/assets/{asset}/video-preview", params={"time_ms": 500, "token": TOKEN}
    )
    client.put(f"/api/v1/assets/{asset}/video-edit", json={"lut": night["ref"]})
    after = TestClient(client.app).get(
        f"/api/v1/assets/{asset}/video-preview", params={"time_ms": 500, "token": TOKEN}
    )

    def mean(response: object) -> float:
        with Image.open(io.BytesIO(response.content)) as image:  # type: ignore[attr-defined]
            return float(np.asarray(image.convert("RGB")).mean())

    assert abs(mean(before) + mean(after) - 255) < 20  # inverted

    out = tmp_path / "Exports"
    out.mkdir()
    task = client.post("/api/v1/exports", json={"asset_ids": [asset], "destination": str(out)})
    wait_idle(client.app.state.db)  # type: ignore[attr-defined]
    result = client.get(f"/api/v1/exports/{task.json()['task']['id']}").json()["result"]
    assert result["exported"] == 1, result
    assert [p.suffix for p in out.iterdir()] == [".mp4"]  # re-encoded for the LUT
