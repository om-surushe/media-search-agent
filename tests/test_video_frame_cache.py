from __future__ import annotations

from fractions import Fraction
import hashlib
from pathlib import Path
import threading

import av
import numpy as np
from PIL import Image
import pytest

from msa_indexer.io.video_frames import (
    FrameRequest,
    VideoFrameCache,
    VideoFrameExtractionCancelled,
    _apply_rotation,
    make_frame_id,
)


def _write_vfr_video(path: Path) -> None:
    with av.open(str(path), mode="w", format="matroska") as output:
        stream = output.add_stream("mpeg4", rate=30)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        for index, pts in enumerate((0, 100, 350, 450)):
            pixels = np.full((48, 64, 3), index * 50, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = pts
            frame.time_base = Fraction(1, 1000)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)


def _add_video(store, path: Path) -> str:
    video_id = hashlib.sha256(path.read_bytes()).hexdigest()
    store.conn.execute(
        "INSERT INTO media(media_id, path, mime, size_bytes) VALUES (?, ?, 'video/x-matroska', ?)",
        (video_id, str(path), path.stat().st_size),
    )
    store.commit()
    return video_id


def test_identity_uses_source_pts_not_shot_or_path_and_tracks_source_revision():
    frame_id = make_frame_id("a" * 64, 0, 350, 1, 1000, None)

    assert frame_id == make_frame_id("a" * 64, 0, 350, 1, 1000, None)
    assert frame_id != make_frame_id("b" * 64, 0, 350, 1, 1000, None)
    assert frame_id != make_frame_id("a" * 64, 0, 450, 1, 1000, None)
    assert make_frame_id("a" * 64, 0, None, None, None, 12) != make_frame_id(
        "a" * 64, 0, None, None, None, 13
    )
    with pytest.raises(ValueError, match="ordinal"):
        make_frame_id("a" * 64, 0, None, None, None, None)


def test_batched_extraction_records_vfr_pts_and_reuses_the_same_rendition(
    isolated_db, tmp_path, monkeypatch
):
    source = tmp_path / "variable.mkv"
    _write_vfr_video(source)
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    video_id = _add_video(isolated_db, source)
    cache = VideoFrameCache(isolated_db, tmp_path / "cache", budget_mb=1)
    requests = [FrameRequest(0, 0, 0.2), FrameRequest(1, 0, 0.38)]

    extracted = list(cache.extract_batch(video_id, source, requests))

    assert [item.request for item in extracted] == requests
    assert all(item.error is None and item.reference is not None for item in extracted)
    first, second = [item.reference for item in extracted]
    assert first is not None and second is not None
    assert first.pts == 100 and second.pts == 350
    assert (first.time_base_num, first.time_base_den) == (1, 1000)
    assert first.actual_timestamp == pytest.approx(0.1)
    assert second.actual_timestamp == pytest.approx(0.35)
    assert first.frame_id != second.frame_id
    assert cache.load_image(first).size == (64, 48)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_hash

    monkeypatch.setattr(av, "open", lambda *_a, **_kw: pytest.fail("cache hit reopened the video"))
    cached = next(cache.extract_batch(
        video_id, source, [FrameRequest(0, 0, 0.2, existing_frame_id=first.frame_id)]
    ))
    assert cached.reference is not None
    assert cached.reference.checksum_sha256 == first.checksum_sha256


def test_corrupt_cache_entry_is_redecoded(isolated_db, tmp_path):
    source = tmp_path / "variable.mkv"
    _write_vfr_video(source)
    video_id = _add_video(isolated_db, source)
    cache = VideoFrameCache(isolated_db, tmp_path / "cache", budget_mb=1)
    request = FrameRequest(0, 0, 0.2)
    first = next(cache.extract_batch(video_id, source, [request])).reference
    assert first is not None
    first.cache_path.write_bytes(b"corrupt rendition")

    refreshed = next(cache.extract_batch(
        video_id, source, [FrameRequest(0, 0, 0.2, existing_frame_id=first.frame_id)]
    ))

    assert refreshed.reference is not None
    assert refreshed.reference.frame_id == first.frame_id
    assert cache.load_image(refreshed.reference).size == (64, 48)
    assert refreshed.reference.checksum_sha256 != hashlib.sha256(b"corrupt rendition").hexdigest()


