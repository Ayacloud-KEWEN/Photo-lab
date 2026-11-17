"""Import from a phone (ADR-040): copy the photos and videos not imported yet into a folder
of the library, then scan it.

Only reads from the phone. On the computer it only creates new files in the chosen folder
(``year/year-month/``), written as ``.part`` and renamed when complete; an existing file is
never overwritten. A Live Photo's HEIC and MOV land side by side under the same name, so the
usual Live Photo pairing finds them.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from lumen.core.errors import ConflictError
from lumen.db.connection import transaction, utc_now
from lumen.media.phone import PhoneError, PhoneFile, PhoneSource, WpdSource
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext

logger = logging.getLogger(__name__)

PHONE_IMPORT_TASK = "phone_import"

# Replaced in tests by a fake phone.
SOURCE: PhoneSource = WpdSource()

# IMG_E1234.HEIC: the version edited on the iPhone (the original IMG_1234 is copied anyway).
_EDITED = re.compile(r"^IMG_E\d", re.IGNORECASE)
UNKNOWN_DATE = "未知日期"


@dataclass(frozen=True)
class Plan:
    copy: list[PhoneFile]  # not imported yet
    in_library: list[PhoneFile]  # already in the library (another way): only recorded
    done: int  # imported before


def is_edited(file: PhoneFile) -> bool:
    return bool(_EDITED.match(file.name))


def plan(
    conn: sqlite3.Connection, serial: str, files: list[PhoneFile], *, include_edited: bool
) -> Plan:
    keys = {
        row[0]
        for row in conn.execute("SELECT object_key FROM phone_imports WHERE serial = ?", (serial,))
    }
    # First import (or files imported before LUMEN did it): a file of the same name and size
    # already in the library is not copied again.
    library = {
        (str(row[0]).lower(), int(row[1]))
        for row in conn.execute(
            "SELECT file_name, size_bytes FROM media_files WHERE status = 'present'"
        )
    }
    copy, in_library, done = [], [], 0
    for file in files:
        if not include_edited and is_edited(file):
            continue
        if file.key in keys:
            done += 1
        elif (file.name.lower(), file.size) in library:
            in_library.append(file)
        else:
            copy.append(file)
    return Plan(copy, in_library, done)


def _group(files: list[PhoneFile]) -> list[list[PhoneFile]]:
    """Files sharing a name stem in a phone folder (a Live Photo's HEIC and MOV) together."""
    groups: dict[tuple[str, str], list[PhoneFile]] = defaultdict(list)
    for file in files:
        groups[(file.folder, os.path.splitext(file.name)[0].upper())].append(file)
    return list(groups.values())


def _folder(dest: Path, group: list[PhoneFile]) -> Path:
    dates = [f.created for f in group if f.created is not None]
    if not dates:
        return dest / UNKNOWN_DATE
    first = min(dates)
    return dest / f"{first:%Y}" / f"{first:%Y-%m}"


def targets(folder: Path, group: list[PhoneFile]) -> dict[str, Path | None]:
    """Where each file of a group goes (``None``: the same file is already there).

    When another file has the name, the whole group gets the same suffix (IMG_1234_2.HEIC
    and IMG_1234_2.MOV) so a Live Photo stays a pair."""
    for n in range(1, 1000):
        result: dict[str, Path | None] = {}
        clash = False
        for file in group:
            stem, ext = os.path.splitext(file.name)
            path = folder / (file.name if n == 1 else f"{stem}_{n}{ext}")
            if path.exists():
                if path.stat().st_size == file.size:
                    result[file.key] = None
                    continue
                clash = True
                break
            result[file.key] = path
        if not clash:
            return result
    raise PermanentTaskError(f"Too many files named like {group[0].name} in {folder}")


def _record(conn: sqlite3.Connection, serial: str, file: PhoneFile, path: str) -> None:
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO phone_imports
                (serial, object_key, file_name, size_bytes, path, imported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (serial, object_key) DO UPDATE SET path = excluded.path,
                                                           imported_at = excluded.imported_at
            """,
            (serial, file.key, file.name, file.size, path, utc_now()),
        )


def _scan_destination(conn: sqlite3.Connection, dest: Path) -> int | None:
    """Scan the library folder holding ``dest``, adding ``dest`` as a folder if none does."""
    from lumen.library.common import SCAN_TASK
    from lumen.schemas.storage_roots import StorageRootCreate
    from lumen.services.storage_roots import create_storage_root, path_key

    key = path_key(dest)
    for row in conn.execute("SELECT id, path_key FROM storage_roots"):
        root = str(row["path_key"])
        if key == root or key.startswith(root.rstrip(os.sep) + os.sep):
            queue.enqueue(
                conn, SCAN_TASK, storage_root_id=int(row["id"]), payload={"reason": "phone"}
            )
            return int(row["id"])
    try:
        return create_storage_root(conn, StorageRootCreate(path=str(dest))).id
    except ConflictError:  # the folder holds library folders: scan those
        logger.info("phone folder contains library folders", extra={"path": str(dest)})
        ids = []
        for row in conn.execute("SELECT id, path_key FROM storage_roots"):
            if str(row["path_key"]).startswith(key.rstrip(os.sep) + os.sep):
                queue.enqueue(
                    conn, SCAN_TASK, storage_root_id=int(row["id"]), payload={"reason": "phone"}
                )
                ids.append(int(row["id"]))
        return ids[0] if ids else None


def import_from_phone(ctx: TaskContext) -> dict[str, object]:
    payload = ctx.payload
    device, serial = str(payload["device_id"]), str(payload["serial"])
    dest = Path(str(payload["dest"]))
    include_edited = bool(payload.get("include_edited", False))
    copied = copied_bytes = 0
    try:
        with SOURCE.open(device) as session:
            ctx.progress(0, None, force=True)
            files: list[PhoneFile] = []
            for file in session.files():
                files.append(file)
                if len(files) % 100 == 0:
                    ctx.check()
            todo = plan(ctx.conn, serial, files, include_edited=include_edited)
            for file in todo.in_library:
                _record(ctx.conn, serial, file, "")
            total = sum(f.size for f in todo.copy)
            if todo.copy:
                dest.mkdir(parents=True, exist_ok=True)
            done = 0
            ctx.progress(0, total, force=True)
            for group in _group(todo.copy):
                folder = _folder(dest, group)
                folder.mkdir(parents=True, exist_ok=True)
                where = targets(folder, group)
                for file in group:
                    target = where[file.key]
                    if target is None:  # copied before (the import was stopped after it)
                        _record(ctx.conn, serial, file, str(folder / file.name))
                        done += file.size
                        continue
                    part = target.with_name(target.name + ".part")
                    try:
                        # closing(): the phone's file stream is released right away, even
                        # when the import stops in the middle of a file. part: our own file.
                        with (
                            open(part, "wb") as out,
                            contextlib.closing(session.read(file)) as chunks,
                        ):
                            for chunk in chunks:
                                out.write(chunk)
                                done += len(chunk)
                                ctx.progress(done, total)
                        os.replace(part, target)
                    finally:
                        with contextlib.suppress(FileNotFoundError):
                            part.unlink()
                    _record(ctx.conn, serial, file, str(target))
                    copied += 1
                    copied_bytes += file.size
            ctx.progress(total, total, force=True)
    except PhoneError as exc:
        raise PermanentTaskError(str(exc)) from exc
    root_id = _scan_destination(ctx.conn, dest) if copied or dest.exists() else None
    logger.info("phone import done", extra={"copied": copied, "bytes": copied_bytes})
    return {
        "copied": copied,
        "bytes": copied_bytes,
        "already": todo.done + len(todo.in_library),
        "folder": str(dest),
        "storage_root_id": root_id,
    }
