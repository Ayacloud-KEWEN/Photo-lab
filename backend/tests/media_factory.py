"""Generates small but real media files for tests (and for manual end-to-end checks).

Run directly to create a sample library::

    python -m tests.media_factory <output-dir>
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

EXIF_IFD = 0x8769
GPS_IFD = 0x8825


def make_jpeg(
    path: Path,
    *,
    size: tuple[int, int] = (600, 400),
    color: tuple[int, int, int] = (200, 120, 40),
    taken: str | None = "2024:05:01 10:22:33",
    make: str = "Canon",
    model: str = "EOS R5",
    orientation: int | None = None,
    gps: tuple[float, float] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color)
    # A marker in the top-left corner makes orientation visible in the output.
    image.paste((255, 255, 255), (0, 0, size[0] // 4, size[1] // 4))
    exif = Image.Exif()
    exif[0x010F] = make
    exif[0x0110] = model
    if orientation:
        exif[0x0112] = orientation
    if taken:
        ifd = exif.get_ifd(EXIF_IFD)
        ifd[0x9003] = taken  # DateTimeOriginal
        ifd[0x829D] = 2.8  # FNumber
        ifd[0x8827] = 400  # ISO
        ifd[0x920A] = 35.0  # FocalLength
    if gps:
        lat, lon = gps
        gps_ifd = exif.get_ifd(GPS_IFD)
        gps_ifd[1] = "N" if lat >= 0 else "S"
        gps_ifd[2] = _dms(abs(lat))
        gps_ifd[3] = "E" if lon >= 0 else "W"
        gps_ifd[4] = _dms(abs(lon))
    image.save(path, "JPEG", quality=90, exif=exif)
    return path


def _dms(value: float) -> tuple[float, float, float]:
    degrees = int(value)
    minutes_full = (value - degrees) * 60
    minutes = int(minutes_full)
    return (float(degrees), float(minutes), round((minutes_full - minutes) * 60, 4))


def make_png(path: Path, size: tuple[int, int] = (320, 240)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (30, 140, 200, 180)).save(path, "PNG")
    return path


def make_heic(path: Path, size: tuple[int, int] = (640, 480)) -> Path:
    import pillow_heif

    pillow_heif.register_heif_opener()
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[0x010F] = "Apple"
    exif[0x0110] = "iPhone 15 Pro"
    exif.get_ifd(EXIF_IFD)[0x9003] = "2023:08:15 18:05:00"
    Image.new("RGB", size, (90, 160, 90)).save(path, "HEIF", exif=exif.tobytes())
    return path


def make_video(
    path: Path,
    *,
    seconds: int = 2,
    creation_time: str = "2024-06-01T09:30:00Z",
    audio: bool = False,
) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to generate videos")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-v", "error", "-y", "-f", "lavfi",
            "-i", f"testsrc=duration={seconds}:size=320x240:rate=25",
            *(["-f", "lavfi", "-i", f"sine=duration={seconds}", "-c:a", "aac"] if audio else []),
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            "-metadata", f"creation_time={creation_time}", str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


def make_xmp(*, rating: int, keywords: list[str]) -> str:
    """An XMP sidecar as written by Lightroom (rating + keywords)."""
    items = "".join(f"<rdf:li>{keyword}</rdf:li>" for keyword in keywords)
    return (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
        f'xmlns:dc="http://purl.org/dc/elements/1.1/" xmp:Rating="{rating}">'
        f"<dc:subject><rdf:Bag>{items}</rdf:Bag></dc:subject>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )


def make_sample_library(root: Path) -> dict[str, Path]:
    """A small library exercising pairing, sidecars, duplicates, Unicode names and video."""
    files = {
        "portrait": make_jpeg(
            root / "2024" / "05" / "IMG_0001.JPG", orientation=6, gps=(31.2304, 121.4737)
        ),
        "landscape": make_jpeg(
            root / "2024" / "05" / "IMG_0002.jpg", taken="2024:05:02 08:00:00", color=(40, 90, 200)
        ),
        "unicode": make_jpeg(root / "旅行" / "西湖 日落.jpg", taken="2023:10:01 17:45:00"),
        "heic": make_heic(root / "phone" / "IMG_5001.HEIC"),
        "png": make_png(root / "exports" / "poster.png"),
        "video": make_video(root / "video" / "clip.mp4"),
        "mov": make_video(root / "video" / "clip2.mov", seconds=1),
    }
    # The same JPEG copied to another folder: a duplicate.
    duplicate = root / "backup" / "IMG_0002_copy.jpg"
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(files["landscape"], duplicate)
    files["duplicate"] = duplicate
    # An XMP sidecar next to a photo.
    sidecar = root / "2024" / "05" / "IMG_0002.xmp"
    sidecar.write_text(make_xmp(rating=4, keywords=["旅行", "Landscape"]), encoding="utf-8")
    files["sidecar"] = sidecar
    # Ignored: unsupported type and hidden folder.
    (root / "notes.txt").write_text("not media", encoding="utf-8")
    make_jpeg(root / ".thumbnails" / "hidden.jpg")
    return files


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample-library")
    for name, path in make_sample_library(target).items():
        print(f"{name:10} {path}")
