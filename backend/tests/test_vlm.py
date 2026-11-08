"""Local vision-language model: the request, parsing answers, the llama-server process."""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumen.app import create_app
from lumen.core.config import Settings
from lumen.vlm import describe
from lumen.vlm.models import DEFAULT_MODEL, FINE_MODEL, MODELS
from lumen.vlm.server import LlamaServer, ModelFiles
from tests.conftest import TOKEN
from tests.media_factory import make_jpeg
from tests.test_pipeline import wait_idle


def test_request_asks_for_json_without_thinking() -> None:
    body = describe.request_body("data:image/jpeg;base64,xx")
    content = body["messages"][0]["content"]
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg")
    assert "description" in content[1]["text"] and "text" in content[1]["text"]
    assert body["response_format"]["json_schema"]["schema"]["required"] == [
        "description", "text", "keywords",
    ]  # fmt: skip
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_images_are_sent_small_enough() -> None:
    url = describe.encode_image(Image.new("RGB", (4032, 3024), "red"), edge=1280)
    data = base64.b64decode(url.split(",", 1)[1])
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (1280, 960) and image.format == "JPEG"


def answer(content: str, prompt: int = 900, output: int = 60) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": output},
    }


def test_parse_answer() -> None:
    content = json.dumps(
        {
            "description": " 两个孩子在海边喂海鸥。 ",
            "text": "Stari Grad\nKotor",
            "keywords": ["海边", "海鸥", "海边", " ", 3],
        },
        ensure_ascii=False,
    )
    parsed = describe.parse_answer(answer(content), 4.2)
    assert parsed.description == "两个孩子在海边喂海鸥。"
    assert parsed.text == "Stari Grad\nKotor"
    assert parsed.keywords == ("海边", "海鸥")  # de-duplicated, blanks and non-strings dropped
    assert (parsed.prompt_tokens, parsed.output_tokens, parsed.seconds) == (900, 60, 4.2)


@pytest.mark.parametrize(
    "bad", [{"choices": []}, answer("not json"), answer("[1, 2]"), {"error": "oom"}]
)
def test_unexpected_answers_raise(bad: dict[str, object]) -> None:
    with pytest.raises(describe.DescribeError):
        describe.parse_answer(bad, 1.0)


def test_server_command_is_local_and_complete(tmp_path: Path) -> None:
    files = ModelFiles("m", tmp_path / "m.gguf", tmp_path / "mm.gguf", ("--reasoning", "off"))
    server = LlamaServer(tmp_path / "llama-server.exe", files, port=5123)
    command = server.command()
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "5123"
    assert command[command.index("--mmproj") + 1] == str(tmp_path / "mm.gguf")
    assert "--no-webui" in command and command[-2:] == ["--reasoning", "off"]


def test_models_use_their_draft_head_only_when_downloaded(tmp_path: Path) -> None:
    spec = MODELS["qwen3.6-35b-a3b"]
    assert "--spec-type" not in spec.files(tmp_path).args
    (tmp_path / spec.folder).mkdir()
    assert spec.draft is not None
    (tmp_path / spec.folder / spec.draft).write_bytes(b"")
    args = spec.files(tmp_path).args
    assert args[args.index("--spec-type") + 1] == "draft-mtp"
    assert not spec.downloaded(tmp_path)  # the model itself is missing


def test_a_server_that_cannot_start_reports_it(tmp_path: Path) -> None:
    files = ModelFiles("m", tmp_path / "m.gguf", tmp_path / "mm.gguf")
    server = LlamaServer(tmp_path / "missing.exe", files)
    from lumen.vlm.server import ServerError

    with pytest.raises(ServerError):
        server.start()
    assert not server.running()


def test_an_answer_cut_off_keeps_what_was_complete() -> None:
    # As the server returns it: JSON text, with escaped newlines, cut mid-word.
    content = (
        '{"description": "博物馆的说明牌。", '
        r'"text": "LOFOTR\nVikingmuseum\nVikingmuseum\nVikingmuseum\nVik'
    )
    cut = {"choices": [{"finish_reason": "length", "message": {"content": content}}]}
    parsed = describe.parse_answer(cut, 30.0)
    assert parsed.truncated and parsed.description == "博物馆的说明牌。"
    # The copying loop is cut short (a line kept at most twice).
    assert parsed.text == "LOFOTR\nVikingmuseum\nVikingmuseum\nVik"
    assert parsed.keywords == ()
    nothing = {"choices": [{"finish_reason": "length", "message": {"content": '{"descr'}}]}
    with pytest.raises(describe.DescribeError):
        describe.parse_answer(nothing, 30.0)


