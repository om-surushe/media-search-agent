from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest


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
    monkeypatch.setattr(adapter, "WHISPER_MODEL_REVISION", hashlib.sha256(b"fake cached model").hexdigest())

    class FakeTranscriber:
        def __init__(self, isolated_models_dir, _device):
            observed["isolated_models_dir"] = str(isolated_models_dir)
            observed["isolated_checkpoint"] = (isolated_models_dir / "whisper" / "base.pt").read_bytes()

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
