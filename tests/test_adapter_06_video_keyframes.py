from pathlib import Path
from types import SimpleNamespace


def test_video_folder_stages_all_videos_and_returns_bounded_summaries(tmp_path, monkeypatch):
    from msa_indexer.adapters import _workbench_sandbox as sandbox

    source_root = tmp_path / "source"
    (source_root / "nested").mkdir(parents=True)
    first = source_root / "first.mp4"
    second = source_root / "nested" / "second.mov"
    photo = source_root / "photo.jpg"
    hidden = source_root / ".hidden.mp4"
    first.write_bytes(b"first video")
    second.write_bytes(b"second video")
    photo.write_bytes(b"image")
    hidden.write_bytes(b"hidden video")
    source = SimpleNamespace(name="sample", path=str(source_root))
    captured = {}
    monkeypatch.setattr(sandbox, "index_capability", lambda _config, **_kwargs: {"available": True, "reason": None})
    monkeypatch.setattr(sandbox, "_clip_checkpoint", lambda _config: (tmp_path / "clip-weights", None))
    def fake_index(
        _config, _source, _workspace, staged_root, _checkpoint, *,
        result_limit, after_index, include_object_detection, **_kwargs,
    ):
        paths = sorted(path.relative_to(staged_root).as_posix() for path in staged_root.rglob("*") if path.is_file())
        captured["paths"] = paths
        captured["bytes"] = [(staged_root / path).read_bytes() for path in paths]
        captured["include_object_detection"] = include_object_detection
        captured["force_object_detection"] = _kwargs["force_object_detection"]
        captured["stage_flags"] = (
            _config.enable_object_detection, _config.enable_video_object_detection,
            _config.enable_face_recognition,
        )
        details = [{"relative_path": path, "video_keyframes": {"keyframe_count": 2}} for path in paths]
        return len(paths), 0, {"shots": 3, "video_keyframes": 4, "embedded_keyframes": 4}, details[:result_limit]

    monkeypatch.setattr(sandbox, "_run_staged_source", fake_index)
    result = sandbox.run_video_folder(SimpleNamespace(enable_video_object_detection=False), source, result_limit=1)

    assert captured["paths"] == ["first.mp4", "nested/second.mov"]
    assert captured["bytes"] == [b"first video", b"second video"]
    assert captured["include_object_detection"] is True
    assert captured["force_object_detection"] is True
    assert captured["stage_flags"] == (True, True, True)
    assert result["scope"] == "whole_configured_source_videos"
    assert result["videos_found"] == result["videos_processed"] == 2
    assert result["complete"] is True
    assert result["video_keyframes"]["video_keyframes"] == 4
    assert result["results_truncated"] is True
    assert len(result["results"]) == 1
    assert result["persisted"] is False
    assert first.read_bytes() == b"first video"
    assert second.read_bytes() == b"second video"
    assert photo.read_bytes() == b"image"
    assert hidden.read_bytes() == b"hidden video"


def test_video_keyframe_capability_checks_shot_detector_when_enabled(monkeypatch):
    import sys
    from msa_indexer.adapters import _workbench_sandbox as sandbox
    from msa_indexer.adapters.adapter_06_video_keyframes import video_keyframe_capability

    captured = {}
    def fake_capability(config, **kwargs):
        captured["flags"] = (
            config.enable_object_detection, config.enable_video_object_detection,
            config.enable_face_recognition, config.object_detection_override,
        )
        captured["force_object_detection"] = kwargs["force_object_detection"]
        return {"available": True, "reason": None}

    monkeypatch.setattr(sandbox, "index_capability", fake_capability)
    monkeypatch.setitem(sys.modules, "msa_indexer.io.shot_detection", None)
    capability = video_keyframe_capability(SimpleNamespace(enable_video_shot_detection=True))
    assert capability == {"available": False, "reason": "PySceneDetect/OpenCV shot detector is unavailable."}
    assert captured["flags"] == (True, True, True, True)
    assert captured["force_object_detection"] is True


def test_video_keyframe_adapter_reports_shots_keyframes_cache_and_status(tmp_path, monkeypatch):
    from msa_indexer.adapters import adapter_06_video_keyframes as adapter
    from msa_indexer.db.sqlite_store import SQLiteStore

    db = SQLiteStore(tmp_path / "preview.sqlite")
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
    db.add_faces("video-id", [{
        "face_id": "face-id", "bbox": (0.1, 0.2, 0.3, 0.4), "confidence": 0.95,
        "shot_index": 0, "kf_index": 0,
    }])
    db.conn.execute(
        "INSERT INTO video_keyframe_selection_state(video_id, selector_version, status, selected_count) "
        "VALUES ('video-id', 'selector-v1', 'completed', 1)"
    )
    db.conn.commit()

    def fake_run_one(_config, _source, _path, *, expected_type, after_index, **_kwargs):
        assert expected_type == "video"
        return after_index(db, None, None, "video-id")

    monkeypatch.setattr(adapter, "run_one_file", fake_run_one)
    result = adapter.preview_video_keyframes(SimpleNamespace(), SimpleNamespace(name="fixture"), "video.mp4")
    summary = result["video_keyframes"]
    assert summary["shot_count"] == 1
    assert summary["shots"][0]["is_synthetic"] is True
    assert summary["keyframes"][0]["object_tags"] == ["car"]
    assert summary["keyframes"][0]["gps_source"] == "video_track"
    assert summary["face_bbox_format"] == "normalized_xywh_0_to_1"
    assert summary["keyframes"][0]["faces"] == [{"bbox": [0.1, 0.2, 0.3, 0.4], "confidence": 0.95}]
    assert summary["keyframes"][0]["faces_truncated"] is False
    assert summary["selection_status"][0]["status"] == "completed"
    assert summary["frame_cache"] == {"decoded_frames": 0, "cached_renditions": 0}
    db.close()


def test_video_keyframe_route_runs_all_source_videos_without_selection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from msa_apps.search_api import app as app_module
    from msa_indexer.adapters import adapter_06_video_keyframes

    source = SimpleNamespace(name="sample", path=str(tmp_path), enabled=True)
    config = SimpleNamespace(media_sources=[source], models_dir=tmp_path)
    monkeypatch.setattr(app_module, "_get_config", lambda _request: config)
    monkeypatch.setattr(app_module, "_workbench_stage_capabilities", lambda _config: {
        "video-keyframes": {"available": True, "reason": None},
    })
    monkeypatch.setattr(adapter_06_video_keyframes, "preview_video_keyframes_folder", lambda _config, _source: {
        "scope": "whole_configured_source_videos", "videos_found": 2,
        "videos_processed": 2, "results": [], "persisted": False,
    })

    response = TestClient(app_module.app).post("/adapters/video-keyframes/run?source_name=sample")
    assert response.status_code == 200
    assert response.json()["scope"] == "whole_configured_source_videos"
    assert response.json()["videos_found"] == 2
    assert response.json()["persisted"] is False
