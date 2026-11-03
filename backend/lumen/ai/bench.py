"""Compare embedding models (SigLIP2 vs OpenCLIP) on text-to-image retrieval.

Two ways to get ground truth:

* ``--library``: your own LUMEN library. Every tag you set yourself or imported
  from files (never AI labels) with enough photos becomes a query; the photos
  carrying it are the relevant results.
* ``--folder DIR --queries FILE``: a folder of images and a JSON file
  ``{"query text": ["file1.jpg", ...], ...}``.

Reports recall@1/5/10, mean average precision and throughput, and writes the full
result as JSON. Examples::

    python -m lumen.ai.bench --library --models siglip2-so400m-patch14-384 openclip-vit-b-32
    python -m lumen.ai.bench --folder D:/eval --queries D:/eval/queries.json

OpenCLIP models need ``pip install -e .[bench]``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from lumen.ai.engine import AIEngine
from lumen.ai.models import DEFAULT_MODEL, MODELS
from lumen.core.config import Settings
from lumen.media import thumbnails

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class Dataset:
    names: list[str]  # one per image
    loaders: list[Path]
    queries: dict[str, set[int]]  # query -> indices of relevant images


@dataclass
class ModelResult:
    model: str
    device: str
    load_s: float
    images_per_s: float
    recall_at: dict[int, float]
    mean_average_precision: float
    per_query: dict[str, dict[str, float]] = field(default_factory=dict)


def library_dataset(settings: Settings, min_photos: int, max_queries: int) -> Dataset:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT a.id, c.fingerprint FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id
             AND c.ingest_state = 'done' AND c.fingerprint IS NOT NULL
        ORDER BY a.id
        """
    ).fetchall()
    position = {int(r["id"]): i for i, r in enumerate(rows)}
    paths = [thumbnails.rendition_paths(settings.cache_dir, r["fingerprint"]).thumb for r in rows]
    queries: dict[str, set[int]] = {}
    for tag in conn.execute(
        """
        SELECT t.name, group_concat(mt.asset_id) AS assets FROM tags t
        JOIN media_tags mt ON mt.tag_id = t.id AND mt.source IN ('user', 'import')
        GROUP BY t.id HAVING COUNT(*) >= ? ORDER BY COUNT(*) DESC LIMIT ?
        """,
        (min_photos, max_queries),
    ):
        relevant = {position[int(a)] for a in tag["assets"].split(",") if int(a) in position}
        if relevant:
            queries[tag["name"]] = relevant
    conn.close()
    return Dataset([str(r["id"]) for r in rows], paths, queries)


def folder_dataset(folder: Path, queries_file: Path) -> Dataset:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    index = {p.name: i for i, p in enumerate(files)}
    spec = json.loads(queries_file.read_text(encoding="utf-8"))
    queries = {
        query: {index[name] for name in names if name in index} for query, names in spec.items()
    }
    return Dataset([p.name for p in files], files, {q: r for q, r in queries.items() if r})


def _average_precision(ranking: np.ndarray, relevant: set[int]) -> float:
    hits, total = 0, 0.0
    for rank, item in enumerate(ranking, start=1):
        if int(item) in relevant:
            hits += 1
            total += hits / rank
    return total / len(relevant)


def evaluate(model_id: str, data: Dataset, batch_size: int, ks: tuple[int, ...]) -> ModelResult:
    engine = AIEngine(idle_unload_s=3600)
    started = time.monotonic()
    encoder = engine.encoder(model_id)
    load_s = time.monotonic() - started

    vectors = []
    started = time.monotonic()
    for start in range(0, len(data.loaders), batch_size):
        images = []
        for path in data.loaders[start : start + batch_size]:
            with Image.open(path) as image:
                images.append(image.convert("RGB"))
        vectors.append(encoder.encode_images(images))
    image_matrix = np.concatenate(vectors) if vectors else np.zeros((0, encoder.dim))
    images_per_s = len(data.loaders) / max(time.monotonic() - started, 1e-9)

    query_names = list(data.queries)
    text_matrix = encoder.encode_texts(query_names)
    similarities = text_matrix @ image_matrix.T
    recall = {k: 0.0 for k in ks}
    average_precisions = []
    per_query = {}
    for qi, query in enumerate(query_names):
        relevant = data.queries[query]
        ranking = np.argsort(-similarities[qi])
        ap = _average_precision(ranking, relevant)
        average_precisions.append(ap)
        stats = {"ap": round(ap, 4)}
        for k in ks:
            hit = len(relevant & {int(i) for i in ranking[:k]}) / min(k, len(relevant))
            recall[k] += hit
            stats[f"r@{k}"] = round(hit, 4)
        per_query[query] = stats
    n = max(len(query_names), 1)
    result = ModelResult(
        model=model_id,
        device=encoder.device,
        load_s=round(load_s, 1),
        images_per_s=round(images_per_s, 1),
        recall_at={k: round(v / n, 4) for k, v in recall.items()},
        mean_average_precision=round(
            float(np.mean(average_precisions)) if average_precisions else 0, 4
        ),
        per_query=per_query,
    )
    engine.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lumen.ai.bench", description=__doc__.split("\n\n")[0]
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--library", action="store_true", help="use the LUMEN library and its tags")
    source.add_argument("--folder", type=Path, help="folder of images (needs --queries)")
    parser.add_argument("--queries", type=Path, help='JSON: {"query": ["file.jpg", ...]}')
    parser.add_argument("--models", nargs="+", default=[DEFAULT_MODEL], choices=sorted(MODELS))
    parser.add_argument("--min-photos", type=int, default=3, help="library mode: photos per tag")
    parser.add_argument("--max-queries", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--output", type=Path, help="write the full result as JSON")
    args = parser.parse_args(argv)

    if args.folder:
        if not args.queries:
            parser.error("--folder requires --queries")
        data = folder_dataset(args.folder, args.queries)
    else:
        data = library_dataset(Settings(), args.min_photos, args.max_queries)
    if not data.queries:
        print("No queries with relevant images: add tags (library mode) or check the JSON.")
        return 1
    print(f"{len(data.loaders)} images, {len(data.queries)} queries\n")

    ks = (1, 5, 10)
    results = []
    for model_id in args.models:
        try:
            result = evaluate(model_id, data, args.batch_size, ks)
        except ImportError as exc:
            print(f"{model_id}: skipped ({exc}; for OpenCLIP: pip install -e .[bench])")
            continue
        results.append(result)

    header = (
        f"{'model':40} {'device':6} {'img/s':>7} "
        + " ".join(f"{'R@' + str(k):>6}" for k in ks)
        + f" {'mAP':>6}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.model:40} {r.device:6} {r.images_per_s:7.1f} "
            + " ".join(f"{r.recall_at[k]:6.3f}" for k in ks)
            + f" {r.mean_average_precision:6.3f}"
        )
    if args.output:
        args.output.write_text(
            json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
