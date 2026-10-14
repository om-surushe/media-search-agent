from msa_indexer.io import video_selection


def test_adaptive_selection_is_novelty_gated_per_shot_and_long_shots_are_capped(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        video_selection,
        "extract_change_keyframes",
        lambda *_args, **_kwargs: {
            "frames": [
                {"timestamp": 0.5, "reason": "change", "change_percent": 12.0},
                {"timestamp": 3.0, "reason": "change", "change_percent": 18.0},
                {"timestamp": 12.0, "reason": "slow_change", "change_percent": 6.0},
                {"timestamp": 24.0, "reason": "slow_change", "change_percent": 8.0},
                {"timestamp": 38.0, "reason": "slow_change", "change_percent": 9.0},
                {"timestamp": 61.0, "reason": "change", "change_percent": 20.0},
            ]
        },
    )

    selected = video_selection.select_adaptive_frames(
        tmp_path / "clip.mp4",
        [(0.0, 10.0), (10.0, 60.0)],
        [[5.0], [30.0]],
        long_shot_threshold_seconds=30.0,
        long_shot_interval_seconds=10.0,
    )

    assert [(frame.shot_index, frame.timestamp, frame.reason) for frame in selected] == [
        (0, 0.5, "change"),
        (1, 12.0, "slow_change"),
        (1, 24.0, "slow_change"),
    ]
    assert {frame.selection_version for frame in selected} == {"adaptive-long-v1"}


def test_long_shot_coverage_is_separately_opt_in(monkeypatch, tmp_path):
    monkeypatch.setattr(
        video_selection,
        "extract_change_keyframes",
        lambda *_args, **_kwargs: {
            "frames": [
                {"timestamp": 5.0, "reason": "slow_change", "change_percent": 5.0},
                {"timestamp": 20.0, "reason": "change", "change_percent": 12.0},
            ]
        },
    )

    selected = video_selection.select_adaptive_frames(
        tmp_path / "clip.mp4",
        [(0.0, 60.0)],
        [[30.0]],
        include_long_shot_coverage=False,
    )

    assert [(frame.timestamp, frame.reason, frame.selection_version) for frame in selected] == [
        (20.0, "change", "adaptive-v1"),
    ]


def test_changed_baseline_does_not_overwrite_legacy_keyframe_slot():
    prior_row = {
        "timestamp": 0.0,
        "requested_timestamp": None,
        "selection_version": "midpoint-v1",
    }
    slot, version, timestamp = video_selection.baseline_keyframe_request(
        1, 0, 2.5, prior_row, 30.0
    )
    assert (slot, version, timestamp) == (5000, "midpoint-v1-append", 2.5)

    slot, version, timestamp = video_selection.baseline_keyframe_request(
        1, 0, 2.5,
        {**prior_row, "timestamp": 2.5},
        30.0,
    )
    assert (slot, version, timestamp) == (0, "midpoint-v1", 2.5)


def test_selector_policy_version_changes_with_selection_configuration():
    settings = {
        "include_long_shot_coverage": False,
        "sensitivity_percent": 8.0,
        "shot_detection_enabled": True,
        "shot_detection_threshold": 30.0,
        "min_shot_length_frames": 15,
        "keyframes_per_shot": 1,
        "long_shot_threshold_seconds": 30.0,
        "long_shot_interval_seconds": 10.0,
    }
    original = video_selection.adaptive_selector_policy_version(**settings)
    changed = video_selection.adaptive_selector_policy_version(
        **{**settings, "sensitivity_percent": 9.0}
    )

    assert original == video_selection.adaptive_selector_policy_version(**settings)
    assert original != changed
    assert video_selection.adaptive_keyframe_index(original, 0) != video_selection.adaptive_keyframe_index(changed, 0)


def test_baseline_policy_changes_get_separate_append_only_slots():
    assert video_selection.baseline_keyframe_slot(1, 0) == (0, "midpoint-v1")
    assert video_selection.baseline_keyframe_slot(2, 0) == (3000, "midpoint-v1-kps2")
    assert video_selection.baseline_keyframe_slot(3, 2) == (4002, "midpoint-v1-kps3")


def test_adaptive_version_slots_are_stable_and_disjoint():
    first_slot = video_selection.adaptive_keyframe_index("adaptive-v1", 0)
    next_slot = video_selection.adaptive_keyframe_index("adaptive-v1", 1)
    next_version_slot = video_selection.adaptive_keyframe_index("adaptive-long-v1", 0)

    assert first_slot > 4000
    assert next_slot == first_slot + 1
    assert next_version_slot != first_slot
    assert video_selection.adaptive_keyframe_index("adaptive-v1", 0) == first_slot
