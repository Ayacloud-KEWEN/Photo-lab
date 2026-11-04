from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lumen.core.errors import DatabaseMigrationError
from lumen.db.connection import Database
from lumen.db.migrator import Migration, current_version, load_migrations, migrate

EXPECTED_TABLES = {
    "media_assets",
    "media_files",
    "media_metadata",
    "media_places",
    "storage_roots",
    "tasks",
    "app_settings",
    "media_locations",
    "tags",
    "media_tags",
    "asset_search",
    "embeddings",
    "ai_analysis",
    "ai_analysis_assets",
    "edit_history",
    "collections",
    "collection_items",
    "schema_migrations",
}


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'asset_search_%'"  # FTS5 shadow tables
    )
    return {row[0] for row in rows}


def test_packaged_migrations_are_contiguous() -> None:
    migrations = load_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))


def test_fresh_database_gets_initial_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    version = migrate(db)
    with db.session() as conn:
        assert version == current_version(conn) >= 1
        assert _tables(conn) == EXPECTED_TABLES
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    first = migrate(db)
    second = migrate(db)
    assert first == second
    with db.session() as conn:
        count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == first


def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    migrations = [
        Migration(1, "good", "CREATE TABLE a (id INTEGER PRIMARY KEY);"),
        Migration(
            2, "bad", "CREATE TABLE b (id INTEGER PRIMARY KEY); INSERT INTO nope VALUES (1);"
        ),
    ]
    with pytest.raises(DatabaseMigrationError, match="0002_bad"):
        migrate(db, migrations=migrations)
    with db.session() as conn:
        assert current_version(conn) == 1
        assert "a" in _tables(conn)
        assert "b" not in _tables(conn)


def test_modified_migration_is_rejected(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    migrate(db, migrations=[Migration(1, "init", "CREATE TABLE a (id INTEGER);")])
    with pytest.raises(DatabaseMigrationError, match="modified"):
        migrate(db, migrations=[Migration(1, "init", "CREATE TABLE a (id TEXT);")])


def test_newer_database_is_rejected(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    migrate(
        db,
        migrations=[
            Migration(1, "one", "CREATE TABLE a (id INTEGER);"),
            Migration(2, "two", "CREATE TABLE b (id INTEGER);"),
        ],
    )
    with pytest.raises(DatabaseMigrationError, match="newer"):
        migrate(db, migrations=[Migration(1, "one", "CREATE TABLE a (id INTEGER);")])


def test_existing_database_is_backed_up_before_migrating(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    backups = tmp_path / "backups"
    one = Migration(1, "one", "CREATE TABLE a (id INTEGER);")
    migrate(db, backup_dir=backups, migrations=[one])
    assert not backups.exists()  # nothing to protect on a fresh database

    migrate(
        db,
        backup_dir=backups,
        migrations=[one, Migration(2, "two", "CREATE TABLE b (id INTEGER);")],
    )
    [backup] = list(backups.glob("lumen-v0001-*.db"))
    with sqlite3.connect(backup) as copy:
        assert copy.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 1


def test_failed_video_frames_are_retried(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    migrate(db, migrations=load_migrations()[:4])
    now = "2026-01-01T00:00:00.000Z"
    with db.session() as conn:
        conn.execute(
            "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
            "VALUES (1, 'D:\\Photos', 'd:\\photos', 'Photos', ?, ?)",
            (now, now),
        )
        files = [  # name, state, attempts, error
            ("timed_out.mov", "error", 3, "ffmpeg timed out"),
            ("timed_out_once.mov", "pending", 1, "ffmpeg timed out"),
            ("bad_colors.mp4", "error", 3, "ffmpeg could not extract a frame: b'...'"),
            ("broken.jpg", "error", 3, "cannot decode image: truncated"),
            ("ok.jpg", "done", 1, None),
        ]
        conn.executemany(
            "INSERT INTO media_files (storage_root_id, relative_path, relative_path_key, "
            "file_name, extension, size_bytes, modified_at, created_at, updated_at, "
            "ingest_state, ingest_attempts, ingest_error) "
            "VALUES (1, ?1, ?1, ?1, 'x', 1, ?2, ?2, ?2, ?3, ?4, ?5)",
            [(name, now, state, attempts, error) for name, state, attempts, error in files],
        )

    migrate(db)
    with db.session() as conn:
        rows = {
            row[0]: tuple(row[1:])
            for row in conn.execute(
                "SELECT file_name, ingest_state, ingest_attempts, ingest_error FROM media_files"
            )
        }
        assert rows["timed_out.mov"] == ("pending", 0, None)
        assert rows["timed_out_once.mov"] == ("pending", 0, None)
        assert rows["bad_colors.mp4"] == ("pending", 0, None)
        assert rows["broken.jpg"][0] == "error"  # other failures are left alone
        assert rows["ok.jpg"] == ("done", 1, None)
        tasks = conn.execute(
            "SELECT kind, status, storage_root_id FROM tasks WHERE status = 'pending'"
        ).fetchall()
        assert [tuple(t) for t in tasks] == [("ingest_storage_root", "pending", 1)]


def test_schema_enforces_constraints(conn: sqlite3.Connection) -> None:
    now = "2026-01-01T00:00:00.000Z"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO media_assets (uuid, media_type, rating, created_at, updated_at) "
            "VALUES ('u1', 'photo', 9, ?, ?)",
            (now, now),
        )
    with pytest.raises(sqlite3.IntegrityError):
        # storage_root 999 does not exist
        conn.execute(
            "INSERT INTO media_files (storage_root_id, relative_path, relative_path_key, "
            "file_name, extension, size_bytes, modified_at, created_at, updated_at) "
            "VALUES (999, 'a.jpg', 'a.jpg', 'a.jpg', 'jpg', 1, ?, ?, ?)",
            (now, now, now),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES ('k', 'not json', ?)", (now,)
        )


def test_live_photo_candidates_are_reread(tmp_path: Path) -> None:
    db = Database(tmp_path / "lumen.db")
    migrate(db, migrations=load_migrations()[:5])
    now = "2026-01-01T00:00:00.000Z"
    with db.session() as conn:
        conn.execute(
            "INSERT INTO storage_roots (id, path, path_key, display_name, created_at, updated_at) "
            "VALUES (1, 'D:\\Photos', 'd:\\photos', 'Photos', ?, ?)",
            (now, now),
        )
        conn.executemany(
            "INSERT INTO media_files (storage_root_id, relative_path, relative_path_key, "
            "file_name, extension, size_bytes, modified_at, created_at, updated_at, "
            "ingest_state, ingest_attempts, fingerprint) "
            "VALUES (1, ?1, ?1, ?1, ?2, 1, ?3, ?3, ?3, 'done', 1, 'xxh128:00')",
            [(f"a.{ext}", ext, now) for ext in ("mov", "heic", "jpg", "png", "cr3")],
        )

    migrate(db)
    with db.session() as conn:
        states = dict(conn.execute("SELECT extension, ingest_state FROM media_files").fetchall())
        assert states == {
            "mov": "pending", "heic": "pending", "jpg": "pending", "png": "done", "cr3": "done"
        }  # fmt: skip
        fingerprints = conn.execute("SELECT DISTINCT fingerprint FROM media_files").fetchall()
        assert [f[0] for f in fingerprints] == ["xxh128:00"]  # kept: no re-hashing
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM tasks "
                "WHERE kind = 'ingest_storage_root' AND status = 'pending'"
            ).fetchone()[0]
            == 1
        )
