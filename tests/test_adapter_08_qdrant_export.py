from pathlib import Path
from types import SimpleNamespace


def test_qdrant_export_capability_can_prepare_only_model_cache_failures(monkeypatch):
    from msa_indexer.adapters import adapter_08_qdrant_export as adapter

    monkeypatch.setattr(adapter.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(adapter, "index_capability", lambda _config: {"available": True, "reason": None})
    assert adapter.qdrant_export_capability(SimpleNamespace()) == {
        "available": True, "reason": None, "can_prepare": False,
    }

    monkeypatch.setattr(adapter, "index_capability", lambda _config: {
        "available": False, "reason": "Managed CLIP weights are not cached with a valid checksum; start model setup first.",
    })
    assert adapter.qdrant_export_capability(SimpleNamespace())["can_prepare"] is True

    monkeypatch.setattr(adapter.importlib.util, "find_spec", lambda _name: None)
    assert adapter.qdrant_export_capability(SimpleNamespace()) == {
        "available": False, "reason": "qdrant-client is not installed.", "can_prepare": False,
    }


def test_qdrant_export_processes_complete_source_folder(tmp_path, monkeypatch):
    from msa_indexer.adapters import _workbench_sandbox as sandbox

    root = tmp_path / "source"
    (root / "nested").mkdir(parents=True)
    image = root / "photo.png"
    video = root / "nested" / "clip.mp4"
    ignored = root / "notes.txt"
    hidden = root / ".hidden.jpg"
    image.write_bytes(b"image")
    video.write_bytes(b"video")
    ignored.write_bytes(b"text")
    hidden.write_bytes(b"hidden")
    source = SimpleNamespace(name="sample", path=str(root))
    captured = {}
    monkeypatch.setattr(sandbox, "index_capability", lambda _config, **_kwargs: {"available": True, "reason": None})
    monkeypatch.setattr(sandbox, "_clip_checkpoint", lambda _config: (tmp_path / "clip.pt", None))

    def fake_run(_config, _source, _workspace, staged_root, _checkpoint, *, result_limit, after_source):
        captured["files"] = sorted(path.relative_to(staged_root).as_posix() for path in staged_root.rglob("*") if path.is_file())
        captured["source_bytes"] = (image.read_bytes(), video.read_bytes())
        captured["limit"] = result_limit
        return 2, 1, {"qdrant_export": {"store": "disposable"}}, [
            {"relative_path": "photo.png"}, {"relative_path": "nested/clip.mp4"},
        ]

    monkeypatch.setattr(sandbox, "_run_staged_source", fake_run)
    result = sandbox.run_source_folder(SimpleNamespace(), source)

    assert result["scope"] == "whole_configured_source"
    assert result["media_found"] == result["media_processed"] == 2
    assert result["image_embeddings"] == 1
    assert result["complete"] is True
    assert result["summary"]["qdrant_export"]["store"] == "disposable"
    assert captured["files"] == ["nested/clip.mp4", "photo.png"]
    assert captured["source_bytes"] == (b"image", b"video")
    assert captured["limit"] == 25
    assert result["persisted"] is False
    assert ignored.read_bytes() == b"text"
    assert hidden.read_bytes() == b"hidden"


def test_qdrant_export_folder_uses_only_embedded_disposable_store(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_08_qdrant_export as adapter
    from msa_indexer.db import qdrant_export

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    isolated = SimpleNamespace(sqlite_path=workspace / "preview.sqlite")
    calls = []

    class FakeDB:
        def get_index_state(self):
            return {"index_version_seq": 3, "index_version_ts": "2025-01-01T00:00:00Z"}

    def capture(name, result):
        def run(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result
        return run

    monkeypatch.setattr(qdrant_export, "export_images_to_qdrant", capture("images", {"sent": 1, "errors": 0}))
    monkeypatch.setattr(qdrant_export, "export_video_frames_to_qdrant", capture("video", {"sent": 2, "errors": 0}))
    monkeypatch.setattr(qdrant_export, "export_faces_to_qdrant", capture("faces", {"sent": 3, "errors": 0}))
    monkeypatch.setattr(qdrant_export, "delete_tombstoned_points_from_qdrant", capture("deletions", {"deleted_points": 0}))
    monkeypatch.setattr(qdrant_export, "record_qdrant_export_version", capture("version", None))
    monkeypatch.setattr(qdrant_export, "get_qdrant_export_version", lambda **kwargs: {"index_version_seq": 3})

    def fake_folder(config, source, *, result_limit, after_source):
        summary = after_source(FakeDB(), isolated, workspace)
        return {
            "scope": "whole_configured_source", "media_found": 2,
            "summary": summary, "results": [], "persisted": False,
        }

    monkeypatch.setattr(adapter, "run_source_folder", fake_folder)
    result = adapter.preview_qdrant_export_folder(SimpleNamespace(), SimpleNamespace(name="sample", path="/unused"))

    preview_store = workspace / "qdrant-preview"
    assert result["scope"] == "whole_configured_source"
    assert result["summary"]["qdrant_export"]["version_recorded"] is True
    assert result["summary"]["qdrant_export"]["store"] == "disposable"
    assert result["persisted"] is False
    assert len(calls) == 5
    assert all(kwargs["qdrant_path"] == preview_store for _name, _args, kwargs in calls)
    assert all(Path(str(kwargs["qdrant_path"])).is_relative_to(workspace) for _name, _args, kwargs in calls)


def test_qdrant_export_catalog_and_folder_endpoint_do_not_require_sample(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from msa_apps.search_api import app as app_module
    from msa_indexer.adapters import adapter_08_qdrant_export as adapter

    source = SimpleNamespace(name="sample", path=str(tmp_path), enabled=True)
    config = SimpleNamespace(media_sources=[source], models_dir=tmp_path)
    monkeypatch.setattr(app_module, "_get_config", lambda _request: config)
    capability = {"available": True, "reason": None, "can_prepare": False}
    monkeypatch.setattr(app_module, "_workbench_stage_capabilities", lambda _config: {
        "qdrant-export": capability,
    })
    calls = []
    monkeypatch.setattr(adapter, "preview_qdrant_export_folder", lambda _config, _source: calls.append("whole_source") or {
        "scope": "whole_configured_source", "media_found": 2,
        "summary": {"qdrant_export": {"store": "disposable"}}, "persisted": False,
    })
    client = TestClient(app_module.app)

    catalog = {stage["id"]: stage for stage in client.get("/adapters").json()}
    assert catalog["qdrant-export"]["can_prepare"] is False
    capability.update(available=False, reason="Managed CLIP weights are missing.", can_prepare=True)
    preparable = {stage["id"]: stage for stage in client.get("/adapters").json()}
    assert preparable["qdrant-export"]["runnable"] is False
    assert preparable["qdrant-export"]["can_prepare"] is True
    capability.update(available=True, reason=None, can_prepare=False)
    response = client.post("/adapters/qdrant-export/run", params={"source_name": "sample"})
    file_response = client.post("/adapters/qdrant-export/run", params={
        "source_name": "sample", "relative_path": "clip.mp4",
    })

    assert response.status_code == 200
    assert response.json()["scope"] == "whole_configured_source"
    assert response.json()["summary"]["qdrant_export"]["store"] == "disposable"
    assert response.json()["persisted"] is False
    assert file_response.status_code == 400
    assert calls == ["whole_source"]
