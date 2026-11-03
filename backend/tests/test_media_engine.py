from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from lumen.media import thumbnails
from lumen.media.fingerprint import fingerprint_file
from lumen.media.formats import format_for
from lumen.media.metadata import (
    ExifToolSession,
    parse_exiftool,
    parse_ffprobe,
    run_ffprobe,
)
from lumen.media.walker import walk_media
from tests.media_factory import make_heic, make_jpeg, make_png, make_video

needs_exiftool = pytest.mark.skipif(shutil.which("exiftool") is None, reason="exiftool missing")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")


def test_formats() -> None:
    assert format_for("CR3").is_raw  # type: ignore[union-attr]
    assert format_for(".jpg").media_type == "photo"  # type: ignore[union-attr]
    assert format_for("MOV").media_type == "video"  # type: ignore[union-attr]
    assert format_for("xmp").media_type is None  # type: ignore[union-attr]
    assert format_for("txt") is None


def test_walker_finds_media_and_skips_hidden(tmp_path: Path) -> None:
    make_jpeg(tmp_path / "a" / "one.jpg")
    make_png(tmp_path / "two.PNG")
    make_jpeg(tmp_path / ".cache" / "hidden.jpg")
    make_jpeg(tmp_path / "$RECYCLE.BIN" / "trash.jpg")
    make_jpeg(tmp_path / "System Volume Information" / "sys.jpg")
    (tmp_path / "readme.txt").write_text("x")

    found = {f.relative_path.replace("\\", "/"): f for f in walk_media(tmp_path)}

    assert set(found) == {"a/one.jpg", "two.PNG"}
    assert found["two.PNG"].extension == "png"
    assert found["a/one.jpg"].size == (tmp_path / "a" / "one.jpg").stat().st_size


def test_walker_can_stop(tmp_path: Path) -> None:
    for i in range(3):
        make_png(tmp_path / f"d{i}" / "x.png")
    assert list(walk_media(tmp_path, should_stop=lambda: True)) == []


def test_fingerprint(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"x" * 10_000_000)
    b.write_bytes(b"x" * 9_999_999 + b"y")
    assert fingerprint_file(a) == fingerprint_file(a)
    assert fingerprint_file(a) != fingerprint_file(b)
    assert fingerprint_file(a).startswith("xxh128:")


def test_parse_exiftool_photo() -> None:
    meta = parse_exiftool(
        {
            "SourceFile": "x.jpg",
            "EXIF:DateTimeOriginal": "2024:05:01 10:22:33",
            "EXIF:Make": "Canon",
            "EXIF:Model": "EOS R5",
            "Composite:LensID": "RF24-70mm F2.8 L IS USM",
            "EXIF:FNumber": 2.8,
            "EXIF:ExposureTime": 0.004,
            "EXIF:ISO": 400,
            "EXIF:FocalLength": 35,
            "EXIF:Orientation": 6,
            "Composite:ImageSize": "6000 4000",
            "Composite:GPSLatitude": 31.23,
            "Composite:GPSLongitude": 121.47,
        }
    )
    assert meta.capture_time == "2024-05-01T10:22:33"
    assert (meta.width, meta.height) == (4000, 6000)  # rotated for display
    assert meta.lens_model == "RF24-70mm F2.8 L IS USM"
    assert (meta.aperture, meta.iso, meta.focal_length_mm) == (2.8, 400, 35.0)
    assert (meta.latitude, meta.longitude) == (31.23, 121.47)
    assert "SourceFile" not in meta.raw


def test_parse_exiftool_dates_and_bad_values() -> None:
    # QuickTime CreateDate is UTC and is converted to local wall-clock time.
    meta = parse_exiftool({"QuickTime:CreateDate": "2024:06:01 09:30:00", "EXIF:ISO": 0})
    expected = datetime(2024, 6, 1, 9, 30, tzinfo=UTC).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    assert meta.capture_time == expected
    assert meta.iso is None

    # The camera's own zone-tagged date is kept as written.
    meta = parse_exiftool({"QuickTime:CreationDate": "2024:06:01 17:30:00+08:00"})
    assert meta.capture_time == "2024-06-01T17:30:00"

    meta = parse_exiftool(
        {
            "EXIF:DateTimeOriginal": "0000:00:00 00:00:00",
            "Composite:GPSLatitude": 0,
            "Composite:GPSLongitude": 0,
            "EXIF:LensModel": "Unknown",
        }
    )
    assert meta.capture_time is None
    assert meta.latitude is None
    assert meta.lens_model is None


def test_parse_ffprobe() -> None:
    meta = parse_ffprobe(
        {
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                    "side_data_list": [{"rotation": -90}],
                },
            ],
            "format": {"duration": "12.5", "tags": {"creation_time": "2024-06-01T09:30:00Z"}},
        }
    )
    assert (meta.width, meta.height) == (1080, 1920)
    assert meta.video_codec == "hevc"
    assert meta.frame_rate == 29.97
    assert meta.duration_ms == 12500
    assert meta.capture_time is not None


