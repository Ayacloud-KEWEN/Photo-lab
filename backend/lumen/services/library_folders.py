"""The library's folders as they are on disk: browsing them and finding them by name.

Built from the paths of the files already imported (nothing is read from disk), counting
what the library shows: assets with a capture time, not rejected.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from lumen.core.errors import NotFoundError
from lumen.schemas.assets import AssetSummary, Folder, FolderList
from lumen.services.assets import folder_key, like_prefix, summaries_by_ids

MAX_FOUND = 50


@dataclass
class _Node:
    name: str
    path: str
    count: int = 0
    direct: int = 0
    cover: int | None = None
    children: set[str] = field(default_factory=set)


def _rows(conn: sqlite3.Connection, root_id: int, prefix: str) -> list[sqlite3.Row]:
    where = "c.storage_root_id = ?"
    params: list[object] = [root_id]
    if prefix:
        where += " AND c.relative_path_key LIKE ? ESCAPE '!'"
        params.append(like_prefix(prefix))
    return conn.execute(
        f"""
        SELECT a.id, c.relative_path FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.status = 'present'
        WHERE {where} AND a.capture_time IS NOT NULL AND a.cull_flag != 'reject'
        ORDER BY a.capture_time DESC
        """,
        params,
    ).fetchall()


def _parts(relative_path: str) -> list[str]:
    return [p for p in relative_path.replace("\\", "/").split("/") if p][:-1]


def _check_root(conn: sqlite3.Connection, root_id: int) -> None:
    if conn.execute("SELECT 1 FROM storage_roots WHERE id = ?", (root_id,)).fetchone() is None:
        raise NotFoundError("Library folder not found", details={"id": root_id})


def _covers(conn: sqlite3.Connection, nodes: list[_Node]) -> dict[int, AssetSummary]:
    ids = [n.cover for n in nodes if n.cover is not None]
    return {s.id: s for s in summaries_by_ids(conn, ids)}


def _to_models(conn: sqlite3.Connection, root_id: int, nodes: list[_Node]) -> FolderList:
    covers = _covers(conn, nodes)
    return FolderList(
        items=[
            Folder(
                storage_root_id=root_id,
                path=n.path,
                name=n.name,
                count=n.count,
                direct=n.direct,
                has_children=bool(n.children),
                cover=covers.get(n.cover) if n.cover is not None else None,
            )
            for n in nodes
        ]
    )


def children(conn: sqlite3.Connection, root_id: int, folder: str) -> FolderList:
    """The subfolders of ``folder`` ('' = the library folder), by name."""
    _check_root(conn, root_id)
    base = _parts(folder.replace("\\", "/").strip("/") + "/x") if folder.strip("/\\") else []
    prefix = folder_key(folder) + os.sep if base else ""
    nodes: dict[str, _Node] = {}
    for row in _rows(conn, root_id, prefix):
        parts = _parts(row["relative_path"])
        if len(parts) <= len(base):
            continue  # right in the folder
        name = parts[len(base)]
        node = nodes.get(name.casefold())
        if node is None:
            path = "/".join([*parts[: len(base)], name])
            node = nodes[name.casefold()] = _Node(name=name, path=path, cover=int(row["id"]))
        node.count += 1
        if len(parts) == len(base) + 1:
            node.direct += 1
        else:
            node.children.add(parts[len(base) + 1].casefold())
    ordered = sorted(nodes.values(), key=lambda n: n.name.casefold())
    return _to_models(conn, root_id, ordered)


def search(conn: sqlite3.Connection, text: str) -> list[Folder]:
    """Folders (of every library folder) whose name contains ``text``, most items first."""
    wanted = text.strip().casefold()
    if not wanted:
        return []
    found: list[Folder] = []
    for root in conn.execute("SELECT id FROM storage_roots ORDER BY id").fetchall():
        tally: dict[str, _Node] = {}
        for row in _rows(conn, int(root["id"]), ""):
            parts = _parts(row["relative_path"])
            for depth, name in enumerate(parts):
                if wanted not in name.casefold():
                    continue
                path = "/".join(parts[: depth + 1])
                node = tally.get(path.casefold())
                if node is None:
                    node = tally[path.casefold()] = _Node(
                        name=name, path=path, cover=int(row["id"])
                    )
                node.count += 1
                if depth == len(parts) - 1:
                    node.direct += 1
                else:
                    node.children.add(parts[depth + 1].casefold())
        found.extend(_to_models(conn, int(root["id"]), list(tally.values())).items)
    found.sort(key=lambda f: (-f.count, f.name.casefold()))
    return found[:MAX_FOUND]


def folder_path(conn: sqlite3.Connection, root_id: int, folder: str) -> Path:
    """The folder on disk; refused outside its library folder or when it is not there."""
    row = conn.execute("SELECT path FROM storage_roots WHERE id = ?", (root_id,)).fetchone()
    if row is None:
        raise NotFoundError("Library folder not found", details={"id": root_id})
    root = Path(row["path"]).resolve()
    target = (root / folder.strip("/\\")).resolve()
    if not target.is_relative_to(root) or not target.is_dir():
        raise NotFoundError("Folder not found", details={"path": folder})
    return target
