"""Phase 4: AI indexing, labels, semantic search, similar photos and cloud analysis."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.ai import cloud, engine
from lumen.ai.models import DEFAULT_MODEL, get_spec
from lumen.app import create_app
from lumen.core.config import Settings
from tests.conftest import TOKEN
from tests.media_factory import make_jpeg, make_video
from tests.test_pipeline import wait_idle

needs_tools = pytest.mark.skipif(
    not (shutil.which("exiftool") and shutil.which("ffmpeg")), reason="exiftool/ffmpeg required"
)

# ------------------------------------------------------------------ fakes


class FakeEncoder:
    """Deterministic stand-in for SigLIP2: vectors follow the image's average colour."""

    dim = 4
    device = "cpu"
    logit_scale = 5.0  # with 50 neutral labels, only clear matches pass the share threshold

    def __init__(self) -> None:
        self.spec = get_spec(DEFAULT_MODEL)
        self.text_calls: list[str] = []

    def encode_images(self, images: list[Image.Image]) -> np.ndarray:
        rows = []
        for image in images:
            r, g, b = (np.asarray(image.convert("RGB"), dtype=np.float32) / 255).mean(axis=(0, 1))
            rows.append([r, g, b, 0.1])
        return _normalize(np.array(rows, dtype=np.float32))

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        self.text_calls += texts
        rows = []
        for text in texts:
            if "sunset" in text or "红" in text:
                rows.append([1.0, 0.1, 0.1, 0.1])
            elif "sea" in text or "蓝" in text:
                rows.append([0.1, 0.2, 1.0, 0.1])
            else:
                rows.append([0.1, 0.1, 0.1, 1.0])
        return _normalize(np.array(rows, dtype=np.float32))

    def probabilities(self, similarities: np.ndarray) -> np.ndarray | None:
        return 1 / (1 + np.exp(-(similarities * 10 - 5)))

    def close(self) -> None:
        pass


def _normalize(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


class FakeEngine:
    def __init__(self) -> None:
        self.fake = FakeEncoder()
        self.loaded_model: str | None = None

    def encoder(self, model_id: str) -> FakeEncoder:
        self.loaded_model = model_id
        return self.fake

    def touch(self) -> None:
        pass

    def unload(self) -> None:
        self.loaded_model = None

    def close(self) -> None:
        pass


class MemoryKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, user: str) -> str | None:
        return self.store.get((service, user))

    def set_password(self, service: str, user: str, value: str) -> None:
        self.store[(service, user)] = value

    def delete_password(self, service: str, user: str) -> None:
        self.store.pop((service, user))


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeEngine]:
    fake = FakeEngine()
    engine.set_engine(fake)  # type: ignore[arg-type]
    # Pretend the AI components and the model are installed wherever that is checked.
    for module in ("lumen.ai.pipeline", "lumen.services.ai", "lumen.api.v1.settings"):
        monkeypatch.setattr(f"{module}.model_downloaded", lambda spec: True)
        monkeypatch.setattr(f"{module}.torch_installed", lambda: True)
    yield fake
    engine.set_engine(None)


@pytest.fixture
def keyring_store(monkeypatch: pytest.MonkeyPatch) -> MemoryKeyring:
    store = MemoryKeyring()
    monkeypatch.setattr(cloud, "_keyring", lambda: store)
    return store


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "Photos"
    make_jpeg(root / "red_1.jpg", color=(230, 40, 30), taken="2024:01:01 10:00:00")
    make_jpeg(root / "red_2.jpg", color=(210, 60, 40), taken="2024:01:02 10:00:00")
    make_jpeg(root / "blue_1.jpg", color=(30, 60, 230), taken="2024:01:03 10:00:00",
              gps=(31.2, 121.4))  # fmt: skip
    make_jpeg(root / "gray_1.jpg", color=(128, 128, 128), taken="2024:01:04 10:00:00")
    return root