def test_cache_eviction_keeps_frame_identity_and_removes_only_rendition(isolated_db, tmp_path):
    source = tmp_path / "variable.mkv"
    _write_vfr_video(source)
    video_id = _add_video(isolated_db, source)
    cache = VideoFrameCache(isolated_db, tmp_path / "cache", budget_mb=1)
    cache.max_bytes = 1  # Force deterministic LRU eviction without large fixtures.
    iterator = cache.extract_batch(
        video_id, source, [FrameRequest(0, 0, 0.2), FrameRequest(1, 0, 0.38)]
    )
    first = next(iterator).reference
    assert first is not None and first.cache_path.is_file()
    cache.load_image(first)  # The caller consumes it before requesting the next frame.
    second = next(iterator).reference

    assert second is not None and second.cache_path.is_file()
    assert not first.cache_path.exists()
    assert isolated_db.get_video_frame(first.frame_id) is not None
    assert isolated_db.get_video_frame_rendition(first.frame_id, "rgb-jpeg-q90-orient-v1") is None
    iterator.close()


def test_cancellation_closes_without_creating_frame_records(isolated_db, tmp_path):
    source = tmp_path / "variable.mkv"
    _write_vfr_video(source)
    video_id = _add_video(isolated_db, source)
    stop = threading.Event()
    stop.set()
    cache = VideoFrameCache(isolated_db, tmp_path / "cache", budget_mb=1)

    with pytest.raises(VideoFrameExtractionCancelled):
        next(cache.extract_batch(video_id, source, [FrameRequest(0, 0, 0.2)], stop))
    assert isolated_db.conn.execute("SELECT COUNT(*) FROM video_frame").fetchone()[0] == 0


def test_selection_versions_append_without_replacing_midpoint_intelligence(isolated_db, tmp_path):
    source = tmp_path / "versioned.mkv"
    _write_vfr_video(source)
    video_id = _add_video(isolated_db, source)
    midpoint_id = make_frame_id(video_id, 0, 100, 1, 1000, None)
    adaptive_id = make_frame_id(video_id, 0, 350, 1, 1000, None)
    for frame_id, pts, timestamp in ((midpoint_id, 100, 0.1), (adaptive_id, 350, 0.35)):
        isolated_db.upsert_video_frame({
            "frame_id": frame_id, "video_id": video_id, "source_revision": video_id,
            "stream_index": 0, "pts": pts, "time_base_num": 1, "time_base_den": 1000,
            "frame_ordinal": None, "actual_timestamp": timestamp, "frame_id_version": 1,
        })
    isolated_db.add_keyframes(video_id, [{
        "shot_index": 0, "kf_index": 0, "timestamp": 0.1,
        "requested_timestamp": 0.2, "frame_id": midpoint_id,
        "shot_start": 0.0, "shot_end": 1.0,
    }])
    isolated_db.set_video_keyframe_selection_status(video_id, "adaptive-v1", "in_progress")
    isolated_db.add_keyframes(video_id, [{
        "shot_index": 0, "kf_index": 1000, "timestamp": 0.35,
        "requested_timestamp": 0.38, "frame_id": adaptive_id,
        "selection_version": "adaptive-v1", "shot_start": 0.0, "shot_end": 1.0,
    }])
    isolated_db.set_video_keyframe_selection_status(
        video_id, "adaptive-v1", "completed", selected_count=1
    )

    rows = isolated_db.conn.execute(
        "SELECT kf_index, timestamp, requested_timestamp, selection_version, frame_id "
        "FROM video_keyframes WHERE video_id=? ORDER BY kf_index", (video_id,)
    ).fetchall()

    assert rows == [
        (0, 0.1, 0.2, "midpoint-v1", midpoint_id),
        (1000, 0.35, 0.38, "adaptive-v1", adaptive_id),
    ]
    assert isolated_db.get_video_keyframe_selection_status(video_id, "adaptive-v1")["status"] == "completed"


def test_portrait_rotation_is_normalized_consistently():
    image = Image.new("RGB", (4, 2), "white")

    rotated = _apply_rotation(image, 90)

    assert rotated.size == (2, 4)
