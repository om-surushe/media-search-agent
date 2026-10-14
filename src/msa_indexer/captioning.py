"""Offline image-caption runtime integration; model inference stays in its own process."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

MODEL_ID = "mlx-community/SmolVLM2-500M-Video-Instruct-mlx"
PROMPT_VERSION = "stage4a2-caption-v1"
VIDEO_SCENE_PROMPT_VERSION = "stage4b-video-scene-v1"


class CaptioningError(ValueError):
    pass


def validate_captioning_runtime(environ: dict[str, str] | None = None) -> tuple[Path, Path, Path]:
    """Check the isolated interpreter, worker, and cached checkpoint without loading MLX."""
    env = os.environ if environ is None else environ
    python_value = env.get("MSA_CAPTION_PYTHON")
    cache_value = env.get("MSA_CAPTION_CACHE_DIR")
    if not python_value:
        raise CaptioningError("AI Image Captions needs MSA_CAPTION_PYTHON set to the isolated MLX Python interpreter.")
    if not cache_value:
        raise CaptioningError("AI Image Captions needs MSA_CAPTION_CACHE_DIR set to the existing local model cache.")

    # Keep the venv executable path (resolve() follows its symlink and can discard site-packages).
    python = Path(os.path.abspath(Path(python_value).expanduser()))
    cache = Path(cache_value).expanduser().resolve()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise CaptioningError(f"Captioning interpreter is not executable: {python}")
    if not cache.is_dir():
        raise CaptioningError(f"Local caption model cache is not a directory: {cache}")

    snapshots = cache / f"models--{MODEL_ID.replace('/', '--')}" / "snapshots"
    if not snapshots.is_dir() or not any(path.is_dir() for path in snapshots.iterdir()):
        raise CaptioningError(
            f"{MODEL_ID} is not present in the local cache at {cache}; captioning is offline and will not download it."
        )

    project_root = Path(__file__).resolve().parents[2]
    worker = project_root / "scripts" / "caption_image.py"
    if not worker.is_file():
        raise CaptioningError(f"Captioning worker script is missing: {worker}")
    return python, cache, worker


def _source_roots(config) -> list[Path]:
    from msa_settings.paths import resolve_for_access

    roots: list[Path] = []
    override = getattr(config, "media_source_override", None)
    if override:
        roots.append(Path(resolve_for_access(str(override))).expanduser().resolve(strict=True))
    for source in getattr(config, "media_sources", []):
        if not getattr(source, "enabled", True):
            continue
        raw_path = getattr(source, "path", None)
        if raw_path:
            roots.append(Path(resolve_for_access(str(raw_path))).expanduser().resolve(strict=True))
    unique = list(dict.fromkeys(roots))
    if not unique or any(not root.is_dir() for root in unique):
        raise CaptioningError("AI Image Captions needs at least one accessible configured media source directory.")
    return unique


def run_captioning_worker(
    config, stop_event, on_progress: Callable[[dict], None],
) -> dict:
    return _run_captioning_worker(config, stop_event, on_progress)


def run_video_scene_captioning_worker(
    config, stop_event, on_progress: Callable[[dict], None],
    video_ids: list[str] | None = None,
) -> dict:
    return _run_captioning_worker(
        config, stop_event, on_progress, video_scenes=True, video_ids=video_ids,
    )


def _run_captioning_worker(
    config, stop_event, on_progress: Callable[[dict], None], *,
    video_scenes: bool = False, video_ids: list[str] | None = None,
) -> dict:
    """Run the isolated offline worker and forward compact progress events."""
    python, cache, worker = validate_captioning_runtime()
    database = Path(config.sqlite_path).expanduser().resolve(strict=True)
    if not database.is_file():
        raise CaptioningError(f"Captioning requires an existing SQLite index: {database}")
    roots = _source_roots(config)
    command = [
        str(python), str(worker), "--video-scenes" if video_scenes else "--all-missing",
        "--database", str(database), "--cache-dir", str(cache),
    ]
    if video_ids is not None:
        for video_id in video_ids:
            command.extend(("--video-id", video_id))
    frame_cache_dir = getattr(config, "video_frame_cache_dir", None)
    if video_scenes and frame_cache_dir is not None:
        command.extend(("--frame-cache-dir", str(frame_cache_dir)))
    for root in roots:
        command.extend(("--source-root", str(root)))
    if os.environ.get("MSA_INDEXER_STOP_FILE"):
        command.extend(("--stop-file", os.environ["MSA_INDEXER_STOP_FILE"]))

    env = os.environ.copy()
    # macOS sets this for its parent venv; it can override MSA_CAPTION_PYTHON.
    env.pop("__PYVENV_LAUNCHER__", None)
    env.update({
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONUNBUFFERED": "1",
    })
    source_dir = str(worker.parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_dir, env.get("PYTHONPATH", "")) if part
    )

    try:
        process = subprocess.Popen(
            command, cwd=str(worker.parents[1]), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except OSError as exc:
        raise CaptioningError(f"Could not start the isolated captioning worker: {exc}") from exc

    events: queue.Queue[str | None] = queue.Queue()

    def read_events() -> None:
        try:
            for line in process.stdout:
                events.put(line)
        finally:
            events.put(None)

    reader = threading.Thread(target=read_events, name="caption-worker-output", daemon=True)
    reader.start()
    progress_key = "video_scene_captioning" if video_scenes else "captioning"
    phase = "scene_captioning" if video_scenes else "captioning"
    state = {
        "model_id": MODEL_ID,
        "prompt_version": VIDEO_SCENE_PROMPT_VERSION if video_scenes else PROMPT_VERSION,
        "status": "starting", "total": 0, "generated": 0, "skipped": 0,
        "failed": 0, "elapsed_seconds": 0.0,
    }
    reader_done = False
    cancel_started: float | None = None
    error_message: str | None = None
    unexpected_output = False
    summary_received = False
    started = time.monotonic()

    def publish() -> None:
        on_progress({"phase": phase, progress_key: dict(state)})

    try:
        while not reader_done or process.poll() is None:
            try:
                line = events.get(timeout=0.25)
            except queue.Empty:
                line = ""
            if line is None:
                reader_done = True
            elif line:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    unexpected_output = True
                    continue
                kind = event.get("event")
                if kind in {"started", "progress", "summary"}:
                    for key in ("status", "total", "generated", "skipped", "failed",
                                "elapsed_seconds", "current", "current_media_id"):
                        if key in event:
                            state[key] = event[key]
                    if event.get("error"):
                        state["error"] = str(event["error"])
                    if kind == "summary":
                        summary_received = True
                        state["status"] = event.get("status", state["status"])
                    publish()
                elif kind in {"error", "image_error"}:
                    error_message = str(event.get("message") or "Caption worker failed.")
                    state["error"] = error_message
                    if kind == "error":
                        state["status"] = "failed"
                    publish()

            if stop_event.is_set():
                cancel_started = cancel_started or time.monotonic()
                if process.poll() is None and time.monotonic() - cancel_started > 120:
                    process.kill()

        return_code = process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()
        reader.join(timeout=1)

    state["elapsed_seconds"] = max(float(state.get("elapsed_seconds", 0)), time.monotonic() - started)
    if stop_event.is_set():
        state["status"] = "cancelled"
    elif return_code != 0 and state["status"] != "failed":
        state.update(status="failed", error="Caption worker exited unexpectedly; verify the isolated MLX runtime and local model cache.")
    elif return_code == 0 and not summary_received:
        detail = "Unexpected worker output." if unexpected_output else "No completion summary was returned."
        state.update(status="failed", error=f"Caption worker did not complete cleanly. {detail}")
    if error_message:
        state["error"] = error_message
    publish()
    if state["status"] == "failed":
        raise CaptioningError(state.get("error", "Image captioning failed."))
    return state
