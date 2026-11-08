"""Compare local vision-language models on photos from your own library.

Picks photos of several kinds (signs, menus, tickets, landscapes, people, food...)
with the library's SigLIP vectors, then asks each model about the same photos and
writes a self-contained HTML report (photos, answers, speed, GPU memory) and JSON::

    python -m lumen.vlm.bench --db <copy of lumen.db> --out <folder> \\
        --llama "D:/LUMEN Studio/tools/llama.cpp/b12207/llama-server.exe" \\
        --models-dir "D:/LUMEN Studio/models" --models qwen3-vl-8b qwen3.6-35b-a3b

Only reads the library (a copy of the database is safest) and the original photos.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image

from lumen.media import thumbnails
from lumen.vlm.describe import IMAGE_EDGE, PROMPT, DescribeError, describe
from lumen.vlm.models import MODELS
from lumen.vlm.server import LlamaServer, ServerError

# Kinds of photo to test, as SigLIP queries (English works best for retrieval).
KINDS: dict[str, str] = {
    "路牌与招牌": "a street sign or shop sign with readable text",
    "菜单与小票": "a restaurant menu or a receipt with printed text",
    "票据与说明牌": "a ticket, a museum information panel or a poster with text",
    "截图与文件": "a screenshot or a photo of a document",
    "风景": "a landscape with mountains, sea or a lake",
    "城市与建筑": "a street in an old town with buildings",
    "人物": "people posing for a photo, a portrait",
    "美食": "a dish of food on a table",
}


def _settings_model(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'ai_model'").fetchone()
    from lumen.ai.models import DEFAULT_MODEL

    return json.loads(row[0]) if row else DEFAULT_MODEL


def pick_photos(db: Path, per_kind: int) -> list[dict[str, Any]]:
    """Photos of each kind whose original can be read now (best SigLIP matches first)."""
    from lumen.ai.engine import AIEngine
    from lumen.ai.index import VectorIndex

    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    model_id = _settings_model(conn)
    rows = conn.execute(
        """
        SELECT a.id, c.relative_path, c.extension, r.path AS root
        FROM media_assets a
        JOIN media_files c ON c.id = a.cover_file_id AND c.status = 'present'
        JOIN storage_roots r ON r.id = c.storage_root_id AND r.status != 'offline'
        WHERE a.media_type = 'photo' AND c.extension IN ('jpg', 'jpeg', 'heic', 'png')
        """
    ).fetchall()
    readable = {int(r["id"]): Path(r["root"]) / r["relative_path"] for r in rows}
    engine = AIEngine(idle_unload_s=60)
    encoder = engine.encoder(model_id)
    index = VectorIndex()
    chosen: list[dict[str, Any]] = []
    seen: set[int] = set()
    try:
        for kind, query in KINDS.items():
            vector = encoder.encode_texts([query])[0]
            hits = index.search(conn, model_id, vector, limit=400, allowed=list(readable))
            taken = 0
            for asset_id, score in hits:
                if asset_id in seen or not readable[asset_id].is_file():
                    continue
                seen.add(asset_id)
                chosen.append(
                    {"asset_id": asset_id, "kind": kind, "path": str(readable[asset_id]),
                     "siglip": round(score, 4)}
                )  # fmt: skip
                taken += 1
                if taken >= per_kind:
                    break
    finally:
        engine.close()
        conn.close()
    return chosen


class GpuMonitor:
    """Peak GPU memory in use (nvidia-smi, sampled twice a second)."""

    def __init__(self) -> None:
        self.peak_mib = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> GpuMonitor:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )  # fmt: skip
                self.peak_mib = max(self.peak_mib, int(out.stdout.split()[0]))
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                pass
            self._stop.wait(0.5)


def run_model(
    model_id: str, llama: Path, models_dir: Path, images: list[Path], log: Path
) -> dict[str, Any]:
    spec = MODELS[model_id]
    server = LlamaServer(llama, spec.files(models_dir), log_path=log)
    result: dict[str, Any] = {"model": model_id, "label": spec.label, "licence": spec.licence}
    started = time.perf_counter()
    with GpuMonitor() as gpu:
        try:
            server.start()
        except ServerError as exc:
            result["error"] = str(exc)
            return result
        result["load_s"] = round(time.perf_counter() - started, 1)
        answers: list[dict[str, Any]] = []
        try:
            for path in images:
                with Image.open(path) as image:
                    try:
                        answer = describe(server.url, image)
                        answers.append(asdict(answer))
                    except DescribeError as exc:
                        answers.append({"error": str(exc)})
                print(f"  {model_id}: {len(answers)}/{len(images)}", file=sys.stderr, flush=True)
        finally:
            server.stop()
    result["answers"] = answers
    result["gpu_peak_mib"] = gpu.peak_mib
    timed = [a for a in answers if "seconds" in a][1:]  # the first one warms up
    if timed:
        result["seconds_per_photo"] = round(sum(a["seconds"] for a in timed) / len(timed), 2)
        tokens = sum(a["output_tokens"] for a in timed)
        result["output_tokens_per_s"] = round(tokens / sum(a["seconds"] for a in timed), 1)
        result["prompt_tokens"] = round(sum(a["prompt_tokens"] for a in timed) / len(timed))
    result["failures"] = sum(1 for a in answers if "error" in a)
    return result


def _thumb(path: Path) -> str:
    with Image.open(path) as image:
        copy = image.convert("RGB")
    copy.thumbnail((480, 480))
    out = io.BytesIO()
    copy.save(out, "JPEG", quality=80)
    return base64.b64encode(out.getvalue()).decode()


def write_report(out: Path, sample: list[dict[str, Any]], results: list[dict[str, Any]]) -> Path:
    esc = html.escape
    head = "".join(f"<th>{esc(r['label'])}</th>" for r in results)
    summary_rows = []
    for key, label in (
        ("load_s", "加载（秒）"), ("seconds_per_photo", "每张（秒）"),
        ("output_tokens_per_s", "生成速度（token/秒）"), ("prompt_tokens", "每张输入 token"),
        ("gpu_peak_mib", "显存峰值（MiB）"), ("failures", "失败"), ("licence", "许可证"),
    ):  # fmt: skip
        values = "".join(f"<td>{esc(str(r.get(key, r.get('error', '—'))))}</td>" for r in results)
        summary_rows.append(f"<tr><th>{label}</th>{values}</tr>")
    rows = []
    for i, item in enumerate(sample):
        cells = []
        for r in results:
            answers = r.get("answers") or []
            a = answers[i] if i < len(answers) else {"error": r.get("error", "—")}
            if "error" in a:
                cells.append(f"<td class=err>{esc(a['error'])}</td>")
                continue
            text = esc(a["text"]).replace("\n", "<br>") or "<i>（无文字）</i>"
            cells.append(
                f"<td><p>{esc(a['description'])}</p><p class=t>{text}</p>"
                f"<p class=k>{esc(' · '.join(a['keywords']))}</p>"
                f"<p class=s>{a['seconds']:.1f} 秒 · {a['output_tokens']} token</p></td>"
            )
        rows.append(
            f"<tr><td class=img><img src='data:image/jpeg;base64,{_thumb(Path(item['image']))}'>"
            f"<div>{esc(item['kind'])} · #{item['asset_id']}</div></td>{''.join(cells)}</tr>"
        )
    page = f"""<!doctype html><html lang=zh-CN><meta charset=utf-8>
