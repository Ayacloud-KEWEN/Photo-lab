from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lumen import API_VERSION, __version__


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_version"] == __version__
    assert body["api_version"] == API_VERSION
    assert body["database"]["status"] == "ok"
    assert body["database"]["schema_version"] >= 1
    assert response.headers["x-request-id"]


def test_requests_without_token_are_rejected(client: TestClient) -> None:
    for headers in ({"Authorization": ""}, {"Authorization": "Bearer wrong"}):
        response = client.get("/api/v1/health", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
    assert client.get("/api/v1/openapi.json", headers={"Authorization": ""}).status_code == 401


def test_cors_preflight_for_tauri_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/storage-roots",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_storage_root_lifecycle(client: TestClient, photo_dir: Path) -> None:
    assert client.get("/api/v1/storage-roots").json() == {"items": []}

    created = client.post("/api/v1/storage-roots", json={"path": str(photo_dir)})
    assert created.status_code == 201
    root = created.json()
    assert root["path"] == str(photo_dir)
    assert root["status"] == "pending_scan"
    assert root["is_available"] is True

    listed = client.get("/api/v1/storage-roots").json()["items"]
    assert [item["id"] for item in listed] == [root["id"]]

    duplicate = client.post("/api/v1/storage-roots", json={"path": str(photo_dir)})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"

    deleted = client.delete(f"/api/v1/storage-roots/{root['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/storage-roots").json() == {"items": []}
    assert (photo_dir / "2026" / "IMG_0001.JPG").exists()


def test_create_with_missing_directory(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/v1/storage-roots", json={"path": str(tmp_path / "nope")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_path"


def test_create_validates_body(client: TestClient) -> None:
    for body in ({}, {"path": ""}, {"path": "C:\\x", "unexpected": 1}):
        response = client.post("/api/v1/storage-roots", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_delete_unknown_root(client: TestClient) -> None:
    response = client.delete("/api/v1/storage-roots/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_unknown_route(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
