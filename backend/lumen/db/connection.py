"""SQLite connections and transactions."""

from __future__ import annotations

import sqlite3
import threading
import time
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
        # Read through memory mapping: large library-wide queries (facets, timeline,
        # duplicates) run 2-3x faster than through SQLite's small per-connection cache.
        conn.execute("PRAGMA mmap_size = 1073741824")
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
_user_generation = 0
_background_generation = 0
_local = threading.local()

# While a background task writes (an import saving every few seconds), library-wide
# results are recomputed at most this often; the user's own changes show at once.
BACKGROUND_STALENESS_S = 60.0


@contextmanager
def background_writes() -> Iterator[None]:
    """Mark the transactions of this thread as background work (the task runner)."""
    _local.background = True
    try:
        yield
    finally:
        _local.background = False


def write_generation() -> tuple[int, int]:
    """(user, background) write counters, bumped after every committed ``transaction()``
    (and a database restore): results computed from the library can be cached until
    they change."""
    return _user_generation, _background_generation


def bump_write_generation(*, background: bool | None = None) -> None:
    global _user_generation, _background_generation
    if background is None:
        background = bool(getattr(_local, "background", False))
    with _generation_lock:
        if background:
            _background_generation += 1
        else:
            _user_generation += 1


class GenerationCache:
    """Values computed from the library, kept until the next write (bounded size).

    A user write (rating, tags, merge...) invalidates at once; background writes only
    after ``BACKGROUND_STALENESS_S`` seconds, so an import does not make every view
    recompute its aggregates continuously.
    """

    def __init__(self, size: int = 16) -> None:
        self._size = size
        self._lock = threading.Lock()
        self._values: dict[Hashable, tuple[int, int, float, object]] = {}

    def get(self, key: Hashable, compute: Callable[[], T]) -> T:
        user, background = write_generation()
        now = time.monotonic()
        with self._lock:
            hit = self._values.get(key)
        if hit is not None and hit[0] == user and (
            hit[1] == background or now - hit[2] < BACKGROUND_STALENESS_S
        ):
            return cast(T, hit[3])
        value = compute()
        with self._lock:
            if len(self._values) >= self._size:
                self._values.clear()
            self._values[key] = (user, background, now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