@pytest.fixture
def client(tmp_path: Path, library: Path, fake_ai: FakeEngine) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        test_client.post("/api/v1/storage-roots", json={"path": str(library)})
        wait_idle(app.state.db)
        yield test_client


def ids_by_name(client: TestClient) -> dict[str, int]:
    items = client.get("/api/v1/assets", params={"limit": 100}).json()["items"]
    return {item["file_name"]: item["id"] for item in items}


def enable_ai(client: TestClient) -> None:
    assert client.patch("/api/v1/settings", json={"ai_enabled": True}).status_code == 200
    wait_idle(client.app.state.db)  # type: ignore[attr-defined]


# ------------------------------------------------------------------ local AI


@needs_tools
def test_ai_is_off_until_enabled(client: TestClient) -> None:
    status = client.get("/api/v1/ai/status").json()
    assert status["local"]["enabled"] is False
    assert status["local"]["indexed"] == 0 and status["local"]["total"] == 4
    assert {m["id"] for m in status["local"]["models"]} >= {DEFAULT_MODEL}
    response = client.get("/api/v1/ai/search", params={"text": "红色"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "ai_not_ready"


@needs_tools
def test_enabling_ai_indexes_and_labels(client: TestClient) -> None:
    enable_ai(client)
    status = client.get("/api/v1/ai/status").json()["local"]
    assert (status["indexed"], status["total"]) == (4, 4)

    names = ids_by_name(client)
    red = client.get(f"/api/v1/assets/{names['red_1.jpg']}").json()
    assert [(t["name"], t["source"]) for t in red["tags"]] == [("日出日落", "ai")]
    blue = client.get(f"/api/v1/assets/{names['blue_1.jpg']}").json()
    assert [t["name"] for t in blue["tags"]] == ["海"]
    gray = client.get(f"/api/v1/assets/{names['gray_1.jpg']}").json()
    assert gray["tags"] == []  # no label is a clear winner

    # AI labels are searchable like any tag, and indexing again changes nothing.
    assert [
        i["file_name"]
        for i in client.get("/api/v1/assets", params={"q": "日出日落"}).json()["items"]
    ] == ["red_2.jpg", "red_1.jpg"]
    client.post("/api/v1/ai/index")
    wait_idle(client.app.state.db)  # type: ignore[attr-defined]
    assert client.get(f"/api/v1/assets/{names['red_1.jpg']}").json()["tags"] == red["tags"]


@needs_tools
def test_user_tags_survive_relabeling(client: TestClient) -> None:
    enable_ai(client)
    asset_id = ids_by_name(client)["red_1.jpg"]
    client.post("/api/v1/assets/batch", json={"asset_ids": [asset_id], "add_tags": ["家人"]})
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.session() as conn:
        conn.execute("UPDATE embeddings SET labels_version = 0")  # vocabulary changed
    client.post("/api/v1/ai/index")
    wait_idle(db)
    tags = {
        (t["name"], t["source"]) for t in client.get(f"/api/v1/assets/{asset_id}").json()["tags"]
    }
    assert tags == {("家人", "user"), ("日出日落", "ai")}


@needs_tools
def test_semantic_search_and_similar(client: TestClient) -> None:
    enable_ai(client)
    result = client.get("/api/v1/ai/search", params={"text": "红色的照片", "limit": 2}).json()
    assert [i["file_name"] for i in result["items"]] == ["red_1.jpg", "red_2.jpg"]
    assert result["scores"] == sorted(result["scores"], reverse=True)
    assert result["model_id"] == DEFAULT_MODEL

    # Filters still apply (only the photo with a location).
    located = client.get("/api/v1/ai/search", params={"text": "红色", "has_location": True}).json()
    assert [i["file_name"] for i in located["items"]] == ["blue_1.jpg"]

    names = ids_by_name(client)
    similar = client.get(f"/api/v1/assets/{names['red_1.jpg']}/similar", params={"limit": 3}).json()
    assert similar["items"][0]["file_name"] == "red_2.jpg"
    assert names["red_1.jpg"] not in [i["id"] for i in similar["items"]]
    assert client.get("/api/v1/assets/99999/similar").status_code == 404


@needs_tools
def test_new_files_are_indexed_after_ingest(client: TestClient, library: Path) -> None:
    enable_ai(client)
    make_jpeg(library / "red_3.jpg", color=(240, 20, 20), taken="2024:02:01 10:00:00")
    root_id = client.get("/api/v1/storage-roots").json()["items"][0]["id"]
    client.post(f"/api/v1/storage-roots/{root_id}/scan")
    wait_idle(client.app.state.db)  # type: ignore[attr-defined]
    status = client.get("/api/v1/ai/status").json()["local"]
    assert (status["indexed"], status["total"]) == (5, 5)


def test_vector_index_search(tmp_path: Path) -> None:
    from lumen.ai.index import VectorIndex
    from lumen.db.connection import Database
    from lumen.db.migrator import migrate

    db = Database(tmp_path / "x.db")
    migrate(db)
    with db.session() as conn:
        now = "2026-01-01T00:00:00.000Z"
        for asset_id, vector in ((1, [1, 0]), (2, [0.8, 0.6]), (3, [0, 1])):
            conn.execute(
                "INSERT INTO media_assets (id, uuid, media_type, created_at, updated_at) "
                "VALUES (?, ?, 'photo', ?, ?)",
                (asset_id, f"u{asset_id}", now, now),
            )
            conn.execute(
                "INSERT INTO embeddings (asset_id, model_id, fingerprint, dim, vector, created_at) "
                "VALUES (?, 'm', 'f', 2, ?, ?)",
                (asset_id, np.array(vector, dtype=np.float16).tobytes(), now),
            )
        index = VectorIndex()
        query = np.array([1.0, 0.0], dtype=np.float32)
        assert [i for i, _ in index.search(conn, "m", query, limit=3)] == [1, 2, 3]
        assert [i for i, _ in index.search(conn, "m", query, limit=3, allowed={2, 3})] == [2, 3]
        assert [i for i, _ in index.search(conn, "m", query, limit=1, exclude=1)] == [2]
        assert index.search(conn, "other", query, limit=3) == []


# ------------------------------------------------------------------ cloud


class FakeDeepSeek:
    """Replaces DeepSeekClient._request; records what would have been sent."""

    def __init__(self, reply: str = "## 点评\n构图很好。", vision: bool = True) -> None:
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.reply = reply
        self.vision = vision

    def __call__(
        self, client: cloud.DeepSeekClient, method: str, path: str, body: Any = None
    ) -> Any:
        self.requests.append((method, path, body))
        if path == "/models":
            return {"data": [{"id": "deepseek-flash"}, {"id": "deepseek-pro"}]}
        has_image = any(
            part.get("type") == "image_url"
            for message in body["messages"]
            if isinstance(message["content"], list)
            for part in message["content"]
        )
        if has_image and not self.vision:
            raise cloud.VisionUnsupportedError("Model does not accept images")
        text = "red" if body["max_tokens"] == 10 else self.reply
        return {
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        }


@pytest.fixture
def deepseek(monkeypatch: pytest.MonkeyPatch) -> FakeDeepSeek:
    fake = FakeDeepSeek()
    monkeypatch.setattr(
        cloud.DeepSeekClient, "_request", lambda self, m, p, b=None: fake(self, m, p, b)
    )
    return fake


def setup_cloud(client: TestClient) -> None:
    assert (
        client.put("/api/v1/ai/cloud/key", json={"api_key": "sk-test-1234567890"}).status_code
        == 204
    )
    client.patch("/api/v1/settings", json={"cloud_enabled": True})


@needs_tools
def test_api_key_is_kept_out_of_the_database(
    client: TestClient, keyring_store: MemoryKeyring
) -> None:
    setup_cloud(client)
    assert keyring_store.store == {
        (cloud.KEYRING_SERVICE, cloud.KEYRING_USER): "sk-test-1234567890"
    }
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.session() as conn:
        dump = "\n".join(conn.iterdump())
    assert "sk-test" not in dump
    assert client.get("/api/v1/ai/status").json()["cloud"]["has_key"] is True
    assert client.delete("/api/v1/ai/cloud/key").status_code == 204
    assert client.get("/api/v1/ai/status").json()["cloud"]["has_key"] is False


@needs_tools
def test_cloud_connection_test(
    client: TestClient, keyring_store: MemoryKeyring, deepseek: FakeDeepSeek
) -> None:
    setup_cloud(client)
    result = client.post("/api/v1/ai/cloud/test").json()
    assert result["ok"] is True and result["vision"] is True
    assert result["models"] == ["deepseek-flash", "deepseek-pro"]
    deepseek.vision = False
    assert client.post("/api/v1/ai/cloud/test").json()["vision"] is False


@needs_tools
def test_cloud_preview_shows_exactly_what_is_sent(
    client: TestClient, keyring_store: MemoryKeyring, deepseek: FakeDeepSeek
) -> None:
    setup_cloud(client)
    blue = ids_by_name(client)["blue_1.jpg"]
    preview = client.post(
        "/api/v1/ai/cloud/preview", json={"kind": "critique", "asset_ids": [blue]}
    ).json()
    assert preview["host"] == "api.deepseek.com" and preview["model"] == "deepseek-flash"
    assert preview["image_max_edge"] == 1024 and preview["cached"] is False
    fields = preview["items"][0]["fields"]
    assert fields["camera"] == "Canon EOS R5" and "location" not in fields  # GPS off by default
    with_location = client.post(
        "/api/v1/ai/cloud/preview",
        json={"kind": "critique", "asset_ids": [blue], "include_location": True},
    ).json()
    assert with_location["items"][0]["fields"]["location"] == "31.20000, 121.40000"
    assert deepseek.requests == []  # previews never contact the provider


@needs_tools
def test_cloud_analysis_requires_confirmation_and_is_cached(
    client: TestClient, keyring_store: MemoryKeyring, deepseek: FakeDeepSeek
) -> None:
    setup_cloud(client)
    red = ids_by_name(client)["red_1.jpg"]
    request = {"kind": "critique", "asset_ids": [red], "language": "zh-CN"}
    assert client.post("/api/v1/ai/cloud/analyze", json=request).status_code == 422  # no consent

    first = client.post("/api/v1/ai/cloud/analyze", json={**request, "confirmed": True}).json()
    assert first["cached"] is False and first["vision"] is True
    assert first["result"].startswith("## 点评") and first["input_tokens"] == 120
    method, path, body = deepseek.requests[-1]
    assert (method, path, body["model"]) == ("POST", "/chat/completions", "deepseek-flash")
    parts = body["messages"][1]["content"]
    image = next(p for p in parts if p["type"] == "image_url")["image_url"]["url"]
    assert image.startswith("data:image/jpeg;base64,")
    assert "简体中文" in parts[-1]["text"]
    assert "location" not in json.dumps(parts)

    calls = len(deepseek.requests)
    again = client.post("/api/v1/ai/cloud/analyze", json={**request, "confirmed": True}).json()
    assert again["cached"] is True and again["id"] == first["id"]
    assert len(deepseek.requests) == calls  # served from cache
    assert client.post("/api/v1/ai/cloud/preview", json=request).json()["cached"] is True
    assert [a["id"] for a in client.get(f"/api/v1/assets/{red}/analyses").json()] == [first["id"]]


@needs_tools
def test_select_best_parses_ranking(
    client: TestClient, keyring_store: MemoryKeyring, deepseek: FakeDeepSeek
) -> None:
    setup_cloud(client)
    names = ids_by_name(client)
    deepseek.reply = '{"best": 2, "ranking": [2, 1, 9]}\n第二张最好，因为光线柔和。'
    result = client.post(
        "/api/v1/ai/cloud/analyze",
        json={"kind": "select_best", "asset_ids": [names["red_1.jpg"], names["blue_1.jpg"]],
              "confirmed": True},
    ).json()  # fmt: skip
    assert result["data"] == {"best": 2, "ranking": [2, 1]}  # out-of-range entries dropped
    assert result["result"] == "第二张最好，因为光线柔和。"
    assert result["asset_ids"] == [names["red_1.jpg"], names["blue_1.jpg"]]


@needs_tools
def test_text_only_fallback_and_errors(
    client: TestClient, keyring_store: MemoryKeyring, deepseek: FakeDeepSeek
) -> None:
    red = ids_by_name(client)["red_1.jpg"]
    analyze = {"kind": "describe", "asset_ids": [red], "confirmed": True}
    # Cloud off → 409; on but model refuses images → 422 vision_unsupported.
    assert (
        client.post("/api/v1/ai/cloud/analyze", json=analyze).json()["error"]["code"]
        == "cloud_not_configured"
    )
    setup_cloud(client)
    deepseek.vision = False
    refused = client.post("/api/v1/ai/cloud/analyze", json=analyze)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "vision_unsupported"

    text_only = client.post("/api/v1/ai/cloud/analyze", json={**analyze, "text_only": True}).json()
    assert text_only["vision"] is False
    _, _, body = deepseek.requests[-1]
    assert all(p["type"] == "text" for p in body["messages"][1]["content"])
    # Wrong number of photos for the kind.
    too_many = client.post(
        "/api/v1/ai/cloud/preview", json={"kind": "describe", "asset_ids": [red, red + 1]}
    )
    assert too_many.status_code == 400


# ------------------------------------------------------------------ real model


def _real_model_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available() and engine.model_downloaded(get_spec(DEFAULT_MODEL))
    except ImportError:
        return False


@pytest.mark.skipif(not _real_model_available(), reason="SigLIP2 model / CUDA not available")
def test_real_siglip2_on_gpu() -> None:
    real = engine.AIEngine(idle_unload_s=60)
    try:
        encoder = real.encoder(DEFAULT_MODEL)
        assert encoder.device == "cuda" and encoder.dim == 1152
        images = [Image.new("RGB", (384, 384), color) for color in ((220, 30, 30), (30, 60, 220))]
        vectors = encoder.encode_images(images)
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, rtol=1e-3)
        texts = encoder.encode_texts(["红色", "蓝色"])  # Chinese queries, no translation
        similarities = texts @ vectors.T
        assert similarities[0, 0] > similarities[0, 1]
        assert similarities[1, 1] > similarities[1, 0]
    finally:
        real.close()


@needs_tools
def test_long_exposure_candidates_are_live_photos_of_suitable_scenes(
    tmp_path: Path, fake_ai: FakeEngine
) -> None:
    root = tmp_path / "Phone"
    make_jpeg(root / "IMG_1.jpg", color=(30, 60, 230), taken="2024:01:01 10:00:00")  # "the sea"
    make_video(root / "IMG_1.MOV", seconds=2)
    make_jpeg(root / "IMG_2.jpg", color=(128, 128, 128), taken="2024:01:02 10:00:00")
    make_video(root / "IMG_2.MOV", seconds=2)
    make_jpeg(root / "IMG_3.jpg", color=(30, 60, 230), taken="2024:01:03 10:00:00")  # no clip
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        client.post("/api/v1/storage-roots", json={"path": str(root)})
        wait_idle(app.state.db)
        enable_ai(client)
        found = client.get("/api/v1/ai/long-exposure").json()
        assert [i["file_name"] for i in found["items"]] == ["IMG_1.jpg", "IMG_2.jpg"]
        assert found["scores"] == sorted(found["scores"], reverse=True)

        # Once it is a long exposure it is no longer suggested.
        first = found["items"][0]["id"]
        client.put(f"/api/v1/assets/{first}/edit", json={"live_effect": "long_exposure"})
        again = client.get("/api/v1/ai/long-exposure").json()
        assert [i["file_name"] for i in again["items"]] == ["IMG_2.jpg"]
