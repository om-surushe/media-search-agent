"""Local video-preview helpers; temporary smoke data never enters app storage."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Mapping

from loguru import logger

MAX_FRAME_CACHE_TEST_FRAMES = 32


def exercise_adaptive_selection(
    video_path: Path,
    duration: float,
    adaptive_settings: Mapping[str, bool | float | int],
    long_shot_coverage: bool,
) -> dict:
    """Compare the production midpoint and opt-in adaptive policies on an upload."""
    from msa_indexer.io.shot_detection import detect_shots
    from msa_indexer.io.video import extract_frame_at_timestamp
    from msa_indexer.io.video_frames import keyframe_timestamps_for_shot
    from msa_indexer.io.video_selection import (
        adaptive_selector_policy_version,
        select_adaptive_frames,
    )

    try:
        shots = []
        if adaptive_settings.get("shot_detection_enabled", False):
            shots = detect_shots(
                video_path,
                threshold=float(adaptive_settings.get("shot_detection_threshold", 30.0)),
                min_scene_len=int(adaptive_settings.get("min_shot_length_frames", 15)),
            )
        if not shots and duration > 0:
            shots = [(0.0, duration)]
        shot_detection_enabled = bool(adaptive_settings.get("shot_detection_enabled", False))
        shot_detection_threshold = float(adaptive_settings.get("shot_detection_threshold", 30.0))
        min_shot_length_frames = int(adaptive_settings.get("min_shot_length_frames", 15))
        keyframes_per_shot = int(adaptive_settings.get("keyframes_per_shot", 1))
        sensitivity_percent = float(adaptive_settings.get("adaptive_keyframe_sensitivity_percent", 8.0))
        long_shot_threshold = float(adaptive_settings.get("long_shot_min_duration_seconds", 30.0))
        long_shot_interval = float(adaptive_settings.get("long_shot_interval_seconds", 10.0))
        baseline_timestamps = [
            keyframe_timestamps_for_shot(shot, keyframes_per_shot) for shot in shots
        ]
        selector_version = adaptive_selector_policy_version(
            include_long_shot_coverage=long_shot_coverage,
            sensitivity_percent=sensitivity_percent,
            shot_detection_enabled=shot_detection_enabled,
            shot_detection_threshold=shot_detection_threshold,
            min_shot_length_frames=min_shot_length_frames,
            keyframes_per_shot=keyframes_per_shot,
            long_shot_threshold_seconds=long_shot_threshold,
            long_shot_interval_seconds=long_shot_interval,
        )
        selected = select_adaptive_frames(
            video_path,
            shots,
            baseline_timestamps,
            sensitivity_percent=sensitivity_percent,
            long_shot_threshold_seconds=long_shot_threshold,
            long_shot_interval_seconds=long_shot_interval,
            include_long_shot_coverage=long_shot_coverage,
            selection_version=selector_version,
        )
        preview_frames = []
        for frame in selected[:10]:
            image = extract_frame_at_timestamp(video_path, frame.timestamp)
            image_data_url = None
            if image is not None:
                image.thumbnail((256, 256))
                buffer = BytesIO()
                image.convert("RGB").save(buffer, format="JPEG", quality=70)
                image_data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
            preview_frames.append({
                "shot_index": frame.shot_index,
                "timestamp": frame.timestamp,
                "reason": frame.reason,
                "change_percent": frame.change_percent,
                "selection_version": frame.selection_version,
                "image_data_url": image_data_url,
            })
        return {
            "shots_detected": len(shots),
            "midpoint_frames": sum(map(len, baseline_timestamps)),
            "adaptive_frames": len(selected),
            "long_shot_coverage_enabled": long_shot_coverage,
            "frames": preview_frames,
        }
    except Exception as exc:
        logger.warning("adaptive keyframe preview check failed: {}", type(exc).__name__)
        return {
            "shots_detected": 0,
            "midpoint_frames": 0,
            "adaptive_frames": 0,
            "long_shot_coverage_enabled": long_shot_coverage,
            "frames": [],
            "error": f"Adaptive selection check failed ({type(exc).__name__}).",
        }


def exercise_shared_frame_cache(video_path: Path, temp_dir: Path, frames: list[dict]) -> dict:
    """Run two passes through the production frame cache using disposable SQLite state."""
    from msa_indexer.db.sqlite_store import SQLiteStore
    from msa_indexer.io.video_frames import FrameRequest, VideoFrameCache

    store = None
    try:
        store = SQLiteStore(temp_dir / "frame-cache-test.sqlite3")
        schema = Path(__file__).resolve().parents[2] / "msa_indexer" / "db" / "schema.sql"
        store.init_schema_no_migrations(schema)
        with video_path.open("rb") as source_file:
            video_id = hashlib.file_digest(source_file, "sha256").hexdigest()
        store.upsert_media({
            "media_id": video_id,
            "path": str(video_path),
            "source_name": "keyframe-preview-test",
            "rel_path": video_path.name,
            "size_bytes": video_path.stat().st_size,
            "mime": "video/preview",
        })
        selected = frames[:MAX_FRAME_CACHE_TEST_FRAMES]
        requests = [
            FrameRequest(0, index, float(frame["timestamp"]))
            for index, frame in enumerate(selected)
        ]
        cache = VideoFrameCache(store, temp_dir / "frame-cache", budget_mb=256)
        first_pass = list(cache.extract_batch(video_id, video_path, requests))
        successful = [
            (index, item) for index, item in enumerate(first_pass) if item.reference is not None
        ]
        second_pass = list(cache.extract_batch(
            video_id,
            video_path,
            [
                FrameRequest(
                    item.request.shot_index,
                    item.request.keyframe_index,
                    item.request.requested_timestamp,
                    existing_frame_id=item.reference.frame_id,
                )
                for _index, item in successful
            ],
        ))
        reuse_by_index = {
            index: second.reference is not None
            and second.reference.frame_id == original.reference.frame_id
            for (index, original), second in zip(successful, second_pass)
        }
        cache_frames = []
        for index, item in enumerate(first_pass):
            reference = item.reference
            reused = reuse_by_index.get(index, False)
            cache_frames.append({
                "requested_timestamp": item.request.requested_timestamp,
                "actual_timestamp": reference.actual_timestamp if reference else None,
                "frame_id": reference.frame_id if reference else None,
                "checksum_sha256": reference.checksum_sha256 if reference else None,
                "reused": reused,
                "error": item.error or (
                    None if reused else "CacheReuseMiss" if reference else None
                ),
            })
        return {
            "selected_frames": len(frames),
            "tested_frames": len(selected),
            "cache_reuse_hits": sum(reuse_by_index.values()),
            "frames": cache_frames,
        }
    except Exception as exc:
        logger.warning("keyframe preview cache check failed: {}", type(exc).__name__)
        return {
            "selected_frames": len(frames),
            "tested_frames": min(len(frames), MAX_FRAME_CACHE_TEST_FRAMES),
            "cache_reuse_hits": 0,
            "frames": [],
            "error": f"Frame-cache check failed ({type(exc).__name__}).",
        }
    finally:
        if store is not None:
            store.close()
