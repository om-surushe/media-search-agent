from fractions import Fraction
import hashlib
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
import av
import numpy as np


def _write_cache_test_video(path: Path) -> None:
    with av.open(str(path), mode="w", format="mp4") as output:
        stream = output.add_stream("mpeg4", rate=5)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 5)
        stream.codec_context.time_base = Fraction(1, 5)
        for index in range(10):
            value = 0 if index < 5 else 255
            pixels = np.full((48, 64, 3), value, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, 5)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)


def _patch_test_client_address(monkeypatch, app_module, host):
    real_ip_address = app_module.ipaddress.ip_address
    monkeypatch.setattr(
        app_module,
        "ipaddress",
        SimpleNamespace(ip_address=lambda value: real_ip_address(host)),
    )


def test_preview_upload_is_temporary_and_local_only(mock_config, monkeypatch):
    from msa_apps.search_api import app as app_module

    _patch_test_client_address(monkeypatch, app_module, "127.0.0.1")
    captured = {}

    def analyze(path, *_):
        captured["path"] = path
        assert path.read_bytes() == b"video-bytes"
        return {
            "duration": 1.0,
            "frames_scanned": 30,
            "change_frames": 1,
            "slow_change_frames": 0,
            "omitted_frames": 0,
            "sensitivity_percent": 8.0,
            "frames": [],
        }

    monkeypatch.setattr(app_module, "_analyze_keyframe_preview", analyze)
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)
    client = TestClient(app)

    response = client.post(
        "/video-keyframes/preview?extension=.mp4",
        content=b"video-bytes",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 200
    assert response.json()["frames_scanned"] == 30
    assert not captured["path"].exists()
    assert not (Path(mock_config.sqlite_path).parent / ".keyframe-preview").exists()


def test_actual_decoded_time_reaches_search_payload_and_seek_api(mock_config, monkeypatch, tmp_path):
    from msa_indexer.db.sqlite_store import SQLiteStore
    from msa_indexer.io.video_frames import FrameRequest, VideoFrameCache
    from msa_indexer.db.qdrant_export import build_video_payload
    from msa_apps.search_api import app as app_module

    source = tmp_path / "seek-test.mp4"
    _write_cache_test_video(source)
    video_id = hashlib.sha256(source.read_bytes()).hexdigest()
    store = SQLiteStore(Path(mock_config.sqlite_path))
    schema = Path(__file__).resolve().parents[1] / "src" / "msa_indexer" / "db" / "schema.sql"
    store.init_schema_no_migrations(schema)
    store.upsert_media({
        "media_id": video_id, "path": str(source), "source_name": "seek-test",
        "rel_path": source.name, "size_bytes": source.stat().st_size,
        "mime": "video/mp4", "duration": 2.0,
    })
    cache = VideoFrameCache(store, tmp_path / "cache", budget_mb=1)
    extracted = next(cache.extract_batch(
        video_id, source, [FrameRequest(0, 0, 0.33)]
    ))
    assert extracted.reference is not None
    actual_time = extracted.reference.actual_timestamp
    store.add_shots(video_id, [(0.0, 2.0)])
    store.add_keyframes(video_id, [{
        "shot_index": 0, "kf_index": 0, "timestamp": actual_time,
        "requested_timestamp": 0.33, "frame_id": extracted.reference.frame_id,
        "shot_start": 0.0, "shot_end": 2.0,
    }])
    exported_row = next(store.iter_video_keyframes())
    assert exported_row["timestamp"] == actual_time
    assert exported_row["frame_id"] == extracted.reference.frame_id
    assert build_video_payload(exported_row)["timestamp"] == actual_time
    store.close()

    _patch_test_client_address(monkeypatch, app_module, "127.0.0.1")
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)
    response = TestClient(app).get(f"/videos/{video_id}/shots")

    assert response.status_code == 200
    assert response.json()["shots"][0]["keyframes"][0]["timestamp"] == actual_time


