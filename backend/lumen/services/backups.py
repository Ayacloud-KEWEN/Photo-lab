"""Database backups: create, list, prune and restore (ADR-024).

A backup is a consistent copy of ``lumen.db`` made with SQLite's online backup API, so the
application keeps running. It holds everything the user did (ratings, tags, notes, edits,
portfolios, AI results); thumbnails are regenerated and the cloud API key stays in the
Windows Credential Manager.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lumen.core.config import Settings
from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import Database, transaction, utc_now
from lumen.db.migrator import check_compatible, migrate
from lumen.schemas.backups import BackupInfo, BackupKind, BackupList
from lumen.services.settings import get_settings
from lumen.tasks.runner import PermanentTaskError, TaskContext

logger = logging.getLogger(__name__)

# Settings that describe where and how to back up stay as they are when restoring.
# Where files are kept on this computer: not taken from the backup (ADR-024, ADR-031).
KEPT_ON_RESTORE = (
    "backup_auto", "backup_interval_days", "backup_keep", "backup_folder", "cache_folder",
)

_PREFIXES: dict[str, BackupKind] = {
    "lumen-backup-": "manual",
    "lumen-auto-": "auto",
    "lumen-before-restore-": "pre_restore",
    "lumen-v": "migration",  # written by the migrator before upgrading
}
_STAMP = re.compile(r"(\d{8})[-T]?(\d{6})")


class BackupError(LumenError):
    code = "backup_failed"


def backup_folder(conn: sqlite3.Connection, settings: Settings) -> Path:
    chosen = get_settings(conn).backup_folder
    return Path(chosen) if chosen else settings.backup_dir


def _kind(name: str) -> BackupKind | None:
    for prefix, kind in _PREFIXES.items():
        if name.startswith(prefix) and name.endswith(".db"):
            return kind
    return None


def _stamp() -> str:
    """Local time with milliseconds: names sort by age."""
    now = datetime.now()
    return f"{now:%Y%m%d-%H%M%S}-{now.microsecond // 1000:03d}"


def _created_at(path: Path) -> str:
    """When the backup was made: from its name, else the file's modification time."""
    found = _STAMP.search(path.name)
    if found:
        try:
            parsed = datetime.strptime(found.group(1) + found.group(2), "%Y%m%d%H%M%S")
            if path.name.startswith("lumen-v"):  # the migrator names files in UTC
                return parsed.replace(tzinfo=UTC).astimezone().replace(tzinfo=None).isoformat()
            return parsed.isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat()


def inspect(path: Path) -> BackupInfo:
    """Facts about a backup file, read without modifying it."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"Not a readable database: {exc}", details={"path": str(path)}) from exc
    try:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"schema_migrations", "media_assets"} <= tables:
            raise BackupError("Not a LUMEN Studio database", details={"path": str(path)})
        version = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        assets = conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0]
        return BackupInfo(
            name=path.name,
            path=str(path),
            kind=_kind(path.name) or "other",
            created_at=_created_at(path),
            size_bytes=path.stat().st_size,
            schema_version=int(version.fetchone()[0]),
            asset_count=int(assets),
        )
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"Not a readable database: {exc}", details={"path": str(path)}) from exc
    finally:
        conn.close()


def _copy(source: sqlite3.Connection, target: Path) -> None:
    """Copy a database to a new file (via a temporary name, so no half-written backup)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    dest = sqlite3.connect(partial)
    try:
        source.backup(dest)
        ok = dest.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        dest.close()
    if ok != "ok":
        partial.unlink(missing_ok=True)
        raise BackupError(f"The backup failed its integrity check: {ok}")
    partial.replace(target)


def create_backup(
    conn: sqlite3.Connection, settings: Settings, kind: BackupKind = "manual"
) -> BackupInfo:
    folder = backup_folder(conn, settings)
    prefix = next(p for p, k in _PREFIXES.items() if k == kind)
    stamp = _stamp()
    target = folder / f"{prefix}{stamp}.db"
    counter = 1
    while target.exists():  # two backups within a second
        counter += 1
        target = folder / f"{prefix}{stamp}-{counter}.db"
    try:
        _copy(conn, target)
    except OSError as exc:
        raise BackupError(
            f"Could not write the backup to {folder}: {exc}", details={"folder": str(folder)}
        ) from exc
    logger.info("database backed up", extra={"backup": str(target), "kind": kind})
    if kind == "auto":
        prune(folder, get_settings(conn).backup_keep)
    return inspect(target)


