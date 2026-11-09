"""The LUT library: importing .cube files, listing and editing them (ADR-039)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from lumen.core.errors import LumenError, NotFoundError
from lumen.db.connection import transaction, utc_now
from lumen.develop import lut
from lumen.schemas.luts import Lut, LutImport, LutImportResult, LutList, LutUpdate

MAX_FILE_BYTES = 64 * 1024 * 1024  # a 129-point LUT is ~60 MB of text


def _references(conn: sqlite3.Connection) -> tuple[Counter[str], set[str]]:
    """How many assets use each LUT now, and every LUT any edit step refers to (undo
    and history must keep rendering, so those files are never deleted)."""
    current: Counter[str] = Counter()
    for row in conn.execute(
        """
        SELECT substr(json_extract(e.recipe, '$.lut'), 1, 16) FROM media_assets a
        JOIN edit_history e ON e.id = a.current_edit_id
        WHERE json_extract(e.recipe, '$.lut') IS NOT NULL
        """
    ):
        current[row[0]] += 1
    anywhere = {
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT substr(json_extract(recipe, '$.lut'), 1, 16) FROM edit_history "
            "WHERE json_extract(recipe, '$.lut') IS NOT NULL"
        )
    }
    return current, anywhere


def _model(row: sqlite3.Row, used: Counter[str]) -> Lut:
    return Lut(
        id=row["id"],
        ref=lut.ref_of(row["id"], row["color_space"]),
        name=row["name"],
        pack=row["pack"],
        color_space=row["color_space"],
        kind=row["kind"],
        size=row["size"],
        hidden=bool(row["hidden"]),
        used=used.get(row["id"], 0),
    )


def list_luts(conn: sqlite3.Connection) -> LutList:
    used, _ = _references(conn)
    rows = conn.execute("SELECT * FROM luts ORDER BY pack COLLATE NOCASE, name COLLATE NOCASE")
    return LutList(items=[_model(row, used) for row in rows])


def get_lut(conn: sqlite3.Connection, lut_id: str) -> Lut:
    row = conn.execute("SELECT * FROM luts WHERE id = ?", (lut_id,)).fetchone()
    if row is None:
        raise NotFoundError("LUT not found", details={"id": lut_id})
    used, _ = _references(conn)
    return _model(row, used)


def _cube_files(path: Path) -> list[tuple[Path, Path]]:
    """(file, the folder it was found under) for every .cube file, macOS litter skipped."""
    if path.is_file():
        return [(path, path.parent)] if path.suffix.lower() == ".cube" else []
    found = []
    for root, folders, files in os.walk(path):
        folders[:] = [f for f in folders if f != "__MACOSX" and not f.startswith(".")]
        for name in files:
            if name.lower().endswith(".cube") and not name.startswith("._"):
                found.append((Path(root) / name, path))
    return sorted(found)


def import_luts(conn: sqlite3.Connection, body: LutImport) -> LutImportResult:
    store = lut.store_folder()
    store.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    already = 0
    failed: list[str] = []
    for raw in body.paths:
        path = Path(raw.strip())
        if not path.is_absolute() or not path.exists():
            failed.append(f"{raw}: not found")
            continue
        for file, root in _cube_files(path):
            relative = file.relative_to(root) if file != root else Path(file.name)
            try:
                if file.stat().st_size > MAX_FILE_BYTES:
                    raise lut.LutError("file too large")
                data = file.read_bytes()
                cube = lut.parse_cube(data)
            except (OSError, lut.LutError) as exc:
                failed.append(f"{relative}: {exc}")
                continue
            lut_id = lut.content_id(data)
            if conn.execute("SELECT 1 FROM luts WHERE id = ?", (lut_id,)).fetchone():
                already += 1
                continue
            _write(store / f"{lut_id}.cube", data)
            pack = relative.parts[0] if len(relative.parts) > 1 else root.name or None
            space = "p3" if "p3" in file.stem.lower().replace(" ", "") else body.color_space
            with transaction(conn):
                conn.execute(
                    """
                    INSERT INTO luts (id, name, pack, color_space, kind, size, source_path,
                                      created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lut_id, file.stem.strip(), pack, space,
                        lut.kind_of(relative.as_posix()), cube.size, str(file), utc_now(),
                    ),
                )  # fmt: skip
            imported.append(lut_id)
    if not imported and not already and not failed:
        raise LumenError("No .cube files were found there")
    used, _ = _references(conn)
    rows = [
        conn.execute("SELECT * FROM luts WHERE id = ?", (lut_id,)).fetchone() for lut_id in imported
    ]
    return LutImportResult(
        imported=len(imported),
        already=already,
        failed=failed[:100],
        items=[_model(row, used) for row in rows],
    )


def _write(target: Path, data: bytes) -> None:
    if target.exists():
        return  # same content (the name is its hash)
    handle, temp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)


def update_lut(conn: sqlite3.Connection, lut_id: str, body: LutUpdate) -> Lut:
    get_lut(conn, lut_id)
    changes = body.model_dump(exclude_none=True)
    if changes:
        columns = ", ".join(f"{key} = ?" for key in changes)
        values = [int(v) if isinstance(v, bool) else v for v in changes.values()]
        with transaction(conn):
            conn.execute(f"UPDATE luts SET {columns} WHERE id = ?", (*values, lut_id))
    return get_lut(conn, lut_id)


def delete_lut(conn: sqlite3.Connection, lut_id: str) -> bool:
    """Remove a LUT; one that an edit (or its history) uses is hidden instead, so those
    photos keep their look. Returns whether it was really deleted."""
    get_lut(conn, lut_id)
    _, anywhere = _references(conn)
    with transaction(conn):
        if lut_id in anywhere:
            conn.execute("UPDATE luts SET hidden = 1 WHERE id = ?", (lut_id,))
            return False
        conn.execute("DELETE FROM luts WHERE id = ?", (lut_id,))
    (lut.store_folder() / f"{lut_id}.cube").unlink(missing_ok=True)
    return True
