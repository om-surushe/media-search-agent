from types import SimpleNamespace
import threading


def test_captioning_capabilities_report_preflight_errors(monkeypatch):
    from msa_indexer import captioning
    from msa_indexer.adapters.adapter_09_optional_captioning import captioning_capabilities

    def unavailable():
        raise captioning.CaptioningError("MLX runtime unavailable")

    monkeypatch.setattr(captioning, "validate_captioning_runtime", unavailable)

    capabilities = captioning_capabilities()

    assert capabilities["image_captions"] == {
        "available": False, "reason": "MLX runtime unavailable",
    }
    assert capabilities["video_scene_captions"] == capabilities["image_captions"]


def test_optional_caption_failures_do_not_fail_completed_indexing(monkeypatch):
    from msa_indexer import captioning
    from msa_indexer.adapters.adapter_09_optional_captioning import run_captioning_stages

    calls = []

    def fail_image(*_args):
        calls.append("image")
        raise captioning.CaptioningError("caption runtime unavailable")

    def fail_video(*_args):
        calls.append("video")
        raise captioning.CaptioningError("caption runtime unavailable")

    monkeypatch.setattr(captioning, "run_captioning_worker", fail_image)
    monkeypatch.setattr(captioning, "run_video_scene_captioning_worker", fail_video)
    summary = {"phase": "complete", "processed_images": 4}
    emitted = []

    run_captioning_stages(
        SimpleNamespace(image_captions_enabled=True, video_scene_captions_enabled=True),
        threading.Event(),
        summary,
        False,
        lambda **payload: emitted.append(payload),
    )

    assert calls == ["image", "video"]
    assert summary["captioning"]["status"] == "failed"
    assert summary["video_scene_captioning"]["status"] == "failed"
    assert summary["processed_images"] == 4
    assert emitted[-1]["phase"] == "complete"
