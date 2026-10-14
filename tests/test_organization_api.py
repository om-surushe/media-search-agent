from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from msa_indexer.db.sqlite_store import SQLiteStore


MEDIA_ID = "b" * 64


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "media.sqlite"
    with SQLiteStore(db_path) as store:
        store.init_schema_no_migrations(Path(__file__).parents[1] / "src/msa_indexer/db/schema.sql")
        store.conn.execute("INSERT INTO media(media_id,path,mime) VALUES (?,?,?)", (MEDIA_ID, str(tmp_path / "original.jpg"), "image/jpeg"))
        store.commit()
    (tmp_path / "original.jpg").write_bytes(b"original")
    cfg = SimpleNamespace(sqlite_path=db_path, log_dir=tmp_path / "logs", models_dir=tmp_path / "models", log_level="ERROR")
    from msa_apps.search_api.app import create_app
    app = create_app(config_override=cfg, reset_dependencies=True)
    return TestClient(app), tmp_path


def test_api_tags_collections_persist_and_never_touch_original(client):
    test_client, root = client
    created = test_client.post("/collections", json={"name": "Trip", "description": "Summer"})
    assert created.status_code == 201
    collection_id = created.json()["collection_id"]
    assert test_client.post("/collections", json={"name": "trip"}).status_code == 409

    assert test_client.post(f"/collections/{collection_id}/items", json={"media_ids": [MEDIA_ID]}).json() == {"added": 1}
    assert test_client.put(f"/media/{MEDIA_ID}/tags", json={"tags": [" family ", "Family", "travel"]}).json()["tags"] == ["family", "travel"]
    assert test_client.get(f"/media/{MEDIA_ID}/tags").json()["tags"] == ["family", "travel"]
    assert test_client.get("/collections").json()["items"][0]["media_count"] == 1
    assert test_client.get(f"/collections/{collection_id}/items").json()["items"][0]["id"] == MEDIA_ID
    assert test_client.get("/user-tags").json() == ["family", "travel"]
    filtered = test_client.get("/media", params={"user_tags": "family"}).json()
    assert [item["id"] for item in filtered["items"]] == [MEDIA_ID]
    assert filtered["items"][0]["user_tags"] == ["family", "travel"]
    assert (root / "original.jpg").read_bytes() == b"original"

    assert test_client.delete(f"/collections/{collection_id}").status_code == 204
    assert test_client.get("/collections").json()["count"] == 0


def test_organization_write_endpoints_reject_read_only_mode(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setenv("MSA_SEARCH_BROWSE_READ_ONLY", "1")
    assert test_client.post("/collections", json={"name": "No"}).status_code == 409
    assert test_client.put(f"/media/{MEDIA_ID}/tags", json={"tags": ["no"]}).status_code == 409