<title>本地视觉模型对比</title>
<style>
:root{{--bg:#fff;--fg:#1c1c1c;--muted:#666;--line:#ddd;--hl:#2563eb}}
@media (prefers-color-scheme: dark){{:root{{--bg:#151515;--fg:#e8e8e8;--muted:#999;--line:#333;--hl:#7aa2ff}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif;margin:16px}}
table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}}
td.img{{width:260px}} td.img img{{width:250px;border-radius:4px}} td.img div{{color:var(--muted);font-size:12px}}
.t{{font-family:Consolas,monospace;font-size:12.5px;color:var(--hl)}} .k{{color:var(--muted);font-size:12.5px}}
.s{{color:var(--muted);font-size:11.5px}} .err{{color:#d33}} details{{margin:12px 0}}
</style>
<h1>本地视觉模型对比</h1>
<p>{len(sample)} 张照片，图片长边 {IMAGE_EDGE} 像素；每张只请求一次，返回描述、画面文字和关键词。</p>
<table>{"".join(["<tr><th></th>" + head + "</tr>", *summary_rows])}</table>
<details><summary>提示词</summary><pre>{esc(PROMPT)}</pre></details>
<table><tr><th>照片</th>{head}</tr>{"".join(rows)}</table></html>"""
    path = out / "report.html"
    path.write_text(page, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, required=True, help="library database (a copy)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--llama", type=Path, required=True, help="llama-server.exe")
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=list(MODELS), choices=sorted(MODELS))
    parser.add_argument("--per-kind", type=int, default=6)
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    images_dir = args.out / "images"
    sample_file = args.out / "sample.json"
    if sample_file.exists():
        sample = json.loads(sample_file.read_text(encoding="utf-8"))
    else:
        print("picking photos…", file=sys.stderr)
        sample = pick_photos(args.db, args.per_kind)
        images_dir.mkdir(exist_ok=True)
        for i, item in enumerate(sample):
            image = thumbnails.decode_still(Path(item["path"]), 2048)
            image.thumbnail((2048, 2048))
            target = images_dir / f"{i:03d}.jpg"
            image.save(target, "JPEG", quality=92)
            item["image"] = str(target)
        sample_file.write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    images = [Path(item["image"]) for item in sample]

    results_file = args.out / "results.json"
    results: dict[str, Any] = (
        json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
    )
    for model_id in args.models:
        print(f"running {model_id}…", file=sys.stderr)
        results[model_id] = run_model(
            model_id, args.llama, args.models_dir, images, args.out / f"{model_id}.log"
        )
        results_file.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        summary = {k: v for k, v in results[model_id].items() if k != "answers"}
        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    ordered = [results[m] for m in MODELS if m in results]
    print(write_report(args.out, sample, ordered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