def test_preview_page_cache_check_uses_disposable_database_and_reuses_frames(
    mock_config, monkeypatch, tmp_path
):
    from msa_apps.search_api import app as app_module

    _patch_test_client_address(monkeypatch, app_module, "127.0.0.1")
    source = tmp_path / "cache-test.mp4"
    _write_cache_test_video(source)
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)

    response = TestClient(app).post(
        "/video-keyframes/preview?extension=.mp4&test_shared_frame_cache=true",
        content=source.read_bytes(),
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 200
    result = response.json()["frame_cache_test"]
    assert result["error"] is None
    assert result["selected_frames"] >= 1
    assert result["tested_frames"] >= 1
    assert result["cache_reuse_hits"] == result["tested_frames"]
    assert all(len(frame["frame_id"]) == 64 for frame in result["frames"])
    assert not (Path(mock_config.sqlite_path).parent / ".keyframe-preview").exists()


def test_preview_can_compare_adaptive_selector_with_long_shot_policy(mock_config, monkeypatch, tmp_path):
    from msa_apps.search_api import app as app_module

    _patch_test_client_address(monkeypatch, app_module, "127.0.0.1")
    source = tmp_path / "adaptive-test.mp4"
    _write_cache_test_video(source)
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)
    temporary_uploads = []
    analyze_preview = app_module._analyze_keyframe_preview

    def capture_upload(video_path, *args, **kwargs):
        temporary_uploads.append(Path(video_path))
        return analyze_preview(video_path, *args, **kwargs)

    monkeypatch.setattr(app_module, "_analyze_keyframe_preview", capture_upload)

    response = TestClient(app).post(
        "/video-keyframes/preview?extension=.mp4&test_adaptive_selection=true&test_long_shot_coverage=true",
        content=source.read_bytes(),
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 200
    comparison = response.json()["adaptive_selection_test"]
    assert comparison["error"] is None
    assert comparison["shots_detected"] >= 1
    assert comparison["midpoint_frames"] >= 1
    assert comparison["long_shot_coverage_enabled"] is True
    assert len(temporary_uploads) == 1 and not temporary_uploads[0].exists()
    assert not (Path(mock_config.sqlite_path).parent / ".keyframe-preview").exists()


def test_preview_upload_rejects_non_loopback_clients(mock_config, monkeypatch):
    from msa_apps.search_api import app as app_module

    _patch_test_client_address(monkeypatch, app_module, "192.0.2.1")
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)
    response = TestClient(app).post(
        "/video-keyframes/preview?extension=.mp4",
        content=b"video-bytes",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 403


def test_preview_upload_rejects_oversized_content(mock_config, monkeypatch):
    from msa_apps.search_api import app as app_module

    _patch_test_client_address(monkeypatch, app_module, "127.0.0.1")
    monkeypatch.setattr(app_module, "_MAX_KEYFRAME_PREVIEW_UPLOAD_BYTES", 3)
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)
    response = TestClient(app).post(
        "/video-keyframes/preview?extension=.mp4",
        content=b"large",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 413


def test_preview_upload_rejects_out_of_range_sensitivity(mock_config, monkeypatch):
    from msa_apps.search_api import app as app_module

    _patch_test_client_address(monkeypatch, app_module, "127.0.0.1")
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)
    response = TestClient(app).post(
        "/video-keyframes/preview?extension=.mp4&sensitivity_percent=40",
        content=b"video-bytes",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 400


def test_preview_upload_reports_invalid_video_as_unprocessable(mock_config, monkeypatch):
    from msa_apps.search_api import app as app_module

    _patch_test_client_address(monkeypatch, app_module, "127.0.0.1")
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)
    response = TestClient(app).post(
        "/video-keyframes/preview?extension=.mp4",
        content=b"not a video",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 422


def test_preview_upload_rejects_unsupported_extension(mock_config, monkeypatch):
    from msa_apps.search_api import app as app_module

    _patch_test_client_address(monkeypatch, app_module, "127.0.0.1")
    app = app_module.create_app(config_override=mock_config, reset_dependencies=True)
    response = TestClient(app).post(
        "/video-keyframes/preview?extension=.txt",
        content=b"video-bytes",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 400


def test_change_sampler_keeps_gradual_changes_and_periodic_coverage(monkeypatch):
    from msa_indexer.io import video

    class FakeCapture:
        def __init__(self, _path):
            self.values = iter([0, 10, 20, 30, 30, 30, 30, 30])
            self.count = 8

        def isOpened(self):
            return True

        def get(self, prop):
            if prop == video.cv2.CAP_PROP_FPS:
                return 4.0
            if prop == video.cv2.CAP_PROP_FRAME_COUNT:
                return self.count
            return 0.0

        def read(self):
            try:
                value = next(self.values)
            except StopIteration:
                return False, None
            return True, np.full((8, 8, 3), value, dtype=np.uint8)

        def release(self):
            pass

    monkeypatch.setattr(video.cv2, "VideoCapture", FakeCapture)

    result = video.extract_change_keyframes("unused.mp4", sensitivity_percent=8.0)

    assert [frame["reason"] for frame in result["frames"]] == ["start", "change"]
    assert [frame["timestamp"] for frame in result["frames"]] == [0.0, 0.75]
    assert result["slow_change_frames"] == 0
    assert result["frames_scanned"] == 8


def test_change_sampler_saves_gradual_novelty_but_skips_repeats(monkeypatch):
    from msa_indexer.io import video

    frames = [np.zeros((8, 8, 3), dtype=np.uint8) for _ in range(8)]
    frames[4][:2, :2] = 255

    class FakeCapture:
        def __init__(self, _path):
            self.frames = iter(frames)

        def isOpened(self):
            return True

        def get(self, prop):
            if prop == video.cv2.CAP_PROP_FPS:
                return 4.0
            if prop == video.cv2.CAP_PROP_FRAME_COUNT:
                return len(frames)
            return 0.0

        def read(self):
            try:
                return True, next(self.frames)
            except StopIteration:
                return False, None

        def release(self):
            pass

    monkeypatch.setattr(video.cv2, "VideoCapture", FakeCapture)

    result = video.extract_change_keyframes("unused.mp4", sensitivity_percent=8.0)

    assert [frame["reason"] for frame in result["frames"]] == ["start", "slow_change"]
    assert [frame["timestamp"] for frame in result["frames"]] == [0.0, 1.0]


def test_keyframe_extraction_does_not_substitute_whole_video_midpoint(monkeypatch):
    from msa_indexer.io import video

    monkeypatch.setattr(video, "extract_frame_at_timestamp", lambda *_: None)
    monkeypatch.setattr(
        video,
        "get_video_representative_frame",
        lambda *_: (_ for _ in ()).throw(AssertionError("unrelated fallback frame used")),
    )

    frames = video.extract_keyframes_from_shot("unused.mp4", (2.0, 4.0))

    assert frames == [(3.0, None)]
