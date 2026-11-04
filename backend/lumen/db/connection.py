"""SQLite connections and transactions."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar, cast

T = TypeVar("T")


def utc_now() -> str:
    """Timestamp format used in every table: ISO 8601, UTC, millisecond precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        # Autocommit mode: transactions are always explicit via ``transaction()``.
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside ``BEGIN IMMEDIATE`` … ``COMMIT``, rolling back on any error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    bump_write_generation()


_generation_lock = threading.Lock()
_generation = 0


def write_generation() -> int:
    """Bumped after every committed ``transaction()`` (and a database restore): results
    computed from the library can be cached until it changes."""
    return _generation


def bump_write_generation() -> None:
    global _generation
    with _generation_lock:
        _generation += 1


class GenerationCache:
    """Values computed from the library, kept until the next write (bounded size)."""

    def __init__(self, size: int = 16) -> None:
        self._size = size
        self._lock = threading.Lock()
        self._values: dict[Hashable, tuple[int, object]] = {}

    def get(self, key: Hashable, compute: Callable[[], T]) -> T:
        generation = write_generation()
        with self._lock:
            hit = self._values.get(key)
        if hit is not None and hit[0] == generation:
            return cast(T, hit[1])
        value = compute()
        with self._lock:
            if len(self._values) >= self._size:
                self._values.clear()
            self._values[key] = (generation, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
