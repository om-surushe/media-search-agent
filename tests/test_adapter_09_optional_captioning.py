import sqlite3
from types import SimpleNamespace


def test_caption_stage_processes_both_media_types_and_returns_bounded_results(tmp_path, monkeypatch):
    from msa_indexer import captioning
    from msa_indexer.adapters import adapter_09_optional_captioning as adapter
    from msa_indexer.adapters import _workbench_sandbox as sandbox

    source = SimpleNamespace(name="source", path=str(tmp_path / "source"))
    cache = tmp_path / "cache"
    model_name = f"models--{captioning.MODEL_ID.replace('/', '--')}"
    model = cache / model_name
    model.mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"local checkpoint")
    python = tmp_path / "python"
    python.touch()
    captured = {}

    monkeypatch.setattr(captioning, "validate_captioning_runtime", lambda: (python, cache, tmp_path / "worker.py"))

    class FakeDB:
        def __init__(self):
            self.conn = sqlite3.connect(":memory:")
            self.conn.executescript(
                "CREATE TABLE image_caption(media_id, caption, model_id, prompt_version, generated_at_utc, status);"
                "CREATE TABLE video_scene_caption(video_id, keyframe_id, timestamp, caption, model_id, "
                "prompt_version, generated_at_utc, status);"
            )
            self.conn.execute(
                "INSERT INTO image_caption VALUES ('image-id', 'A red car on a road.', 'model', 'p1', 'now', 'completed')"
            )
            self.conn.execute(
                "INSERT INTO video_scene_caption VALUES ('video-id', 1, 1.5, 'A person walks through the scene.', "
                "'model', 'p2', 'now', 'completed')"
            )

    def fake_caption_stages(config, _stop_event, summary, _export_blocked, emit_summary, *, python_path, cache_dir):
        captured["flags"] = (config.image_captions_enabled, config.video_scene_captions_enabled)
        captured["python"] = python_path
        captured["cache"] = cache_dir
        assert (cache_dir / model_name / "model.safetensors").read_bytes() == b"local checkpoint"
        summary["captioning"] = {"status": "completed", "generated": 1, "failed": 0}
        summary["video_scene_captioning"] = {"status": "completed", "generated": 1, "failed": 0}
        emit_summary(**summary)

    monkeypatch.setattr(adapter, "run_captioning_stages", fake_caption_stages, raising=False)

    def fake_source_folder(_config, _source, *, result_limit, after_source, after_index):
        db = FakeDB()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        isolated = SimpleNamespace(sqlite_path=workspace / "preview.sqlite")
        summary = after_source(db, isolated, workspace)
        results = [
            {"relative_path": "photo.jpg", **after_index(db, isolated, workspace, "image-id")},
            {"relative_path": "nested/clip.mp4", **after_index(db, isolated, workspace, "video-id")},
        ]
        return {
            "scope": "whole_configured_source", "media_found": 2,
            "media_processed": 2, "summary": summary, "results": results[:result_limit],
            "persisted": False,
        }

    monkeypatch.setattr(sandbox, "run_source_folder", fake_source_folder)
    monkeypatch.setattr(adapter, "captioning_stage_capability", lambda _config: {"available": True, "reason": None})
    result = adapter.preview_captioning_folder(SimpleNamespace(), source)

    assert result["scope"] == "whole_configured_source"
    assert result["media_found"] == 2
    assert captured["flags"] == (True, True)
    assert captured["python"] == python
    assert captured["cache"] == tmp_path / "workspace" / "caption-model-cache"
    assert result["summary"]["captioning"]["generated"] == 1
    assert result["summary"]["video_scene_captioning"]["generated"] == 1
    assert result["results"][0]["image_captions"][0]["caption"] == "A red car on a road."
    assert result["results"][0]["video_scene_captions"] == []
    assert result["results"][1]["video_scene_captions"][0]["timestamp"] == 1.5
    assert result["results"][1]["video_scene_captions"][0]["caption"] == "A person walks through the scene."
    assert result["persisted"] is False


def test_caption_capability_redacts_configured_local_paths(tmp_path, monkeypatch):
    from msa_indexer import captioning
    from msa_indexer.adapters import adapter_09_optional_captioning as adapter

    secret_path = str(tmp_path / "private-model-cache")
    monkeypatch.setenv("MSA_CAPTION_CACHE_DIR", secret_path)
    def fail_runtime():
        raise RuntimeError(f"Cache unavailable: {secret_path}")

    monkeypatch.setattr(captioning, "validate_captioning_runtime", fail_runtime)
    capability = adapter.captioning_capabilities()["image_captions"]

    assert capability["available"] is False
    assert secret_path not in capability["reason"]
    assert "<local path>" in capability["reason"]


def test_caption_stage_api_and_catalog_run_whole_source_without_file_selection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from msa_apps.search_api import app as app_module
    from msa_indexer.adapters import adapter_09_optional_captioning as adapter

    source = SimpleNamespace(name="sample", path=str(tmp_path), enabled=True)
    config = SimpleNamespace(media_sources=[source], models_dir=tmp_path)
    monkeypatch.setattr(app_module, "_get_config", lambda _request: config)
    monkeypatch.setattr(app_module, "_workbench_stage_capabilities", lambda _config: {
        "captions": {"available": True, "reason": None},
    })
    calls = []
    monkeypatch.setattr(adapter, "preview_captioning_folder", lambda _config, _source: calls.append("all") or {
        "scope": "whole_configured_source", "media_found": 2,
        "summary": {"captioning": {"generated": 1}, "video_scene_captioning": {"generated": 1}},
        "persisted": False,
    })
    client = TestClient(app_module.app)

    catalog = {stage["id"]: stage for stage in client.get("/adapters").json()}
    response = client.post("/adapters/captions/run", params={"source_name": "sample"})
    file_response = client.post("/adapters/captions/run", params={
        "source_name": "sample", "relative_path": "photo.jpg",
    })

    assert catalog["captions"]["runnable"] is True
    assert response.status_code == 200
    assert response.json()["scope"] == "whole_configured_source"
    assert response.json()["summary"]["video_scene_captioning"]["generated"] == 1
    assert response.json()["persisted"] is False
    assert file_response.status_code == 400
    assert calls == ["all"]
