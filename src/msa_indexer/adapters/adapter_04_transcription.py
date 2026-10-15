"""Stage 04: transcribe videos from one configured source without persistence."""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import tempfile
from pathlib import Path

from msa_indexer.io.scanner import ScanStats, iter_media_entries
from msa_indexer.models.asr import (
    WHISPER_MODEL_REVISION,
    WHISPER_MODEL_SIZE,
    LocalWhisperTranscriber,
)
from msa_settings.paths import resolve_for_access
from .adapter_01_discovery import VIDEO_EXT, validated_sample_path

_MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024
_MAX_SEGMENTS = 100
_MAX_TEXT_CHARS = 500
_FOLDER_RESULT_LIMIT = 10
_FOLDER_SEGMENT_LIMIT = 20


def transcription_capability(models_dir: Path) -> dict[str, bool | str | None]:
    """Check local prerequisites without loading a model or triggering a download."""
    if importlib.util.find_spec("whisper") is None:
        return {"available": False, "reason": "Python package openai-whisper is not installed."}
    checkpoint = Path(models_dir) / "whisper" / f"{WHISPER_MODEL_SIZE}.pt"
    if not checkpoint.is_file():
        return {
            "available": False,
            "reason": "Whisper base weights are not cached; first-run download is intentionally not started by the workbench.",
        }
    return {"available": True, "reason": None}


def _verify_checkpoint(checkpoint: Path) -> None:
    """Reject incomplete/corrupt weights before passing them to Whisper's downloader."""
    if not checkpoint.is_file():
        raise RuntimeError("Whisper base checkpoint is missing; no download was attempted")
    digest = hashlib.sha256()
    with checkpoint.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != WHISPER_MODEL_REVISION:
        raise RuntimeError("Whisper base checkpoint checksum mismatch; no download was attempted")


def _isolated_models_dir(models_dir: Path, workspace: Path) -> Path:
    cached_checkpoint = Path(models_dir) / "whisper" / f"{WHISPER_MODEL_SIZE}.pt"
    _verify_checkpoint(cached_checkpoint)
    isolated_models_dir = workspace / "models"
    isolated_cache = isolated_models_dir / "whisper"
    isolated_cache.mkdir(parents=True)
    isolated_checkpoint = isolated_cache / cached_checkpoint.name
    shutil.copyfile(cached_checkpoint, isolated_checkpoint)
    _verify_checkpoint(isolated_checkpoint)
    return isolated_models_dir


def _segments(result, limit: int) -> list[dict[str, float | str]]:
    return [
        {"start": segment["start"], "end": segment["end"], "text": segment["text"][:_MAX_TEXT_CHARS]}
        for segment in result.segments[:limit]
    ]


def preview_transcription(source, relative_path: str, models_dir: Path, device: str = "cpu") -> dict:
    """Transcribe one video copy; retained for direct adapter verification."""
    root, path = validated_sample_path(source, relative_path)
    if path.suffix.lower() not in VIDEO_EXT:
        raise ValueError("Transcription requires a video file")
    if path.stat().st_size > _MAX_MEDIA_BYTES:
        raise ValueError("Selected video exceeds the 2 GiB workbench limit")
    capability = transcription_capability(models_dir)
    if not capability["available"]:
        raise RuntimeError(str(capability["reason"]))

    with tempfile.TemporaryDirectory(prefix="msa-adapter-04-") as workspace:
        workspace_path = Path(workspace)
        staged_media = workspace_path / ("selected" + path.suffix.lower())
        shutil.copyfile(path, staged_media)
        isolated_models_dir = _isolated_models_dir(Path(models_dir), workspace_path)
        result = LocalWhisperTranscriber(isolated_models_dir, device).transcribe(staged_media)

    return {
        "source": source.name,
        "relative_path": path.relative_to(root).as_posix(),
        "status": result.status,
        "language": result.language,
        "segments": _segments(result, _MAX_SEGMENTS),
        "segments_truncated": len(result.segments) > _MAX_SEGMENTS,
        "error_code": result.error_code,
        "model_revision": WHISPER_MODEL_REVISION,
        "persisted": False,
    }


def preview_transcription_folder(
    source, models_dir: Path, device: str = "cpu", result_limit: int = _FOLDER_RESULT_LIMIT,
) -> dict:
    """Transcribe every video in the configured source using an isolated model copy."""
    if not 1 <= result_limit <= 25:
        raise ValueError("Result limit must be between 1 and 25")
    root = Path(resolve_for_access(str(source.path))).resolve()
    if not root.is_dir():
        raise ValueError("Configured source is not an accessible directory")
    capability = transcription_capability(models_dir)
    if not capability["available"]:
        raise RuntimeError(str(capability["reason"]))

    stats = ScanStats()
    results = []
    videos_found = videos_transcribed = videos_without_speech = failed = 0
    with tempfile.TemporaryDirectory(prefix="msa-adapter-04-") as workspace:
        workspace_path = Path(workspace)
        isolated_models_dir = _isolated_models_dir(Path(models_dir), workspace_path)
        transcriber = LocalWhisperTranscriber(isolated_models_dir, device)
        for path, stat in iter_media_entries(root, media_type="video", stats=stats):
            videos_found += 1
            relative_path = path.relative_to(root).as_posix()
            staged_media = None
            try:
                safe_root, safe_path = validated_sample_path(source, relative_path)
                relative_path = safe_path.relative_to(safe_root).as_posix()
                if stat.st_size > _MAX_MEDIA_BYTES:
                    raise ValueError("Video exceeds the workbench size limit")
                staged_media = workspace_path / f"video-{videos_found}{safe_path.suffix.lower()}"
                shutil.copyfile(safe_path, staged_media)
                result = transcriber.transcribe(staged_media)
            except RuntimeError:
                raise RuntimeError("Whisper could not load the verified local checkpoint; no download was attempted") from None
            except (OSError, ValueError):
                failed += 1
                if len(results) < result_limit:
                    results.append({"relative_path": relative_path, "status": "failed"})
                continue
            finally:
                if staged_media is not None:
                    staged_media.unlink(missing_ok=True)

            if result.status == "transcribed":
                videos_transcribed += 1
            else:
                videos_without_speech += 1
            if len(results) < result_limit:
                results.append({
                    "relative_path": relative_path,
                    "status": result.status,
                    "language": result.language,
                    "segments": _segments(result, _FOLDER_SEGMENT_LIMIT),
                    "segments_truncated": len(result.segments) > _FOLDER_SEGMENT_LIMIT,
                    "error_code": result.error_code,
                })

    return {
        "source": source.name,
        "scope": "whole_configured_source_videos",
        "videos_found": videos_found,
        "videos_transcribed": videos_transcribed,
        "videos_without_speech": videos_without_speech,
        "failed_files": failed,
        "scan_errors": stats.walk_errors,
        "complete": failed == 0 and stats.walk_errors == 0,
        "results_limit": result_limit,
        "results_truncated": videos_found > len(results),
        "results": results,
        "model_revision": WHISPER_MODEL_REVISION,
        "persisted": False,
    }
