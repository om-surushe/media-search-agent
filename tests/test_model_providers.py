from pathlib import Path

from msa_indexer.models.providers import (
    OpenClipAdapter,
    WhisperAdapter,
    default_model_adapters,
)


def test_openclip_adapter_forwards_configuration():
    calls = []
    expected = object()

    def constructor(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    cache_dir = Path("/models")
    result = OpenClipAdapter(constructor).create(
        "ViT-B-32", "laion2b", "cuda:0", cache_dir
    )

    assert result is expected
    assert calls == [(('ViT-B-32', 'laion2b', 'cuda:0'), {"cache_dir": cache_dir})]


def test_whisper_adapter_forwards_local_model_configuration():
    calls = []
    expected = object()

    def constructor(*args):
        calls.append(args)
        return expected

    models_dir = Path("/models")
    result = WhisperAdapter(constructor).create(models_dir, "cpu")

    assert result is expected
    assert calls == [(models_dir, "cpu")]


def test_default_bundle_composes_supplied_pipeline_constructors():
    calls = []

    def clip_constructor(*args, **kwargs):
        calls.append(("clip", args, kwargs))
        return object()

    def whisper_constructor(*args):
        calls.append(("whisper", args))
        return object()

    adapters = default_model_adapters(clip_constructor, whisper_constructor)
    adapters.clip.create("model", "weights", "cpu", None)
    adapters.whisper.create(Path("/models"), "cpu")

    assert isinstance(adapters.clip, OpenClipAdapter)
    assert isinstance(adapters.whisper, WhisperAdapter)
    assert calls == [
        ("clip", ("model", "weights", "cpu"), {"cache_dir": None}),
        ("whisper", (Path("/models"), "cpu")),
    ]