# --- The background task and the API, with a fake model ----------------------------------------


class FakeReader:
    """Reads a photo by its colour; remembers which models were started."""

    started: ClassVar[list[str]] = []
    fail_dark = True

    def __init__(self, folder: Path, reserve_mib: int | None) -> None:
        self.model = ""

    def start(self, model_id: str) -> None:
        FakeReader.started.append(model_id)
        self.model = model_id

    def read(self, image: Image.Image) -> describe.Description:
        r, g, b = image.convert("RGB").resize((1, 1)).getpixel((0, 0))  # type: ignore[misc]
        if max(r, g, b) < 60 and FakeReader.fail_dark:
            raise describe.DescribeError("the model gave up")
        if r > b:
            return describe.Description(
                "红色的日落，海边的酒吧", "SUNSET BAR\nHappy hour", ("日落", "酒吧"), 900, 40, 3.0
            )
        return describe.Description(
            "蓝色的海湾和古城", "Stari Grad Kotor", ("海湾", "古城"), 900, 30, 2.0
        )

    def stop(self) -> None:
        pass


@pytest.fixture
def vlm_app(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    from lumen.vlm import pipeline
    from lumen.vlm.models import FINE_MODEL, MODELS, llama_server, models_dir

    # Model files where the settings say (empty files: the fake model does the reading).
    folder = tmp_path / "vlm"
    llama_server(folder).parent.mkdir(parents=True)
    llama_server(folder).write_bytes(b"")
    for spec in (MODELS[DEFAULT_MODEL], MODELS[FINE_MODEL]):
        for name in spec.file_names():
            (models_dir(folder) / spec.folder).mkdir(parents=True, exist_ok=True)
            (models_dir(folder) / spec.folder / name).write_bytes(b"")
    photos = tmp_path / "Photos"
    make_jpeg(photos / "red.jpg", color=(220, 60, 40), taken="2020:01:01 10:00:00")
    make_jpeg(photos / "blue.jpg", color=(30, 60, 220), taken="2020:01:02 10:00:00")
    make_jpeg(photos / "dark.jpg", color=(10, 10, 10), taken="2020:01:03 10:00:00")

    FakeReader.started = []
    pipeline.set_reader_factory(FakeReader)
    app = create_app(Settings(data_dir=tmp_path / "data", log_to_file=False), TOKEN)
    try:
        with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            client.post("/api/v1/storage-roots", json={"path": str(photos)})
            wait_idle(app.state.db)
            yield client, folder
    finally:
        pipeline.set_reader_factory(None)


def names(client: TestClient, **params: object) -> list[str]:
    items = client.get("/api/v1/assets", params={"limit": 50, **params}).json()["items"]
    return sorted(item["file_name"] for item in items)


def test_photos_are_read_and_found_by_what_is_in_them(vlm_app: tuple[TestClient, Path]) -> None:
    client, folder = vlm_app
    db = client.app.state.db  # type: ignore[attr-defined]
    status = client.get("/api/v1/vlm/status").json()
    assert status["enabled"] is False and status["runtime_installed"] is False  # default folder
    assert [m["role"] for m in status["models"]] == ["default", "fine"]

    settings = {"vlm_folder": str(folder), "vlm_enabled": True, "vlm_scope": "all"}
    assert client.patch("/api/v1/settings", json=settings).status_code == 200
    wait_idle(db)
    status = client.get("/api/v1/vlm/status").json()
    assert status["runtime_installed"] and all(m["downloaded"] for m in status["models"])
    assert (status["described"], status["to_read"]) == (3, 0)
    assert FakeReader.started == [DEFAULT_MODEL]

    # The description, the text and the keywords are searchable.
    assert names(client, q="Kotor") == ["blue.jpg"]
    assert names(client, q="海边的酒吧") == ["red.jpg"]
    assert names(client, q="happy hour") == ["red.jpg"]
    ids = {item["file_name"]: item["id"] for item in client.get("/api/v1/assets").json()["items"]}
    detail = client.get(f"/api/v1/assets/{ids['blue.jpg']}").json()["description"]
    assert detail["text"] == "Stari Grad Kotor" and detail["keywords"] == ["海湾", "古城"]
    assert detail["fine"] is False and detail["model"] == DEFAULT_MODEL
    # A photo the model could not read is kept (empty), so it is not retried every run.
    assert (
        client.get(f"/api/v1/assets/{ids['dark.jpg']}").json()["description"]["description"] == ""
    )

    # Asked again, with the careful model: read first, by that model.
    FakeReader.fail_dark = False
    queued = client.post(
        "/api/v1/vlm/describe", json={"asset_ids": [ids["dark.jpg"]], "fine": True}
    )
    assert queued.status_code == 202 and queued.json()["queued"] == 1
    wait_idle(db)
    assert FakeReader.started[-1] == FINE_MODEL
    detail = client.get(f"/api/v1/assets/{ids['dark.jpg']}").json()["description"]
    assert detail["fine"] is True and detail["description"] == "蓝色的海湾和古城"
    assert client.get("/api/v1/vlm/status").json()["requested"] == 0
    FakeReader.fail_dark = True

    videos_only = client.post("/api/v1/vlm/describe", json={"asset_ids": [99999]})
    assert videos_only.status_code == 400


def test_priority_order(vlm_app: tuple[TestClient, Path]) -> None:
    from lumen.vlm import pipeline

    client, _ = vlm_app
    db = client.app.state.db  # type: ignore[attr-defined]
    ids = {item["file_name"]: item["id"] for item in client.get("/api/v1/assets").json()["items"]}
    with db.session() as conn:
        # Taken in 2020 (imported just now does not count as recent).
        assert pipeline.library_order(conn, "priority") == []
        conn.execute("UPDATE media_assets SET rating = 4 WHERE id = ?", (ids["red.jpg"],))
        conn.execute("UPDATE media_assets SET is_favorite = 1 WHERE id = ?", (ids["dark.jpg"],))
        assert pipeline.library_order(conn, "priority") == [ids["dark.jpg"], ids["red.jpg"]]
        # Photos with text come next; "all" adds the rest, newest first.
        ranked = pipeline.library_order(conn, "priority", [ids["blue.jpg"]])
        assert ranked[-1] == ids["blue.jpg"]
        assert pipeline.library_order(conn, "all")[-1] == ids["blue.jpg"]
        # A photo taken last week is a key photo too.
        conn.execute(
            "UPDATE media_assets SET capture_time = strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')"
            " WHERE id = ?",
            (ids["blue.jpg"],),
        )
        assert ids["blue.jpg"] in pipeline.library_order(conn, "priority")


def test_a_request_made_while_reading_is_read_next(vlm_app: tuple[TestClient, Path]) -> None:
    from lumen.vlm import pipeline

    client, folder = vlm_app
    db = client.app.state.db  # type: ignore[attr-defined]
    ids = {item["file_name"]: item["id"] for item in client.get("/api/v1/assets").json()["items"]}
    order: list[int] = []
    original = FakeReader.read

    def read(self: FakeReader, image: Image.Image) -> describe.Description:
        # While the first photo (dark, the newest) is read, the user asks for the red one
        # (the oldest, otherwise read last), carefully.
        if not order:
            with db.session() as conn:
                pipeline.request(conn, [ids["red.jpg"]], fine=True)
        order.append(len(order))
        return original(self, image)

    FakeReader.fail_dark = False
    FakeReader.read = read  # type: ignore[method-assign]
    try:
        body = {"vlm_folder": str(folder), "vlm_enabled": True, "vlm_scope": "all"}
        client.patch("/api/v1/settings", json=body)
        wait_idle(db)
    finally:
        FakeReader.read = original  # type: ignore[method-assign]
        FakeReader.fail_dark = True
    # Default model for the first photo, then the careful one for the request, then back.
    assert FakeReader.started == [DEFAULT_MODEL, FINE_MODEL, DEFAULT_MODEL]
    red = client.get(f"/api/v1/assets/{ids['red.jpg']}").json()["description"]
    assert red["fine"] is True
    assert client.get("/api/v1/vlm/status").json()["described"] == 3
