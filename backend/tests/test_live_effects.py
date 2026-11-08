"""Live Photo effects (ADR-037): a chosen frame, long exposure, loop / bounce, exports."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.develop import engine, live
from lumen.develop.recipe import EditRecipe
from lumen.develop.renditions import _FULL_NAME
from lumen.media.formats import format_for
from tests.conftest import TOKEN
from tests.media_factory import make_heic
from tests.test_pipeline import wait_idle

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg and ffprobe",
)

SIZE = (320, 240)
FRAMES = 30
FPS = 15
SQUARE = 24


def square_x(index: int) -> int:
    return 20 + index * 9


def scene(index: int, *, shake: bool = True) -> np.ndarray:
    """A textured background (moved by hand shake) with a bright square crossing it."""
    rng = np.random.default_rng(7)
    width, height = SIZE
    texture = rng.integers(40, 200, size=(height // 8 + 4, width // 8 + 4, 3), dtype=np.uint8)
    big = np.kron(texture, np.ones((8, 8, 1), dtype=np.uint8))
    dx, dy = (3 * ((index * 7) % 5 - 2), 2 * ((index * 3) % 5 - 2)) if shake else (0, 0)
    frame = big[16 + dy : 16 + dy + height, 16 + dx : 16 + dx + width].copy()
    x = square_x(index)
    frame[100 : 100 + SQUARE, x : x + SQUARE] = 255
    return frame


def make_clip(path: Path, *, shake: bool = True, frames: int = FRAMES) -> Path:
    """A short clip like a Live Photo's (H.264 here; iPhones write HEVC)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b"".join(scene(i, shake=shake).tobytes() for i in range(frames))
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{SIZE[0]}x{SIZE[1]}",
            "-framerate", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv444p",
            str(path),
        ],
        input=data,
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


def clip_of(path: Path, tmp_path: Path) -> live.Clip:
    tools = live.Tools(shutil.which("ffmpeg"), shutil.which("ffprobe"), tmp_path / "cache")
    return live.Clip(path, "sha256:" + "ab" * 32, tools)


# --- Recipes --------------------------------------------------------------------------------


def test_older_edits_keep_their_hash() -> None:
    recipe = EditRecipe(exposure=0.5)
    assert "live" not in recipe.canonical_json()
    assert not recipe.uses_motion()
    frame = recipe.model_copy(update={"live_frame_ms": 1200})
    assert frame.uses_motion() and frame.content_hash() != recipe.content_hash()
    assert EditRecipe(live_effect="long_exposure").uses_motion()
    assert not EditRecipe(live_effect="loop").uses_motion()
    assert EditRecipe(live_effect="loop").content_hash() != ""  # an edit of its own
    assert frame.without_live() == recipe


def test_cache_pruning_knows_live_files() -> None:
    for name in ("ab12_f1.jpg", "ab12_e0f_f1.jpg", "ab12_lx1.png", "ab12_loop0_m1.mp4",
                 "ab12_bounce1a2b3c4d_m1.mp4"):  # fmt: skip
        assert _FULL_NAME.fullmatch(name), name
    assert not _FULL_NAME.fullmatch("ab12_t1.jpg")


# --- The clip -------------------------------------------------------------------------------


def test_parse_probe_reads_rotation_still_and_gamut() -> None:
    info = live.parse_probe(
        {
            "streams": [
                {
                    "index": 0, "codec_type": "video", "width": 1920, "height": 1440,
                    "color_primaries": "smpte432", "side_data_list": [{"rotation": -90}],
                },
                {"index": 1, "codec_type": "audio"},
                {"index": 2, "codec_type": "data", "start_time": "0.000", "duration": "3.0"},
                {"index": 3, "codec_type": "data", "start_time": "1.433", "duration": "0.0017"},
            ],
            "format": {"duration": "3.005"},
            "packets": [
                {"stream_index": 0, "pts_time": "0.066"},
                {"stream_index": 0, "pts_time": "0.000"},
                {"stream_index": 1, "pts_time": "0.010"},
                {"stream_index": 0, "pts_time": "0.033"},
                {"stream_index": 0, "pts_time": "-0.100"},  # before the edit list starts
            ],
        }
    )  # fmt: skip
    assert (info.width, info.height) == (1440, 1920)
    assert info.frame_times_ms == (0, 33, 66)
    assert info.still_ms == 1433 and info.duration_ms == 3005
    assert info.wide_gamut and info.has_audio


