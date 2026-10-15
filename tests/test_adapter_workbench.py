from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest

from msa_indexer.adapters.adapter_01_discovery import preview_media_entries, validated_sample_path
from msa_indexer.adapters.adapter_02_identity import preview_identity
from msa_indexer.adapters.adapter_03_metadata import preview_metadata
from msa_indexer.adapters.registry import ADAPTER_STAGES


def test_transcription_preview_uses_disposable_copy_and_does_not_persist(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_04_transcription as adapter
    from msa_indexer.models.asr import TranscriptResult

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video bytes")
    source = SimpleNamespace(name="sample", path=str(tmp_path))
    models_dir = tmp_path / "approved-model-cache"
    cached_checkpoint = models_dir / "whisper" / "base.pt"
    cached_checkpoint.parent.mkdir(parents=True)
    cached_checkpoint.write_bytes(b"fake cached model")
    observed = {}

    monkeypatch.setattr(adapter, "transcription_capability", lambda _path: {"available": True, "reason": None})
    monkeypatch.setattr(
        adapter, "WHISPER_MODEL_REVISION", hashlib.sha256(b"fake cached model").hexdigest(),
    )

    class FakeTranscriber:
        def __init__(self, isolated_models_dir, _device):
            observed["isolated_models_dir"] = str(isolated_models_dir)
            observed["isolated_checkpoint"] = (
                isolated_models_dir / "whisper" / "base.pt"
            ).read_bytes()

        def transcribe(self, path):
            observed["is_copy"] = path != video and path.is_file()
            observed["content"] = path.read_bytes()
            return TranscriptResult("transcribed", "en", ({"start": 1.0, "end": 2.0, "text": "private words"},))

    monkeypatch.setattr(adapter, "LocalWhisperTranscriber", FakeTranscriber)
    result = adapter.preview_transcription(source, "clip.mp4", models_dir)
    assert observed["is_copy"] is True
    assert observed["content"] == b"video bytes"
    assert observed["isolated_models_dir"] != str(models_dir)
    assert observed["isolated_checkpoint"] == b"fake cached model"
    assert result["segments"][0]["text"] == "private words"
    assert result["persisted"] is False
    assert str(tmp_path) not in str(result)
    assert video.read_bytes() == b"video bytes"


def test_transcription_rejects_bad_cached_weights_without_loading_or_overwriting_them(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_04_transcription as adapter

    source_root = tmp_path / "source"
    source_root.mkdir()
    video = source_root / "clip.mp4"
    video.write_bytes(b"video bytes")
    models_dir = tmp_path / "models"
    checkpoint = models_dir / "whisper" / "base.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"invalid weights")
    before = checkpoint.read_bytes()
    calls = []
    monkeypatch.setattr(adapter, "transcription_capability", lambda _path: {"available": True, "reason": None})
    monkeypatch.setattr(adapter, "LocalWhisperTranscriber", lambda *_args: calls.append(True))

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        adapter.preview_transcription(SimpleNamespace(name="sample", path=str(source_root)), "clip.mp4", models_dir)

    assert calls == []
    assert checkpoint.read_bytes() == before


def test_transcription_folder_processes_all_videos_with_bounded_results(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_04_transcription as adapter
    from msa_indexer.models.asr import TranscriptResult

    source_root = tmp_path / "source"
    (source_root / "nested").mkdir(parents=True)
    first = source_root / "first.mp4"
    second = source_root / "nested" / "second.mov"
    image = source_root / "photo.jpg"
    first.write_bytes(b"first video")
    second.write_bytes(b"second video")
    image.write_bytes(b"image")
    source = SimpleNamespace(name="sample", path=str(source_root))
    models_dir = tmp_path / "approved-model-cache"
    cached_checkpoint = models_dir / "whisper" / "base.pt"
    cached_checkpoint.parent.mkdir(parents=True)
    cached_checkpoint.write_bytes(b"fake cached model")
    observed = {"copies": []}

    monkeypatch.setattr(adapter, "transcription_capability", lambda _path: {"available": True, "reason": None})
    monkeypatch.setattr(adapter, "WHISPER_MODEL_REVISION", hashlib.sha256(b"fake cached model").hexdigest())

    class FakeTranscriber:
        def __init__(self, isolated_models_dir, _device):
            observed["isolated_models_dir"] = str(isolated_models_dir)
            observed["isolated_checkpoint"] = (isolated_models_dir / "whisper" / "base.pt").read_bytes()

        def transcribe(self, path):
            observed["copies"].append((path.is_file(), path.read_bytes()))
            segments = tuple(
                {"start": float(index), "end": float(index + 1), "text": "x" * 501}
                for index in range(25)
            )
            return TranscriptResult("transcribed", "en", segments)

    monkeypatch.setattr(adapter, "LocalWhisperTranscriber", FakeTranscriber)
    result = adapter.preview_transcription_folder(source, models_dir, result_limit=1)

    assert result["scope"] == "whole_configured_source_videos"
    assert result["videos_found"] == result["videos_transcribed"] == 2
    assert result["complete"] is True
    assert result["results_truncated"] is True
    assert len(result["results"]) == 1
    assert len(result["results"][0]["segments"]) == 20
    assert result["results"][0]["segments_truncated"] is True
    assert all(len(segment["text"]) == 500 for segment in result["results"][0]["segments"])
    assert observed["isolated_models_dir"] != str(models_dir)
    assert observed["isolated_checkpoint"] == b"fake cached model"
    assert len(observed["copies"]) == 2
    assert all(is_copy and content in (b"first video", b"second video") for is_copy, content in observed["copies"])
    assert result["persisted"] is False
    assert str(source_root) not in repr(result)
    assert first.read_bytes() == b"first video"
    assert second.read_bytes() == b"second video"
    assert image.read_bytes() == b"image"
    assert cached_checkpoint.read_bytes() == b"fake cached model"


def test_transcription_capability_does_not_claim_uncached_model(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_04_transcription as adapter

    monkeypatch.setattr(adapter.importlib.util, "find_spec", lambda _name: object())
    capability = adapter.transcription_capability(tmp_path)
    assert capability["available"] is False
    assert "not cached" in capability["reason"]


def test_index_sandbox_copies_only_selected_media_and_redirects_all_writes(tmp_path, monkeypatch):
    from msa_indexer.adapters import _workbench_sandbox as sandbox
    from msa_indexer.db.sqlite_store import SQLiteStore

    source_root = tmp_path / "source"
    (source_root / "album").mkdir(parents=True)
    selected = source_root / "album" / "photo.jpg"
    selected.write_bytes(b"selected")
    (source_root / "other.jpg").write_bytes(b"not selected")
    models = tmp_path / "models"
    checkpoint = models / "clip" / "weights.pt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"cached")
    config = SimpleNamespace(models_dir=models)
    source = SimpleNamespace(name="fixture", path=str(source_root))
    observed = {}

    monkeypatch.setattr(sandbox, "index_capability", lambda _config, **_kwargs: {"available": True, "reason": None})
    monkeypatch.setattr(sandbox, "_clip_checkpoint", lambda _config: (checkpoint, None))
    monkeypatch.setattr(sandbox, "_copy_model_cache", lambda _config, _target, _checkpoint, **_kwargs: None)

    def fake_run_index(isolated, stop_after_local_finalize=False):
        observed["sqlite"] = isolated.sqlite_path
        observed["qdrant"] = isolated.qdrant_path
        staged_root = Path(isolated.media_sources[0].path)
        observed["source_files"] = sorted(p.relative_to(staged_root).as_posix() for p in staged_root.rglob("*"))
        assert stop_after_local_finalize is True
        db = SQLiteStore(isolated.sqlite_path)
        db.init_schema(Path(__file__).parents[1] / "src/msa_indexer/db/schema.sql")
        try:
            db.upsert_media({
                "media_id": "preview-id", "path": str(staged_root / "album/photo.jpg"),
                "source_name": "fixture", "rel_path": "album/photo.jpg", "mime": "image/jpeg",
            })
        finally:
            db.close()

    monkeypatch.setattr(sandbox, "run_index", fake_run_index)
    result = sandbox.run_one_file(config, source, "album/photo.jpg", expected_type="image")
    assert result["relative_path"] == "album/photo.jpg"
    assert result["persisted"] is False
    assert observed["source_files"] == ["album", "album/photo.jpg"]
    assert observed["sqlite"] != getattr(config, "sqlite_path", None)
    assert observed["qdrant"].parent == observed["sqlite"].parent.parent
    assert str(source_root) not in str(result)
    assert selected.read_bytes() == b"selected"


def test_offline_model_runtime_redirects_torch_cache_and_blocks_network(tmp_path, monkeypatch):
    import os
    import socket
    from msa_indexer.adapters import _workbench_sandbox as sandbox

    monkeypatch.setenv("TORCH_HOME", "persistent-cache")
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    model_cache = tmp_path / "models"
    with sandbox._offline_model_runtime(model_cache):
        assert os.environ["TORCH_HOME"] == str(model_cache / "facenet_pytorch")
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        with pytest.raises(RuntimeError, match="network access is blocked"):
            socket.socket().connect(("127.0.0.1", 9))
    assert os.environ["TORCH_HOME"] == "persistent-cache"
    assert os.environ["HF_HUB_OFFLINE"] == "0"


def test_caption_capability_rejects_incomplete_cached_checkpoint(tmp_path, monkeypatch):
    import sys
    from msa_indexer.adapters import adapter_09_optional_captioning as adapter
    from msa_indexer.captioning import MODEL_ID, MODEL_REVISION

    cache = tmp_path / "caption-cache"
    snapshots = cache / f"models--{MODEL_ID.replace('/', '--')}" / "snapshots" / MODEL_REVISION
    snapshots.mkdir(parents=True)
    (snapshots / "config.json").write_text("{}")
    monkeypatch.setenv("MSA_CAPTION_PYTHON", sys.executable)
    monkeypatch.setenv("MSA_CAPTION_CACHE_DIR", str(cache))
    result = adapter.captioning_capabilities()
    assert result["image_captions"]["available"] is False
    assert "incomplete" in result["image_captions"]["reason"]


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
        observed["bytes"] = [ (staged_root / path).read_bytes() for path in paths ]
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


def test_video_keyframe_adapter_reports_full_coupled_stage_output(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_06_video_keyframes as adapter
    from msa_indexer.db.sqlite_store import SQLiteStore

    database = tmp_path / "preview.sqlite"
    db = SQLiteStore(database)
    db.init_schema(Path(__file__).parents[1] / "src/msa_indexer/db/schema.sql")
    db.upsert_media({
        "media_id": "video-id", "path": "temporary/video.mp4", "source_name": "fixture",
        "rel_path": "video.mp4", "mime": "video/mp4", "duration": 4.0,
    })
    db.add_shots("video-id", [(0.0, 4.0)], is_synthetic=True)
    db.add_keyframes("video-id", [{
        "shot_index": 0, "kf_index": 0, "timestamp": 2.0, "shot_start": 0.0,
        "shot_end": 4.0, "gps_lat": 1.0, "gps_lon": 2.0,
        "gps_source": "video_track", "tags": ["car"],
    }])
    db.conn.execute(
        "INSERT INTO video_keyframe_selection_state(video_id, selector_version, status, selected_count) "
        "VALUES ('video-id', 'selector-v1', 'completed', 1)"
    )
    db.conn.commit()

    def run_one_file(_config, _source, _path, *, expected_type, after_index):
        assert expected_type == "video"
        return after_index(db, None, None, "video-id")

    monkeypatch.setattr(adapter, "run_one_file", run_one_file)
    result = adapter.preview_video_keyframes(SimpleNamespace(), SimpleNamespace(name="fixture"), "video.mp4")
    summary = result["video_keyframes"]
    assert summary["shot_count"] == 1
    assert summary["shots"][0]["is_synthetic"] is True
    assert summary["keyframes"][0]["object_tags"] == ["car"]
    assert summary["keyframes"][0]["gps_source"] == "video_track"
    assert summary["selection_status"][0]["status"] == "completed"
    assert summary["frame_cache"] == {"decoded_frames": 0, "cached_renditions": 0}
    db.close()


def test_qdrant_export_adapter_uses_only_disposable_vector_store(tmp_path, monkeypatch):
    import numpy as np
    from msa_indexer.adapters import adapter_08_qdrant_export as adapter
    from msa_indexer.db.sqlite_store import SQLiteStore

    database = tmp_path / "preview.sqlite"
    qdrant_path = tmp_path / "qdrant-preview"

    def run_one_file(_config, _source, _path, *, after_index, **_kwargs):
        isolated = SimpleNamespace(sqlite_path=database)
        db = SQLiteStore(database)
        db.init_schema(Path(__file__).parents[1] / "src/msa_indexer/db/schema.sql")
        db.upsert_media({
            "media_id": "image-id", "path": "temporary/image.jpg", "source_name": "fixture",
            "rel_path": "image.jpg", "mime": "image/jpeg",
        })
        db.upsert_image_embedding("image-id", np.asarray([0.1, 0.2], dtype=np.float32), "test")
        db.bump_index_version()
        db.close()
        db = SQLiteStore(database)
        try:
            result = {"relative_path": "image.jpg", "persisted": False}
            result.update(after_index(db, isolated, tmp_path, "image-id"))
            return result
        finally:
            db.close()

    from msa_indexer.db import qdrant_export
    opened_paths = []
    original_client_factory = qdrant_export._new_qdrant_client

    def track_client(path=None):
        opened_paths.append(Path(path))
        return original_client_factory(path)

    monkeypatch.setattr(qdrant_export, "_new_qdrant_client", track_client)
    monkeypatch.setattr(adapter, "run_one_file", run_one_file)
    result = adapter.preview_qdrant_export(SimpleNamespace(), SimpleNamespace(name="fixture"), "image.jpg")
    assert result["qdrant_export"]["image"]["sent"] == 1
    assert result["qdrant_export"]["version_recorded"] is True
    assert result["qdrant_export"]["export_version"]["index_version_seq"] >= 1
    assert result["qdrant_export"]["store"] == "disposable"
    assert result["qdrant_export"]["persisted"] is False
    assert opened_paths and set(opened_paths) == {qdrant_path}
    assert qdrant_path.is_dir()


def test_identity_preview_processes_whole_source_without_unbounded_results(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_02_identity as adapter

    for name in ("a.jpg", "b.mp4", "c.png"):
        (tmp_path / name).write_bytes(name.encode())
    calls = []
    monkeypatch.setattr(adapter, "preview_identity", lambda _source, path: calls.append(path) or {"relative_path": path})

    result = adapter.preview_source_identity(SimpleNamespace(name="sample", path=str(tmp_path)), result_limit=2)

    assert set(calls) == {"a.jpg", "b.mp4", "c.png"}
    assert result["files_checked"] == 3
    assert len(result["results"]) == 2
    assert result["persisted"] is False


def test_metadata_preview_processes_whole_source_without_file_selection(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_03_metadata as adapter

    for name in ("a.jpg", "b.mp4"):
        (tmp_path / name).write_bytes(name.encode())
    calls = []
    monkeypatch.setattr(adapter, "preview_metadata", lambda _source, path: calls.append(path) or {"status": "completed", "relative_path": path})

    result = adapter.preview_source_metadata(SimpleNamespace(name="sample", path=str(tmp_path)))

    assert set(calls) == {"a.jpg", "b.mp4"}
    assert result["files_checked"] == result["completed"] == 2
    assert result["persisted"] is False


def test_preview_discovery_is_bounded_and_only_returns_media(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"a")
    (tmp_path / "b.mp4").write_bytes(b"bb")
    (tmp_path / "notes.txt").write_text("ignored")
    result = preview_media_entries(SimpleNamespace(name="sample", path=str(tmp_path)), limit=1)
    assert result["source"] == "sample"
    assert result["returned"] == 1
    assert result["has_more"] is True
    assert result["entries"][0]["extension"] in {".jpg", ".mp4"}
    assert len(ADAPTER_STAGES) == 9
    assert [stage["number"] for stage in ADAPTER_STAGES] == list(range(1, 10))
    assert [stage["id"] for stage in ADAPTER_STAGES if stage["runnable"]] == [
        "discovery", "identity", "metadata",
    ]


def test_identity_preview_hashes_only_validated_relative_file(tmp_path):
    source = SimpleNamespace(name="sample", path=str(tmp_path))
    media = tmp_path / "folder" / "image.jpg"
    media.parent.mkdir()
    media.write_bytes(b"sample bytes")
    result = preview_identity(source, "folder/image.jpg")
    assert result["relative_path"] == "folder/image.jpg"
    assert result["sha256"] == "8e13f6c598de092f99affe5c64d3aca48f4b4e0bea6e396bc257c40482674e3a"
    assert result["incremental_match"] is None
    assert media.read_bytes() == b"sample bytes"


def test_metadata_preview_is_read_only_and_returns_relative_name(tmp_path):
    from PIL import Image

    path = tmp_path / "photo.jpg"
    Image.new("RGB", (2, 3), color="red").save(path)
    result = preview_metadata(SimpleNamespace(name="sample", path=str(tmp_path)), "photo.jpg")
    assert result["relative_path"] == "photo.jpg"
    assert result["persisted"] is False
    assert str(tmp_path) not in str(result)
    assert path.is_file()


def test_sample_path_rejects_traversal_and_non_media(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "private.jpg"
    outside.write_bytes(b"not exposed")
    (root / "alias.jpg").symlink_to(outside)
    source = SimpleNamespace(name="sample", path=str(root))
    for relative in ("../private.jpg", "alias.jpg", "/private.jpg"):
        with pytest.raises(ValueError):
            validated_sample_path(source, relative)
    with pytest.raises(ValueError):
        validated_sample_path(source, "missing.txt")


def test_preview_discovery_rejects_invalid_limit(tmp_path):
    with pytest.raises(ValueError, match="Sample limit"):
        preview_media_entries(SimpleNamespace(name="sample", path=str(tmp_path)), limit=0)