def _render(tmp_path: Path, source: Path) -> tuple[Image.Image, Image.Image]:
    target = thumbnails.rendition_paths(tmp_path / "cache", "xxh128:" + "ab" * 16)
    media_format = format_for(source.suffix)
    assert media_format is not None
    thumbnails.render(source, media_format, target, ffmpeg=shutil.which("ffmpeg"))
    return Image.open(target.thumb), Image.open(target.preview)


def test_render_jpeg_applies_orientation(tmp_path: Path) -> None:
    source = make_jpeg(tmp_path / "p.jpg", size=(3000, 2000), orientation=6)
    thumb, preview = _render(tmp_path, source)
    assert preview.size == (1365, 2048)  # portrait, fitted to 2048
    assert max(thumb.size) == thumbnails.THUMB_EDGE
    assert thumb.width < thumb.height


def test_render_small_png_with_alpha(tmp_path: Path) -> None:
    thumb, preview = _render(tmp_path, make_png(tmp_path / "a.png", size=(120, 80)))
    assert preview.size == (120, 80)  # never upscaled
    assert thumb.mode == "RGB"


def test_render_heic(tmp_path: Path) -> None:
    _, preview = _render(tmp_path, make_heic(tmp_path / "a.heic"))
    assert preview.size == (640, 480)


@needs_ffmpeg
def test_render_video_frame(tmp_path: Path) -> None:
    _, preview = _render(tmp_path, make_video(tmp_path / "v.mp4", seconds=1))
    assert preview.size == (320, 240)


@needs_ffmpeg
@pytest.mark.parametrize(("encoder", "codec"), [("libx264", "h264"), ("libx265", "hevc")])
def test_render_video_with_reserved_color_codes(tmp_path: Path, encoder: str, codec: str) -> None:
    # Code 3 is "reserved" in H.264/HEVC; ffmpeg's filter graph refuses such streams.
    source = tmp_path / f"{codec}.mp4"
    subprocess.run(
        [
            str(shutil.which("ffmpeg")), "-v", "error", "-y", "-f", "lavfi",
            "-i", "testsrc=duration=2:size=320x240:rate=25", "-pix_fmt", "yuv420p",
            "-c:v", encoder, "-bsf:v",
            f"{codec}_metadata=colour_primaries=3:transfer_characteristics=3"
            ":matrix_coefficients=3",
            str(source),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    _, preview = _render(tmp_path, source)
    assert preview.size == (320, 240)


@needs_ffmpeg
def test_video_tools_never_inherit_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Under the desktop shell the backend's stdin is a pipe with a read always pending
    # (--watch-stdin). On Windows, ffmpeg polling an inherited copy of it (after its first
    # 0.5 s stats period, so typical 4K phone videos) blocks until the timeout.
    video = make_video(tmp_path / "v.mov", seconds=2)
    calls: list[tuple[list[str], object]] = []
    real_run = subprocess.run

    def spy(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs.get("stdin")))
        return real_run(command, **kwargs)  # type: ignore[call-overload, no-any-return]

    monkeypatch.setattr(subprocess, "run", spy)
    run_ffprobe(str(shutil.which("ffprobe")), video)
    _render(tmp_path, video)
    assert len(calls) == 2  # ffprobe, then one ffmpeg frame grab
    for command, stdin in calls:
        assert stdin == subprocess.DEVNULL, command
    assert "-nostdin" in calls[1][0]


def test_render_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not a jpeg")
    fake_raw = tmp_path / "fake.cr2"
    fake_raw.write_bytes(b"not a raw file")
    for source in (broken, fake_raw):
        with pytest.raises(thumbnails.RenderError):
            _render(tmp_path, source)


def test_render_skips_existing(tmp_path: Path) -> None:
    source = make_jpeg(tmp_path / "a.jpg")
    _render(tmp_path, source)
    source.write_bytes(b"corrupted later")
    _render(tmp_path, source)  # cached by fingerprint, not re-rendered


@needs_exiftool
def test_exiftool_session_reads_unicode_paths(tmp_path: Path) -> None:
    first = make_jpeg(tmp_path / "旅行" / "西湖 日落.jpg", taken="2023:10:01 17:45:00")
    second = make_jpeg(tmp_path / "plain.jpg", gps=(48.8584, 2.2945))
    missing = tmp_path / "missing.jpg"

    with ExifToolSession(str(shutil.which("exiftool"))) as session:
        results = session.read([first, second, missing])

    assert parse_exiftool(results[str(first)]).capture_time == "2023-10-01T17:45:00"  # type: ignore[arg-type]
    located = parse_exiftool(results[str(second)])  # type: ignore[arg-type]
    assert located.latitude == pytest.approx(48.8584, abs=1e-4)
    assert isinstance(results[str(missing)], Exception)
