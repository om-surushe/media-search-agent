from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from msa_apps.search_api import app as app_module
from msa_apps.search_api import setup_models
from msa_apps.search_api.setup_models import SetupManager


def test_catalog_reports_app_model_paths_and_unavailable_entries(monkeypatch, tmp_path):
    manager = SetupManager()
    monkeypatch.setattr(setup_models, "get_manager", lambda: manager)
    monkeypatch.setattr(app_module, "_get_config", lambda _request: SimpleNamespace(models_dir=tmp_path))

    response = TestClient(app_module.app).get("/api/models/catalog")

    assert response.status_code == 200
    payload = response.json()
    models = {model["id"]: model for model in payload["models"]}
    assert models["clip-vit-b32"]["path"] == str(tmp_path / "commercial/clip-vit-b32/snapshot")
    assert models["clip-vit-b32"]["downloadable"] is True
    assert models["gemini-embedding-2"]["downloadable"] is False
    assert payload["hardware"]["accelerator"] in {"cpu", "cuda", "mps"}


def test_conditional_download_requires_explicit_evaluation_acknowledgement(monkeypatch, tmp_path):
    manager = SetupManager()
    start = Mock()
    monkeypatch.setattr(setup_models, "get_manager", lambda: manager)
    monkeypatch.setattr(manager, "start_if_needed", start)
    monkeypatch.setattr(app_module, "_get_config", lambda _request: SimpleNamespace(models_dir=tmp_path))
    monkeypatch.setattr(app_module, "_search_browse_read_only", lambda: False)
    client = TestClient(app_module.app)

    refused = client.post("/api/models/sface/download", json={})
    assert refused.status_code == 409
    start.assert_not_called()

    accepted = client.post("/api/models/sface/download", json={"confirm_experimental": True})
    assert accepted.status_code == 202
    assert accepted.json() == {"status": "preparing", "model_id": "sface"}
    start.assert_called_once_with(tmp_path, {"sface"})


def test_hosted_and_gated_models_cannot_be_downloaded_as_local_weights(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "_get_config", lambda _request: SimpleNamespace(models_dir=tmp_path))
    monkeypatch.setattr(app_module, "_search_browse_read_only", lambda: False)
    client = TestClient(app_module.app)

    for model_id in ("indicconformer-600m", "gemini-embedding-2"):
        response = client.post(
            f"/api/models/{model_id}/download",
            json={"confirm_experimental": True},
        )
        assert response.status_code == 409
