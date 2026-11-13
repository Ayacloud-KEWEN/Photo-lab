"""Browsing the library by its folders on disk, and finding folders by name."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen.app import create_app
from lumen.core.config import Settings
from tests.conftest import TOKEN
from tests.media_factory import make_jpeg
from tests.test_pipeline import wait_idle


def _names(client: TestClient, **params: object) -> list[str]:
    items = client.get("/api/v1/assets", params={"limit": 100, **params}).json()["items"]
    return sorted(item["file_name"] for item in items)


def test_browse_and_filter_by_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen.api.v1 import assets as assets_api

    shown: list[Path] = []
    monkeypatch.setattr(assets_api, "reveal_in_explorer", shown.append)
    photos = tmp_path / "Photos"
    for rel, day in [
        ("root.jpg", 1), ("2024/c.jpg", 2), ("2024/Japan/a.jpg", 3),
        ("2024/Japan/Tokyo/b.jpg", 4), ("2024/Japan/Tokyo/b2.jpg", 5), ("2023/Swiss/d.jpg", 6),
    ]:  # fmt: skip
        make_jpeg(photos / rel, taken=f"2024:05:0{day} 10:00:00")
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        root = client.post("/api/v1/storage-roots", json={"path": str(photos)}).json()["id"]
        wait_idle(app.state.db)

        top = client.get("/api/v1/folders", params={"storage_root_id": root}).json()["items"]
        assert [
            (f["name"], f["path"], f["count"], f["direct"], f["has_children"]) for f in top
        ] == [
            ("2023", "2023", 1, 0, True),
            ("2024", "2024", 4, 1, True),
        ]
        assert top[1]["cover"]["file_name"] == "b2.jpg"  # its newest photo
        inner = client.get(
            "/api/v1/folders", params={"storage_root_id": root, "path": r"2024\Japan"}
        ).json()["items"]
        assert [(f["name"], f["path"], f["count"], f["has_children"]) for f in inner] == [
            ("Tokyo", "2024/Japan/Tokyo", 2, False),
        ]

        # The library filtered by a folder: with its subfolders, or only what is right in it.
        assert _names(client, storage_root_id=root, folder="2024/japan") == [
            "a.jpg",
            "b.jpg",
            "b2.jpg",
        ]
        assert _names(client, storage_root_id=root, folder="2024/Japan", subfolders=False) == [
            "a.jpg"
        ]
        assert _names(client, storage_root_id=root, folder="/", subfolders=False) == ["root.jpg"]
        assert _names(client, storage_root_id=root, folder="2024", q="b2") == ["b2.jpg"]
        assert _names(client, storage_root_id=root, folder="20") == []  # not a name prefix

        found = client.get("/api/v1/folders/search", params={"q": "o"}).json()["items"]
        assert [(f["name"], f["path"]) for f in found] == [("Tokyo", "2024/Japan/Tokyo")]
        found = client.get("/api/v1/folders/search", params={"q": "20"}).json()["items"]
        assert [f["name"] for f in found] == ["2024", "2023"]
        assert client.get("/api/v1/folders", params={"storage_root_id": 99}).status_code == 404

        reveal = "/api/v1/folders/reveal"
        assert (
            client.post(reveal, params={"storage_root_id": root, "path": "2024/Japan"}).status_code
            == 204
        )
        assert shown == [(photos / "2024" / "Japan").resolve()]
        outside = client.post(reveal, params={"storage_root_id": root, "path": "../.."})
        assert outside.status_code == 404 and len(shown) == 1
