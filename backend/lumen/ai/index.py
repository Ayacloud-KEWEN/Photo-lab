"""In-memory vector index over the ``embeddings`` table (exact cosine search).

Brute force is fast enough for personal libraries (100k x 1152 float16 ≈ 230 MB,
one matrix-vector product per query); the matrix is reloaded only after writes.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Collection
from dataclasses import dataclass

import numpy as np


@dataclass
class _Matrix:
    ids: np.ndarray  # int64
    vectors: np.ndarray  # float16, (n, dim)
    generation: int


class VectorIndex:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, _Matrix] = {}
        self._generation: dict[str, int] = {}

    def invalidate(self, model_id: str) -> None:
        with self._lock:
            self._generation[model_id] = self._generation.get(model_id, 0) + 1

    def _matrix(self, conn: sqlite3.Connection, model_id: str) -> _Matrix:
        with self._lock:
            generation = self._generation.get(model_id, 0)
            cached = self._cache.get(model_id)
            if cached is not None and cached.generation == generation:
                return cached
        rows = conn.execute(
            "SELECT asset_id, vector FROM embeddings WHERE model_id = ? ORDER BY asset_id",
            (model_id,),
        ).fetchall()
        if rows:
            ids = np.fromiter((row[0] for row in rows), dtype=np.int64, count=len(rows))
            vectors = np.stack([np.frombuffer(row[1], dtype=np.float16) for row in rows])
        else:
            ids = np.zeros(0, dtype=np.int64)
            vectors = np.zeros((0, 0), dtype=np.float16)
        matrix = _Matrix(ids, vectors, generation)
        with self._lock:
            self._cache[model_id] = matrix
        return matrix

    def vector_of(
        self, conn: sqlite3.Connection, model_id: str, asset_id: int
    ) -> np.ndarray | None:
        row = conn.execute(
            "SELECT vector FROM embeddings WHERE model_id = ? AND asset_id = ?",
            (model_id, asset_id),
        ).fetchone()
        return np.frombuffer(row[0], dtype=np.float16).astype(np.float32) if row else None

    def search(
        self,
        conn: sqlite3.Connection,
        model_id: str,
        query: np.ndarray,
        *,
        limit: int,
        allowed: Collection[int] | None = None,
        exclude: int | None = None,
    ) -> list[tuple[int, float]]:
        """Top ``limit`` (asset_id, cosine similarity) pairs, best first."""
        matrix = self._matrix(conn, model_id)
        if matrix.ids.size == 0:
            return []
        scores = matrix.vectors.astype(np.float32) @ query.astype(np.float32).reshape(-1)
        mask = np.ones(scores.shape, dtype=bool)
        if allowed is not None:
            mask &= np.isin(matrix.ids, np.fromiter(allowed, dtype=np.int64))
        if exclude is not None:
            mask &= matrix.ids != exclude
        candidates = np.flatnonzero(mask)
        if candidates.size == 0:
            return []
        top = candidates[np.argsort(-scores[candidates], kind="stable")[:limit]]
        return [(int(matrix.ids[i]), float(scores[i])) for i in top]


index = VectorIndex()
