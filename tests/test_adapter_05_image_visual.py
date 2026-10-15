from pathlib import Path
from types import SimpleNamespace


def test_workbench_accepts_the_cached_checkpoint_named_by_open_clip(tmp_path, monkeypatch):
    import open_clip
    from msa_indexer.adapters import _workbench_sandbox as sandbox
    from msa_indexer.models.clip_artifacts import CLIP_CHECKPOINT_SHA256, CLIP_HF_REPO

    cfg = open_clip.get_pretrained_cfg("ViT-L-14", "openai")
    assert cfg["hf_hub"].rstrip("/") == CLIP_HF_REPO
    repo_cache = tmp_path / "clip" / f"models--{CLIP_HF_REPO.replace('/', '--')}" / "snapshots" / "revision"
    checkpoint = repo_cache / "open_clip_model.safetensors"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"fixture weights")

    class FakeDigest:
        def update(self, _chunk):
            pass

        def hexdigest(self):
            return CLIP_CHECKPOINT_SHA256[checkpoint.name]

    monkeypatch.setattr(sandbox.hashlib, "sha256", lambda: FakeDigest())
    found, reason = sandbox._clip_checkpoint(SimpleNamespace(
        models_dir=tmp_path, model_name="ViT-L-14", pretrained="openai",
    ))
    assert found == checkpoint
    assert reason is None


def test_image_visual_folder_stages_every_image_once_and_returns_bounded_results(tmp_path, monkeypatch):
    from msa_indexer.adapters import _workbench_sandbox as sandbox

    source_root = tmp_path / "source"
    (source_root / "nested").mkdir(parents=True)
    first = source_root / "first.jpg"
    second = source_root / "nested" / "second.png"
    movie = source_root / "clip.mp4"
    hidden = source_root / ".hidden.jpg"
    first.write_bytes(b"first image")
    second.write_bytes(b"second image")
    movie.write_bytes(b"video")
    hidden.write_bytes(b"hidden image")
    source = SimpleNamespace(name="sample", path=str(source_root))
    observed = {}
    capability_calls = []

    monkeypatch.setattr(sandbox, "index_capability", lambda _config, *, force_object_detection=False: (
        capability_calls.append(force_object_detection) or {"available": True, "reason": None}
    ))
    monkeypatch.setattr(sandbox, "_clip_checkpoint", lambda _config: (tmp_path / "clip-weights", None))

    def fake_index(
        _config, _source, _workspace, staged_root, _checkpoint, *,
        result_limit, after_index, force_object_detection,
    ):
        assert force_object_detection is True
        paths = sorted(path.relative_to(staged_root).as_posix() for path in staged_root.rglob("*") if path.is_file())
        observed["paths"] = paths
        observed["bytes"] = [(staged_root / path).read_bytes() for path in paths]
        return len(paths), len(paths), {}, [{"relative_path": path} for path in paths[:result_limit]]

    monkeypatch.setattr(sandbox, "_run_staged_source", fake_index)
    result = sandbox.run_image_folder(SimpleNamespace(), source, result_limit=1)

    assert capability_calls == [True]
    assert observed["paths"] == ["first.jpg", "nested/second.png"]
    assert observed["bytes"] == [b"first image", b"second image"]
    assert result["scope"] == "whole_configured_source_images"
    assert result["images_found"] == result["images_processed"] == 2
    assert result["image_embeddings"] == 2
    assert result["complete"] is True
    assert result["results_truncated"] is True
    assert len(result["results"]) == 1
    assert result["persisted"] is False
    assert first.read_bytes() == b"first image"
    assert second.read_bytes() == b"second image"
    assert movie.read_bytes() == b"video"
    assert hidden.read_bytes() == b"hidden image"


