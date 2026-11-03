from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.db.migrator import migrate

TOKEN = "test-token"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", log_to_file=False, run_tasks=False)


@pytest.fixture
def db(settings: Settings) -> Database:
    settings.ensure_directories()
    database = Database(settings.database_path)
    migrate(database, backup_dir=settings.backup_dir)
    return database


@pytest.fixture
def conn(db: Database) -> Iterator[sqlite3.Connection]:
    with db.session() as connection:
        yield connection


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings, TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        yield test_client


@pytest.fixture
def photo_dir(tmp_path: Path) -> Path:
    """A directory with a file in it, standing in for a user's photo folder."""
    directory = tmp_path / "Photos"
    (directory / "2026").mkdir(parents=True)
    (directory / "2026" / "IMG_0001.JPG").write_bytes(b"\xff\xd8\xff\xe0original")
    return directory
