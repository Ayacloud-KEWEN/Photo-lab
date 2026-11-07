"""User preferences stored in ``app_settings`` (one JSON value per field)."""

from __future__ import annotations

import json
import sqlite3

from lumen.db.connection import transaction, utc_now
from lumen.schemas.settings import AppSettings, AppSettingsUpdate


def get_settings(conn: sqlite3.Connection) -> AppSettings:
    stored = {
        row["key"]: json.loads(row["value"])
        for row in conn.execute("SELECT key, value FROM app_settings")
    }
    defaults = AppSettings().model_dump()
    return AppSettings.model_validate(
        {**defaults, **{k: stored[k] for k in defaults if k in stored}}
    )


def update_settings(conn: sqlite3.Connection, data: AppSettingsUpdate) -> AppSettings:
    now = utc_now()
    with transaction(conn):
        for key, value in data.model_dump(exclude_none=True).items():
            if key in ("backup_folder", "mapweb_url") and value == "":  # back to the default
                conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
                continue
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value,
                                                updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), now),
            )
    return get_settings(conn)