def test_staged_image_visual_run_forces_detection_only_on_isolated_config(tmp_path, monkeypatch):
    from msa_indexer.adapters import _workbench_sandbox as sandbox
    from msa_indexer.db.sqlite_store import SQLiteStore

    config = SimpleNamespace(enable_object_detection=False)
    source = SimpleNamespace(name="sample", path=str(tmp_path))
    workspace = tmp_path / "workspace"
    staged_root = workspace / "source"
    staged_root.mkdir(parents=True)
    checkpoint = tmp_path / "clip-weights"

    def copy_models(_config, target, _checkpoint, *, force_object_detection, include_object_detection=None):
        assert force_object_detection is True
        local = target / "clip" / "weights"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"model")
        return local

    def fake_run_index(isolated, *, stop_after_local_finalize):
        assert stop_after_local_finalize is True
        assert isolated.object_detection_override is True
        assert isolated.enable_object_detection is False
        db = SQLiteStore(isolated.sqlite_path)
        db.init_schema(Path(__file__).parents[1] / "src/msa_indexer/db/schema.sql")
        db.close()

    monkeypatch.setattr(sandbox, "_copy_model_cache", copy_models)
    monkeypatch.setattr(sandbox, "run_index", fake_run_index)
    result = sandbox._run_staged_source(
        config, source, workspace, staged_root, checkpoint,
        result_limit=1, force_object_detection=True,
    )

    processed, embeddings, summary, details = result
    assert (processed, embeddings, details) == (0, 0, [])
    assert summary["video_keyframes"] == 0
    assert not hasattr(config, "object_detection_override")


def test_image_visual_adapter_reports_embeddings_objects_faces_and_status(tmp_path, monkeypatch):
    import numpy as np
    from msa_indexer.adapters import adapter_05_image_visual as adapter
    from msa_indexer.db.sqlite_store import SQLiteStore

    database = tmp_path / "preview.sqlite"
    db = SQLiteStore(database)
    db.init_schema(Path(__file__).parents[1] / "src/msa_indexer/db/schema.sql")
    db.upsert_media({
        "media_id": "image-id", "path": "temporary/image.jpg", "source_name": "fixture",
        "rel_path": "image.jpg", "mime": "image/jpeg",
    })
    db.upsert_image_embedding("image-id", np.asarray([0.1, 0.2], dtype=np.float32), "test-clip")
    db.add_tags("image-id", ["tree"])
    db.add_faces("image-id", [{
        "face_id": "image-id:f0", "bbox": [0.1, 0.2, 0.3, 0.4], "confidence": 0.9,
        "gender": None, "age": None,
    }])
    db.set_pipeline_status("image-id", "object_detection", "completed", model_name="test")
    db.commit()

    def run_one_file(_config, _source, _path, *, after_index, **_kwargs):
        return after_index(db, None, None, "image-id")

    monkeypatch.setattr(adapter, "run_one_file", run_one_file)
    result = adapter.preview_image_visual(SimpleNamespace(), SimpleNamespace(name="fixture"), "image.jpg")
    visual = result["image_visual"]
    assert visual["embedding"] == {"dimension": 2, "model": "test-clip"}
    assert visual["object_tags"] == ["tree"]
    assert visual["faces"][0]["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert visual["detector_status"]["object_detection_done"] is True
    db.close()


def test_image_visual_route_runs_whole_source_without_file_selection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from msa_apps.search_api import app as app_module
    from msa_indexer.adapters import adapter_05_image_visual

    source = SimpleNamespace(name="sample", path=str(tmp_path), enabled=True)
    config = SimpleNamespace(media_sources=[source], models_dir=tmp_path)
    monkeypatch.setattr(app_module, "_get_config", lambda _request: config)
    monkeypatch.setattr(app_module, "_workbench_stage_capabilities", lambda _config: {
        "image-visual": {"available": True, "reason": None},
    })
    monkeypatch.setattr(adapter_05_image_visual, "preview_image_visual_folder", lambda _config, _source: {
        "scope": "whole_configured_source_images", "images_found": 2,
        "images_processed": 2, "results": [], "persisted": False,
    })

    response = TestClient(app_module.app).post("/adapters/image-visual/run?source_name=sample")
    assert response.status_code == 200
    assert response.json()["scope"] == "whole_configured_source_images"
    assert response.json()["images_found"] == 2
    assert response.json()["persisted"] is False
