"""Versioned keyframe timestamp policies for video indexing."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .video import extract_change_keyframes

MIDPOINT_SELECTOR_VERSION = "midpoint-v1"
ADAPTIVE_SELECTOR_VERSION = "adaptive-v1"
LONG_SHOT_SELECTOR_VERSION = "adaptive-long-v1"
# ponytail: append-only selector versions preserve old search results but can grow;
# add pruning only alongside an explicit rollback/history workflow.
_BASELINE_KEYFRAME_INDEX_BASE = {1: 0, 2: 3000, 3: 4000}
_BASELINE_REBUILD_INDEX_BASE = {1: 5000, 2: 6000, 3: 7000}


@dataclass(frozen=True)
class SelectedVideoFrame:
    shot_index: int
    timestamp: float
    reason: str
    change_percent: float
    selection_version: str


def baseline_keyframe_slot(keyframes_per_shot: int, candidate_index: int) -> tuple[int, str]:
    """Keep the historic one-midpoint slot; store changed policies additively."""
    count = min(max(int(keyframes_per_shot), 1), 3)
    base = _BASELINE_KEYFRAME_INDEX_BASE[count]
    version = MIDPOINT_SELECTOR_VERSION if count == 1 else f"midpoint-v1-kps{count}"
    return base + candidate_index, version


def adaptive_selector_policy_version(
    *,
    include_long_shot_coverage: bool,
    sensitivity_percent: float,
    shot_detection_enabled: bool,
    shot_detection_threshold: float,
    min_shot_length_frames: int,
    keyframes_per_shot: int,
    long_shot_threshold_seconds: float,
    long_shot_interval_seconds: float,
) -> str:
    algorithm = LONG_SHOT_SELECTOR_VERSION if include_long_shot_coverage else ADAPTIVE_SELECTOR_VERSION
    settings = {
        "algorithm": algorithm,
        "sensitivity_percent": sensitivity_percent,
        "shot_detection_enabled": shot_detection_enabled,
        "shot_detection_threshold": shot_detection_threshold,
        "min_shot_length_frames": min_shot_length_frames,
        "keyframes_per_shot": keyframes_per_shot,
        "long_shot_threshold_seconds": long_shot_threshold_seconds,
        "long_shot_interval_seconds": long_shot_interval_seconds,
    }
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    return f"{algorithm}:{digest}"


def baseline_keyframe_request(
    keyframes_per_shot: int,
    candidate_index: int,
    requested_timestamp: float,
    existing_row: Mapping[str, Any] | None,
    fps: float,
) -> tuple[int, str, float]:
    """Keep a legacy row when it matches; otherwise append the changed policy."""
    slot, version = baseline_keyframe_slot(keyframes_per_shot, candidate_index)
    if existing_row is None:
        return slot, version, requested_timestamp
    prior_request = existing_row.get("requested_timestamp")
    prior_time = float(prior_request if prior_request is not None else existing_row["timestamp"])
    tolerance = max(0.001, 0.5 / max(float(fps), 1.0))
    same_policy = existing_row.get("selection_version") == version
    if same_policy and abs(prior_time - requested_timestamp) <= tolerance:
        # Reuse legacy time as the request until the row has PTS-backed provenance.
        return slot, version, prior_time
    count = min(max(int(keyframes_per_shot), 1), 3)
    append_slot = _BASELINE_REBUILD_INDEX_BASE[count] + candidate_index
    return append_slot, f"{version}-append", requested_timestamp


def adaptive_keyframe_index(selector_version: str, candidate_index: int) -> int:
    """Reserve deterministic, disjoint natural-key slots for each selector version."""
    if not selector_version.startswith((ADAPTIVE_SELECTOR_VERSION, LONG_SHOT_SELECTOR_VERSION)):
        raise ValueError("unsupported selector version")
    if not 0 <= candidate_index < 1000:
        raise ValueError("unsupported selector candidate index")
    base = 10_000 + int(hashlib.sha256(selector_version.encode()).hexdigest()[:15], 16)
    return base + candidate_index


def select_adaptive_frames(
    video_path: Path,
    shots: list[tuple[float, float]],
    baseline_timestamps: list[list[float]],
    *,
    sensitivity_percent: float = 8.0,
    min_gap_seconds: float = 1.0,
    long_shot_threshold_seconds: float = 30.0,
    long_shot_interval_seconds: float = 10.0,
    max_change_frames_per_shot: int = 1,
    max_long_shot_frames: int = 2,
    include_long_shot_coverage: bool = True,
    selection_version: str | None = None,
) -> list[SelectedVideoFrame]:
    """Add novel motion/change frames without replacing midpoint keyframes.

    `change` candidates are capped per shot. `slow_change` candidates are only
    considered for long shots and are already gated by visual novelty in the
    shared preview sampler. Existing midpoint/start/end timestamps remain the
    canonical fallback and are excluded from the added set.
    """
    if not shots:
        return []
    selector_version = selection_version or (
        LONG_SHOT_SELECTOR_VERSION if include_long_shot_coverage else ADAPTIVE_SELECTOR_VERSION
    )
    if (
        min_gap_seconds <= 0
        or long_shot_interval_seconds < min_gap_seconds
        or long_shot_threshold_seconds < 0
        or not 0 < sensitivity_percent <= 100
    ):
        raise ValueError("invalid adaptive keyframe selection settings")
    if max_change_frames_per_shot < 0 or max_long_shot_frames < 0:
        raise ValueError("adaptive keyframe limits must be non-negative")

    max_candidates = min(2000, max(32, len(shots) * (max_change_frames_per_shot + max_long_shot_frames + 2) * 8))
    scan = extract_change_keyframes(
        video_path,
        sensitivity_percent=sensitivity_percent,
        min_interval_seconds=min_gap_seconds,
        max_interval_seconds=long_shot_interval_seconds,
        max_keyframes=max_candidates,
        include_images=False,
    )
    shot_starts = [start for start, _end in shots]
    added_per_shot = [0] * len(shots)
    long_added_per_shot = [0] * len(shots)
    selected: list[SelectedVideoFrame] = []

    for candidate in scan["frames"]:
        timestamp = float(candidate["timestamp"])
        shot_index = bisect_right(shot_starts, timestamp) - 1
        if shot_index < 0 or shot_index >= len(shots):
            continue
        start, end = shots[shot_index]
        if timestamp > end:
            continue
        baseline = baseline_timestamps[shot_index] if shot_index < len(baseline_timestamps) else []
        if any(abs(timestamp - base) < min_gap_seconds for base in baseline):
            continue

        reason = str(candidate["reason"])
        if reason == "change" and added_per_shot[shot_index] < max_change_frames_per_shot:
            added_per_shot[shot_index] += 1
        elif (
            include_long_shot_coverage
            and reason == "slow_change"
            and end - start >= long_shot_threshold_seconds
            and long_added_per_shot[shot_index] < max_long_shot_frames
        ):
            long_added_per_shot[shot_index] += 1
        else:
            continue
        selected.append(SelectedVideoFrame(
            shot_index=shot_index,
            timestamp=timestamp,
            reason=reason,
            change_percent=float(candidate.get("change_percent", 0.0)),
            selection_version=selector_version,
        ))

    return selected
