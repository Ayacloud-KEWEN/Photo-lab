"""Database backup and restore (ADR-024)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.db.migrator import load_migrations, migrate
from lumen.services import backups
from tests.test_develop import NOW, add_photo


@pytest.fixture
def photos(conn: sqlite3.Connection, tmp_path: Path) -> list[int]:
    root = tmp_path / "Photos"
    root.mkdir()
    conn.execute(
        "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
        "VALUES (1, ?, ?, 'Photos', ?, ?)",
        (str(root), str(root).lower(), NOW, NOW),
    )
    return [add_photo(conn, root, f"IMG_000{i}.JPG") for i in range(3)]


def rating(client: TestClient, asset_id: int) -> int:
    return int(client.get(f"/api/v1/assets/{asset_id}").json()["rating"])


def test_backup_and_restore_bring_back_the_library(
    client: TestClient, settings: Settings, photos: list[int]
) -> None:
    client.patch(f"/api/v1/assets/{photos[0]}", json={"rating": 5})
    made = client.post("/api/v1/backups")
    assert made.status_code == 201, made.text
    backup = made.json()
    assert (backup["kind"], backup["asset_count"]) == ("manual", 3)
    assert Path(backup["path"]).parent == settings.backup_dir
    assert backup["schema_version"] == len(load_migrations())

    # Changes after the backup, including a backup setting (kept by a restore).
    client.patch(f"/api/v1/assets/{photos[0]}", json={"rating": 1})
    client.patch("/api/v1/settings", json={"backup_keep": 3, "map_online_tiles": True})
    restored = client.post("/api/v1/backups/restore", json={"name": backup["name"]})
    assert restored.status_code == 200, restored.text
    result = restored.json()
    assert result["restored"]["name"] == backup["name"]
    assert result["safety_backup"]["kind"] == "pre_restore"

    assert rating(client, photos[0]) == 5
    after = client.get("/api/v1/settings").json()
    assert (after["backup_keep"], after["map_online_tiles"]) == (3, False)

    listed = client.get("/api/v1/backups").json()
    assert listed["folder_available"] is True
    assert {item["kind"] for item in listed["items"]} == {"manual", "pre_restore"}
    # The safety backup holds the state before restoring.
    safety = client.post(
        "/api/v1/backups/restore", json={"name": result["safety_backup"]["name"]}
    )
    assert safety.status_code == 200
    assert rating(client, photos[0]) == 1


def test_restore_upgrades_an_older_backup(
    client: TestClient, settings: Settings, photos: list[int], tmp_path: Path
) -> None:
    older = tmp_path / "older.db"
    migrate(Database(older), migrations=load_migrations()[:-1])
    restored = client.post("/api/v1/backups/restore", json={"path": str(older)})
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"]["schema_version"] == len(load_migrations()) - 1
    assert restored.json()["schema_version"] == len(load_migrations())
    assert client.get("/api/v1/assets", params={"limit": 10}).json()["items"] == []


def test_restore_refuses_files_it_cannot_use(
    client: TestClient, settings: Settings, photos: list[int], tmp_path: Path
) -> None:
    text = tmp_path / "notes.db"
    text.write_text("not a database", encoding="utf-8")
    assert client.post("/api/v1/backups/restore", json={"path": str(text)}).status_code == 400

    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE things (id INTEGER)").connection.commit()
    assert client.post("/api/v1/backups/restore", json={"path": str(other)}).status_code == 400

    newer = Path(client.post("/api/v1/backups").json()["path"])
    with sqlite3.connect(newer) as db:
        db.execute(
            "INSERT INTO schema_migrations VALUES (999, 'future', 'x', '2030-01-01T00:00:00Z')"
        )
    response = client.post("/api/v1/backups/restore", json={"name": newer.name})
    assert response.status_code == 400
    assert "newer" in response.json()["error"]["message"]
    assert client.post("/api/v1/backups/restore", json={"name": "missing.db"}).status_code == 404
    assert len(client.get("/api/v1/assets", params={"limit": 10}).json()["items"]) == 3


def test_automatic_backups_are_due_by_interval_and_pruned(
    conn: sqlite3.Connection, settings: Settings, photos: list[int], tmp_path: Path
) -> None:
    folder = tmp_path / "Backups on D"
    conn.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES ('backup_folder', ?, ?), "
        "('backup_keep', '2', ?)",
        (f'"{folder.as_posix()}"', NOW, NOW),
    )
    assert backups.auto_backup_due(conn, settings)
    made = [backups.create_backup(conn, settings, "auto") for _ in range(3)]
    assert not backups.auto_backup_due(conn, settings)
    # Only the two newest automatic backups are kept; manual ones are never pruned.
    assert sorted(p.name for p in folder.glob("lumen-auto-*.db")) == sorted(
        b.name for b in made[1:]
    )
    backups.create_backup(conn, settings, "manual")
    backups.create_backup(conn, settings, "auto")
    assert len(list(folder.glob("lumen-auto-*.db"))) == 2
    assert len(list(folder.glob("lumen-backup-*.db"))) == 1

    week_ago = time.time() - 8 * 86400
    for path in folder.glob("lumen-auto-*.db"):
        os.utime(path, (week_ago, week_ago))
    assert backups.auto_backup_due(conn, settings)
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value, updated_at) "
        "VALUES ('backup_auto', 'false', ?)",
        (NOW,),
    )
    assert not backups.auto_backup_due(conn, settings)


def test_backup_settings(client: TestClient, tmp_path: Path) -> None:
    folder = str(tmp_path / "Backups")
    assert client.patch("/api/v1/settings", json={"backup_folder": folder}).json()[
        "backup_folder"
    ] == folder
    assert client.get("/api/v1/backups").json()["folder_available"] is False
    assert client.post("/api/v1/backups").status_code == 201  # creates the folder
    assert client.patch("/api/v1/settings", json={"backup_folder": ""}).json()[
        "backup_folder"
    ] is None
    assert client.patch("/api/v1/settings", json={"backup_folder": "relative"}).status_code == 422
    assert client.patch("/api/v1/settings", json={"backup_keep": 0}).status_code == 422


def test_library_views_are_cached_until_the_next_write(
    client: TestClient, conn: sqlite3.Connection, photos: list[int]
) -> None:
    first = client.get("/api/v1/assets/facets").json()
    assert first["favorites"] == 0
    # A write outside the API (no transaction) is not seen: the cached result stays...
    conn.execute("UPDATE media_assets SET is_favorite = 1 WHERE id = ?", (photos[0],))
    assert client.get("/api/v1/assets/facets").json()["favorites"] == 0
    # ...until the next committed write through the application.
    client.patch(f"/api/v1/assets/{photos[1]}", json={"rating": 3})
    assert client.get("/api/v1/assets/facets").json()["favorites"] == 1
