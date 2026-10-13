import argparse
from types import SimpleNamespace


def test_cli_detection_override_is_optional_boolean():
    from msa_cli.cmd_index import register

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers)

    assert parser.parse_args(["index", "run"]).object_detection_enabled is None
    assert parser.parse_args(["index", "run", "--object-detection"]).object_detection_enabled is True
    assert parser.parse_args(["index", "run", "--no-object-detection"]).object_detection_enabled is False


def test_per_run_override_controls_image_and_video_detection_together():
    from msa_indexer.pipeline import _object_detection_enabled, _video_object_detection_enabled

    config = SimpleNamespace(
        enable_object_detection=False,
        enable_video_object_detection=False,
        device="cpu",
        object_detection_override=True,
    )
    assert _object_detection_enabled(config) is True
    assert _video_object_detection_enabled(config) is True

    config.object_detection_override = False
    config.enable_object_detection = True
    config.enable_video_object_detection = True
    assert _object_detection_enabled(config) is False
    assert _video_object_detection_enabled(config) is False