def prune(folder: Path, keep: int) -> list[str]:
    """Delete the oldest automatic backups beyond ``keep`` (other backups are never deleted)."""
    autos = sorted(p for p in folder.glob("lumen-auto-*.db") if p.is_file())
    removed = []
    for path in autos[: max(0, len(autos) - keep)]:
        path.unlink(missing_ok=True)
        removed.append(path.name)
    return removed


def list_backups(conn: sqlite3.Connection, settings: Settings) -> BackupList:
    folder = backup_folder(conn, settings)
    folders = [folder] if folder == settings.backup_dir else [folder, settings.backup_dir]
    items: list[BackupInfo] = []
    for directory in folders:
        if not directory.is_dir():
            continue
        for path in directory.glob("lumen-*.db"):
            if _kind(path.name) is None:
                continue
            try:
                items.append(inspect(path))
            except BackupError:
                logger.warning("unreadable backup", extra={"backup": str(path)})
    items.sort(key=lambda item: item.created_at, reverse=True)
    autos = [item.created_at for item in items if item.kind == "auto"]
    return BackupList(
        folder=str(folder),
        default_folder=str(settings.backup_dir),
        folder_available=folder.is_dir(),
        last_auto_at=max(autos) if autos else None,
        items=items,
    )


def auto_backup_due(conn: sqlite3.Connection, settings: Settings) -> bool:
    app = get_settings(conn)
    if not app.backup_auto:
        return False
    if not conn.execute("SELECT EXISTS (SELECT 1 FROM media_assets)").fetchone()[0]:
        return False  # nothing to protect yet
    folder = backup_folder(conn, settings)
    latest = max((p.stat().st_mtime for p in folder.glob("lumen-auto-*.db")), default=None)
    if latest is None:
        return True
    age = datetime.now() - datetime.fromtimestamp(latest)
    return age >= timedelta(days=app.backup_interval_days)


def find_backup(conn: sqlite3.Connection, settings: Settings, name: str) -> Path:
    """A listed backup by file name."""
    for item in list_backups(conn, settings).items:
        if item.name == name:
            return Path(item.path)
    raise NotFoundError("Backup not found", details={"name": name})


def restore(db: Database, settings: Settings, source: Path) -> tuple[BackupInfo, BackupInfo]:
    """Replace the database with a backup; returns (the backup, the safety backup made first).

    The caller pauses background tasks. The current database is backed up first, the
    backup's content is copied in page by page (other connections see it afterwards),
    then it is migrated to the current schema. Backup settings are kept.
    """
    if not source.is_file():
        raise NotFoundError("Backup file not found", details={"path": str(source)})
    info = inspect(source)
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    try:
        check = src.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise BackupError(f"The backup is damaged: {check}", details={"path": str(source)})
        try:
            check_compatible(src)
        except Exception as exc:
            raise BackupError(str(exc), details={"path": str(source)}) from exc

        with db.session() as conn:
            kept = {
                row["key"]: row["value"]
                for row in conn.execute(
                    f"SELECT key, value FROM app_settings WHERE key IN "
                    f"({','.join('?' * len(KEPT_ON_RESTORE))})",
                    KEPT_ON_RESTORE,
                )
            }
            safety = create_backup(conn, settings, "pre_restore")
            src.backup(conn)
    finally:
        src.close()

    migrate(db, backup_dir=settings.backup_dir)
    with db.session() as conn, transaction(conn):
        conn.execute(
            f"DELETE FROM app_settings WHERE key IN ({','.join('?' * len(KEPT_ON_RESTORE))})",
            KEPT_ON_RESTORE,
        )
        now = utc_now()
        for key, value in kept.items():
            conn.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
    logger.info("database restored", extra={"backup": str(source), "safety": safety.path})
    return info, safety


BACKUP_TASK = "db_backup"


def backup_task(ctx: TaskContext) -> dict[str, str]:
    """The automatic backup (queued at start-up when one is due)."""
    try:
        info = create_backup(ctx.conn, ctx.settings, "auto")
    except BackupError as exc:
        raise PermanentTaskError(exc.message) from exc
    return {"backup": info.name}
