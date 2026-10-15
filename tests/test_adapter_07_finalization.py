from types import SimpleNamespace


def test_finalization_adapter_uses_index_capability_and_disposable_preview(monkeypatch):
    from msa_indexer.adapters import adapter_07_finalization as adapter

    config = SimpleNamespace()
    monkeypatch.setattr(adapter, "index_capability", lambda value: {
        "available": value is config, "reason": None,
    })
    assert adapter.finalization_capability(config)["available"] is True

    calls = []
    monkeypatch.setattr(adapter, "run_one_file", lambda *_args, **kwargs: calls.append(kwargs) or {
        "relative_path": "clip.mp4", "persisted": False,
    })
    result = adapter.preview_finalization(config, SimpleNamespace(name="sample"), "clip.mp4")
    assert result["relative_path"] == "clip.mp4"
    assert result["persisted"] is False
    assert calls == [{}]


def test_finalization_catalog_and_button_endpoint_require_selected_sample(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from msa_apps.search_api import app as app_module
    from msa_indexer.adapters import adapter_07_finalization as adapter

    source = SimpleNamespace(name="sample", path=str(tmp_path), enabled=True)
    config = SimpleNamespace(media_sources=[source], models_dir=tmp_path)
    monkeypatch.setattr(app_module, "_get_config", lambda _request: config)
    monkeypatch.setattr(app_module, "_workbench_stage_capabilities", lambda _config: {
        "finalization": {"available": True, "reason": None},
    })
    calls = []
    monkeypatch.setattr(adapter, "preview_finalization", lambda _config, _source, path: calls.append(path) or {
        "relative_path": path, "finalization": {"index_version": 1, "committed": True},
        "persisted": False,
    })
    client = TestClient(app_module.app)

    catalog = {stage["id"]: stage for stage in client.get("/adapters").json()}
    assert catalog["finalization"]["runnable"] is True
    missing_sample = client.post("/adapters/finalization/run", params={"source_name": "sample"})
    response = client.post("/adapters/finalization/run", params={
        "source_name": "sample", "relative_path": "clip.mp4",
    })

    assert missing_sample.status_code == 400
    assert response.status_code == 200
    assert response.json()["finalization"]["committed"] is True
    assert response.json()["persisted"] is False
    assert calls == ["clip.mp4"]