def test_frames_and_analysis(tmp_path: Path) -> None:
    clip = clip_of(make_clip(tmp_path / "IMG_1.MOV"), tmp_path)
    info = live.probe(clip)
    assert (info.width, info.height) == SIZE and len(info.frame_times_ms) == FRAMES
    assert not info.wide_gamut

    decoded = list(live.frames(clip))
    assert len(decoded) == FRAMES and decoded[0].shape == (SIZE[1], SIZE[0], 3)
    # The frame at a time is the one shown then: the square has moved on.
    later = live.frame_at(clip, info.frame_times_ms[10])
    assert later[110, square_x(10) + SQUARE // 2].min() > 230
    assert later[110, square_x(0) + SQUARE // 2].min() < 230

    analysis = live.analyse(clip)
    assert len(analysis.sharpness) == FRAMES and max(analysis.sharpness) == 1.0
    assert analysis.recommended_ms in info.frame_times_ms
    with Image.open(io.BytesIO(analysis.strip)) as strip:
        assert strip.height == live.STRIP_HEIGHT and strip.width >= live.STRIP_TILES * 10


def test_long_exposure_aligns_hand_shake_and_smears_motion(tmp_path: Path) -> None:
    clip = clip_of(make_clip(tmp_path / "IMG_2.MOV"), tmp_path)
    blended = live.long_exposure(clip)
    assert blended.shape == (SIZE[1], SIZE[0], 3)
    assert live.long_exposure_path(clip).exists()  # cached for the next render

    reference = scene(FRAMES // 2).astype(np.float32) / 255
    background = (slice(20, 90), slice(40, 280))  # above the square's path
    aligned_error = np.abs(blended[background] - reference[background]).mean()
    unaligned = np.mean([scene(i).astype(np.float32) / 255 for i in range(FRAMES)], axis=0)
    shaky_error = np.abs(unaligned[background] - reference[background]).mean()
    assert aligned_error < 0.03 < shaky_error

    # The square passed through: its trail is dimmer than the square in any one frame.
    trail = blended[100 : 100 + SQUARE, square_x(5) : square_x(25)]
    assert 0.2 < trail.mean() < 0.9

    again = live.long_exposure(clip)  # from the cache
    assert np.abs(again - blended).max() < 1 / 1000


def test_loop_and_bounce_sequences() -> None:
    frames = [np.full((2, 2, 3), i * 10, dtype=np.uint8) for i in range(10)]
    bounce = list(live._sequence(iter(frames), "bounce", 10))
    assert [int(f[0, 0, 0]) for f in bounce] == [*range(0, 100, 10), *range(80, 0, -10)]

    frames = [np.full((2, 2, 3), i * 10, dtype=np.uint8) for i in range(20)]
    loop = [int(f[0, 0, 0]) for f in live._sequence(iter(frames), "loop", 10)]
    # Fading over 5 frames: 5..14 as shot, then 15..19 dissolving into 0..4, so the loop
    # flows back into frame 5 where it starts again.
    assert loop == [*range(50, 150, 10), 125, 110, 95, 80, 65]

    assert len(list(live._sequence(iter(frames), "live", 10))) == 20


def test_render_motion_writes_video_and_gif(tmp_path: Path) -> None:
    clip = clip_of(make_clip(tmp_path / "IMG_3.MOV", shake=False), tmp_path)
    recipe = EditRecipe(exposure=0.5, live_effect="bounce")
    video = tmp_path / "out.mp4"
    live.render_motion(clip, recipe, video, format="mp4", edge=None)
    probed = live.parse_probe(
        json.loads(
            subprocess.run(
                [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-of", "json",
                 "-show_entries", "stream=index,codec_type,width,height:packet=stream_index,"
                 "pts_time", str(video)],
                capture_output=True, check=True,
            ).stdout
        )
    )  # fmt: skip
    assert len(probed.frame_times_ms) == 2 * FRAMES - 2
    assert (probed.width, probed.height) == SIZE

    gif = tmp_path / "out.gif"
    live.render_motion(clip, recipe, gif, format="gif", edge=160)
    assert gif.read_bytes()[:6] == b"GIF89a"
    with Image.open(gif) as image:
        assert max(image.size) == 160 and getattr(image, "n_frames", 1) > 5

    playback = live.playback(clip, recipe)
    assert playback == live.motion_path(clip, recipe) and playback.stat().st_size > 0
    # The frame chosen does not change how the clip plays: same cached file.
    assert live.motion_path(clip, recipe.model_copy(update={"live_frame_ms": 500})) == playback


def test_develop_engine_takes_the_picture_from_the_clip(tmp_path: Path) -> None:
    still = make_heic(tmp_path / "IMG_4.HEIC", size=SIZE)
    clip = clip_of(make_clip(tmp_path / "IMG_4.MOV", shake=False), tmp_path)
    fmt = format_for("heic")
    times = live.probe(clip).frame_times_ms
    frame = engine.load_picture(still, fmt, EditRecipe(live_frame_ms=times[20]), None, motion=clip)
    assert frame[110, square_x(20) + SQUARE // 2].min() > 0.9
    with pytest.raises(engine.DevelopError):
        engine.load_picture(still, fmt, EditRecipe(live_frame_ms=0), None, motion=None)
    # Clips that are not Display P3 are sRGB: no profile for a frame.
    assert engine.icc_profile(still, fmt, EditRecipe(live_frame_ms=0), clip) is None


# --- End to end -----------------------------------------------------------------------------


def test_live_effects_through_the_api(tmp_path: Path) -> None:
    phone = tmp_path / "Phone"
    make_heic(phone / "IMG_7001.HEIC", size=SIZE)
    make_clip(phone / "IMG_7001.MOV")
    make_heic(phone / "IMG_7002.HEIC", size=SIZE)  # not a Live Photo
    out = tmp_path / "Exports"
    out.mkdir()

    settings = Settings(data_dir=tmp_path / "data", log_to_file=False)
    app = create_app(settings, TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        client.post("/api/v1/storage-roots", json={"path": str(phone)})
        wait_idle(app.state.db)
        items = {i["file_name"]: i for i in client.get("/api/v1/assets").json()["items"]}
        asset = items["IMG_7001.HEIC"]
        assert asset["is_live"] and asset["live_effect"] == "live"
        assert items["IMG_7002.HEIC"]["live_effect"] is None
        base = f"/api/v1/assets/{asset['id']}"

        info = client.get(f"{base}/live").json()
        assert len(info["frames"]) == FRAMES and info["strip_tiles"] == live.STRIP_TILES
        strip = TestClient(app).get(f"{base}/live/strip", params={"token": TOKEN})
        assert strip.status_code == 200 and strip.headers["content-type"] == "image/jpeg"
        other = items["IMG_7002.HEIC"]["id"]
        assert client.get(f"/api/v1/assets/{other}/live").status_code == 409
        refused = client.put(f"/api/v1/assets/{other}/edit", json={"live_frame_ms": 0})
        assert refused.status_code == 409

        # A chosen frame becomes the photo: thumbnails, previews and the full size.
        chosen = info["frames"][20]["time_ms"]
        state = client.put(f"{base}/edit", json={"live_frame_ms": chosen}).json()
        assert state["is_edited"]
        version = state["rendition_version"]
        for variant in ("thumb", "preview", "full"):
            got = client.get(f"{base}/thumbnail", params={"variant": variant, "v": version})
            assert got.status_code == 200, variant
        preview = client.post(f"{base}/develop/preview", json={"recipe": state["recipe"]})
        with Image.open(io.BytesIO(preview.content)) as image:
            pixels = np.asarray(image.convert("RGB"))
        assert pixels[110, square_x(20) + SQUARE // 2].min() > 220

        # Long exposure, then a loop for playback.
        state = client.put(f"{base}/edit", json={"live_effect": "long_exposure"}).json()
        thumb = client.get(f"{base}/thumbnail", params={"v": state["rendition_version"]})
        assert thumb.status_code == 200
        assert list((settings.cache_dir / "renditions").glob("*/*_lx1.png"))
        assert client.get(base).json()["live_effect"] == "long_exposure"

        client.put(f"{base}/edit", json={"live_effect": "loop", "exposure": 0.3})
        motion = TestClient(app).get(f"{base}/motion", params={"token": TOKEN, "effect": "loop"})
        assert motion.status_code == 200 and motion.headers["content-type"] == "video/mp4"
        original = client.get(f"{base}/motion")
        assert original.headers["content-type"] == "video/quicktime"  # the clip as shot

        # Exports: GIF and MP4 for the Live Photo; the other photo stays a JPEG.
        for live_as in ("gif", "video", "photo"):
            task = client.post(
                "/api/v1/exports",
                json={"asset_ids": [asset["id"], other], "destination": str(out),
                      "live_as": live_as},
            ).json()  # fmt: skip
            wait_idle(app.state.db)
            result = client.get(f"/api/v1/exports/{task['task']['id']}").json()["result"]
            assert result["exported"] == 2 and not result["failed"], result
        names = sorted(p.name for p in out.iterdir())
        assert names == ["IMG_7001.gif", "IMG_7001.jpg", "IMG_7001.mp4",
                         "IMG_7002 (2).jpg", "IMG_7002 (3).jpg", "IMG_7002.jpg"], names  # fmt: skip


def test_p3_to_srgb_keeps_greys_and_widens_colours() -> None:
    grey = np.full((2, 2, 3), 128, dtype=np.uint8)
    assert np.array_equal(live.p3_to_srgb(grey), grey)
    # A P3 red is more saturated than sRGB can show: it clips to the sRGB red.
    red = np.zeros((1, 1, 3), dtype=np.uint8)
    red[..., 0] = 255
    assert live.p3_to_srgb(red)[0, 0].tolist() == [255, 0, 0]
    # A muted P3 colour becomes more saturated in sRGB numbers (same light).
    muted = np.array([[[180, 120, 100]]], dtype=np.uint8)
    out = live.p3_to_srgb(muted)[0, 0].astype(int)
    assert out[0] > 180 and out[2] <= 100
