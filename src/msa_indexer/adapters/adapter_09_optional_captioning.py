"""Optional captioning stage, isolated from core indexing and model adapters."""
from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

from loguru import logger

SummaryEmitter = Callable[..., None]


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    local_paths = (
        os.environ.get("MSA_CAPTION_PYTHON"),
        os.environ.get("MSA_CAPTION_CACHE_DIR"),
        str(Path.home()),
    )
    for local_path in local_paths:
        if local_path:
            message = message.replace(local_path, "<local path>")
    return message


def captioning_capabilities(
    config=None, *, include_prepare: bool = False,
) -> dict[str, dict[str, bool | str | None]]:
    """Report CPU Transformers support and the pinned BLIP checkpoint state."""
    models_dir = Path(getattr(config, "models_dir", "models")) if config is not None else None
    try:
        import subprocess
        from msa_indexer.captioning import CaptioningError, validate_captioning_runtime

        python, _cache, _worker = validate_captioning_runtime(
            models_dir=models_dir, require_model=False,
        )
        env = os.environ.copy()
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        check = subprocess.run(
            [str(python), "-c", "import torch; from transformers import BlipForConditionalGeneration, BlipProcessor"],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
        if check.returncode:
            raise RuntimeError("PyTorch and Transformers BLIP support are unavailable in the caption interpreter.")
        try:
            validate_captioning_runtime(models_dir=models_dir)
        except CaptioningError as exc:
            capability = {"available": False, "reason": _safe_error_message(exc)}
            can_prepare = True
        else:
            capability = {"available": True, "reason": None}
            can_prepare = False
    except Exception as exc:
        capability = {"available": False, "reason": _safe_error_message(exc)}
        can_prepare = False
    if include_prepare:
        capability["can_prepare"] = can_prepare
    return {
        "image_captions": dict(capability),
        "video_scene_captions": dict(capability),
    }


def captioning_stage_capability(config) -> dict[str, bool | str | None]:
    from ._workbench_sandbox import index_capability

    index = index_capability(config)
    if not index["available"]:
        return index
    return captioning_capabilities(config, include_prepare=True)["image_captions"]


def preview_captioning(config, source, relative_path: str) -> dict:
    from msa_indexer.captioning import (
        VIDEO_SCENE_PROMPT_VERSION, PROMPT_VERSION, run_captioning_worker,
        run_video_scene_captioning_worker, validate_captioning_runtime,
    )
    from ._workbench_sandbox import run_one_file

    def caption(db, isolated, workspace, media_id):
        _python, source_cache, _worker = validate_captioning_runtime(
            models_dir=Path(getattr(config, "models_dir", "models")),
        )
        from msa_indexer.captioning import MODEL_ID

        cache_root = workspace / "caption-model-cache"
        model_cache = cache_root / f"models--{MODEL_ID.replace('/', '--')}"
        shutil.copytree(source_cache / model_cache.name, model_cache)
        updates: list[dict] = []
        event = threading.Event()
        is_video = Path(relative_path).suffix.lower() in {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".flv", ".webm"}
        if is_video:
            result = run_video_scene_captioning_worker(
                isolated, event, updates.append, video_ids=[media_id],
                python_path=_python, cache_dir=cache_root,
            )
            prompt = VIDEO_SCENE_PROMPT_VERSION
        else:
            result = run_captioning_worker(
                isolated, event, updates.append, python_path=_python, cache_dir=cache_root,
            )
            prompt = PROMPT_VERSION
        return {"captioning": {
            "status": result.get("status"), "generated": result.get("generated", 0),
            "skipped": result.get("skipped", 0), "failed": result.get("failed", 0),
            "prompt_version": prompt, "persisted": False,
        }}

    return run_one_file(config, source, relative_path, after_index=caption)


def preview_captioning_folder(config, source, result_limit: int = 25) -> dict:
    """Caption every supported image and video in a disposable source preview."""
    from copy import copy
    from msa_indexer.captioning import MODEL_ID, validate_captioning_runtime
    from ._workbench_sandbox import run_source_folder

    capability = captioning_stage_capability(config)
    if not capability["available"]:
        raise RuntimeError(str(capability["reason"]))
    python, source_cache, _worker = validate_captioning_runtime(
        models_dir=Path(getattr(config, "models_dir", "models")),
    )
    model_cache_name = f"models--{MODEL_ID.replace('/', '--')}"

    def caption_source(db, isolated, workspace):
        cache_root = workspace / "caption-model-cache"
        model_cache = cache_root / model_cache_name
        shutil.copytree(source_cache / model_cache_name, model_cache)
        caption_config = copy(isolated)
        caption_config.image_captions_enabled = True
        caption_config.video_scene_captions_enabled = True
        summary: dict = {}
        run_captioning_stages(
            caption_config, threading.Event(), summary, False,
            lambda **update: summary.update(update),
            python_path=python, cache_dir=cache_root,
        )
        return {
            "captioning": summary.get("captioning", {}),
            "video_scene_captioning": summary.get("video_scene_captioning", {}),
        }

    def caption_details(db, _isolated, _workspace, media_id):
        image_count = db.conn.execute(
            "SELECT COUNT(*) FROM image_caption WHERE media_id=?", (media_id,),
        ).fetchone()[0]
        image_rows = db.conn.execute(
            "SELECT caption, model_id, prompt_version, generated_at_utc, status "
            "FROM image_caption WHERE media_id=? "
            "ORDER BY generated_at_utc DESC, model_id, prompt_version LIMIT 20", (media_id,),
        ).fetchall()
        video_count = db.conn.execute(
            "SELECT COUNT(*) FROM video_scene_caption WHERE video_id=?", (media_id,),
        ).fetchone()[0]
        video_rows = db.conn.execute(
            "SELECT timestamp, caption, model_id, prompt_version, generated_at_utc, status "
            "FROM video_scene_caption WHERE video_id=? "
            "ORDER BY timestamp, keyframe_id LIMIT 20", (media_id,),
        ).fetchall()
        return {
            "image_captions": [
                {"caption": row[0], "model_id": row[1], "prompt_version": row[2],
                 "generated_at_utc": row[3], "status": row[4]}
                for row in image_rows
            ],
            "image_captions_truncated": int(image_count) > len(image_rows),
            "video_scene_captions": [
                {"timestamp": row[0], "caption": row[1], "model_id": row[2],
                 "prompt_version": row[3], "generated_at_utc": row[4], "status": row[5]}
                for row in video_rows
            ],
            "video_scene_captions_truncated": int(video_count) > len(video_rows),
        }

    return run_source_folder(
        config, source, result_limit=result_limit,
        after_source=caption_source, after_index=caption_details,
    )


def run_captioning_stages(
    config,
    stop_event,
    complete_summary: dict,
    export_blocked: bool,
    emit_summary: SummaryEmitter,
    *,
    python_path: Path | None = None,
    cache_dir: Path | None = None,
) -> None:
    """Run requested optional caption stages; failures never invalidate core indexing."""
    image_enabled = bool(getattr(config, "image_captions_enabled", False))
    video_enabled = bool(getattr(config, "video_scene_captions_enabled", False))
    if not image_enabled and not video_enabled:
        return

    if stop_event is None:
        stop_event = threading.Event()
    phase = "export_blocked" if export_blocked else "complete"
    runtime_kwargs = {}
    if python_path is not None:
        runtime_kwargs["python_path"] = python_path
    if cache_dir is not None:
        runtime_kwargs["cache_dir"] = cache_dir

    if image_enabled:
        from msa_indexer.captioning import MODEL_ID, PROMPT_VERSION

        captioning = {
            "model_id": MODEL_ID,
            "prompt_version": PROMPT_VERSION,
            "status": "cancelled" if stop_event.is_set() else "starting",
            "total": 0,
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "elapsed_seconds": 0.0,
        }
        if not stop_event.is_set():
            def publish_captioning(update):
                captioning.update(update["captioning"])
                emit_summary(**{
                    **complete_summary,
                    **update,
                    **({"phase": "export_blocked"} if export_blocked else {}),
                })

            try:
                from msa_indexer.captioning import run_captioning_worker

                captioning.update(
                    run_captioning_worker(config, stop_event, publish_captioning, **runtime_kwargs)
                )
            except Exception as exc:
                captioning.update(status="failed", error=_safe_error_message(exc))
                logger.warning(
                    "Optional image caption stage failed; indexing will continue: {}",
                    type(exc).__name__,
                )
        complete_summary["captioning"] = captioning
        emit_summary(**{**complete_summary, "phase": phase})

    if video_enabled:
        from msa_indexer.captioning import MODEL_ID, VIDEO_SCENE_PROMPT_VERSION

        scene_captioning = {
            "model_id": MODEL_ID,
            "prompt_version": VIDEO_SCENE_PROMPT_VERSION,
            "status": "cancelled" if stop_event.is_set() else "starting",
            "total": 0,
            "generated": 0,
            "skipped": 0,
            "failed": 0,
            "elapsed_seconds": 0.0,
        }
        if not stop_event.is_set():
            def publish_video_scenes(update):
                scene_captioning.update(update["video_scene_captioning"])
                emit_summary(**{
                    **complete_summary,
                    **update,
                    **({"phase": "export_blocked"} if export_blocked else {}),
                })

            try:
                from msa_indexer.captioning import run_video_scene_captioning_worker

                scene_captioning.update(
                    run_video_scene_captioning_worker(
                        config, stop_event, publish_video_scenes, **runtime_kwargs,
                    )
                )
            except Exception as exc:
                scene_captioning.update(status="failed", error=_safe_error_message(exc))
                logger.warning(
                    "Optional video scene caption stage failed; indexing will continue: {}",
                    type(exc).__name__,
                )
        complete_summary["video_scene_captioning"] = scene_captioning
        emit_summary(**{**complete_summary, "phase": phase})
