"""Forward-only SQL migrations (see docs/ARCHITECTURE.md, ADR-003)."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from lumen.core.errors import DatabaseMigrationError
from lumen.db.connection import Database, utc_now

logger = logging.getLogger(__name__)

_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def load_migrations(directory: Path | None = None) -> list[Migration]:
    """Load ``NNNN_name.sql`` files, from the packaged directory unless one is given."""
    if directory is None:
        files = [
            (entry.name, entry.read_text(encoding="utf-8"))
            for entry in resources.files("lumen.db").joinpath("migrations").iterdir()
            if entry.name.endswith(".sql")
        ]
    else:
        files = [(p.name, p.read_text(encoding="utf-8")) for p in directory.glob("*.sql")]

    migrations: list[Migration] = []
    for filename, sql in files:
        match = _FILENAME.match(filename)
        if not match:
            raise DatabaseMigrationError(f"Invalid migration file name: {filename}")
        migrations.append(Migration(int(match.group(1)), match.group(2), sql))

    migrations.sort(key=lambda m: m.version)
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise DatabaseMigrationError(f"Migration versions must be contiguous from 1: {versions}")
    return migrations


def _ensure_bookkeeping(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            checksum   TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _applied(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {int(row[0]): str(row[1]) for row in rows}


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_bookkeeping(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def _backup(db: Database, backup_dir: Path, from_version: int) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "").replace(".", "")
    target = backup_dir / f"lumen-v{from_version:04d}-{stamp}.db"
    with db.session() as source:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    return target


def migrate(
    db: Database,
    *,
    backup_dir: Path | None = None,
    migrations: list[Migration] | None = None,
) -> int:
    """Apply pending migrations and return the resulting schema version."""
    migrations = load_migrations() if migrations is None else migrations
    known = {m.version: m for m in migrations}
    latest = max(known, default=0)

    with db.session() as conn:
        _ensure_bookkeeping(conn)
        applied = _applied(conn)

        newer = sorted(v for v in applied if v not in known)
        if newer:
            raise DatabaseMigrationError(
                f"Database schema version {max(newer)} is newer than this application "
                f"supports ({latest}). Please update LUMEN Studio."
            )
        for version, checksum in applied.items():
            if known[version].checksum != checksum:
                raise DatabaseMigrationError(
                    f"Migration {version:04d}_{known[version].name} was modified after it "
                    "was applied. Restore the original file."
                )

        pending = [m for m in migrations if m.version not in applied]
        if not pending:
            return max(applied, default=0)

        start = max(applied, default=0)
        if start > 0 and backup_dir is not None:
            path = _backup(db, backup_dir, start)
            logger.info("database backed up before migration", extra={"backup": str(path)})

        for migration in pending:
            logger.info(
                "applying migration",
                extra={"version": migration.version, "migration": migration.name},
            )
            # executescript() would auto-commit, so the transaction is part of the script.
            script = (
                "BEGIN IMMEDIATE;\n"
                f"{migration.sql}\n;\n"
                "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                f"VALUES ({migration.version}, '{migration.name}', "
                f"'{migration.checksum}', '{utc_now()}');\n"
                "COMMIT;"
            )
            try:
                conn.executescript(script)
            except sqlite3.Error as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise DatabaseMigrationError(
                    f"Migration {migration.version:04d}_{migration.name} failed: {exc}"
                ) from exc

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise DatabaseMigrationError(f"Foreign key violations after migration: {violations}")

        return latest
