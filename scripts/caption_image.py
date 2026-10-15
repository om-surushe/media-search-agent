#!/usr/bin/env python3
"""Offline BLIP image-captioning worker for CPU-capable Transformers runtimes."""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
import re
try:
    import resource
except ImportError:  # Windows does not expose the POSIX resource module.
    resource = None
import shutil
import sqlite3
import subprocess
import sys
import signal
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

_SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIR))
from msa_indexer.captioning import (
    MODEL_ID, MODEL_REVISION, PROMPT_VERSION, VIDEO_SCENE_PROMPT_VERSION,
)

SQLITE_HEADER = b"SQLite format 3\x00"
PROMPT = "a photograph of"
VIDEO_SCENE_PROMPT = "a video frame showing"


class CaptionProvider(Protocol):
    model_load_seconds: float
    generation_seconds: float

    def caption(self, image_path: Path, max_tokens: int, prompt: str = PROMPT) -> str: ...

    def close(self) -> None: ...


class BlipCaptionProvider:
    """CPU Transformers adapter for the pinned, local BLIP caption checkpoint."""

    def __init__(self, model_path: Path) -> None:
        import torch
        from transformers import BlipForConditionalGeneration, BlipProcessor

        self._torch = torch
        self._processor = BlipProcessor.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=False,
        )
        started = time.perf_counter()
        self._model = BlipForConditionalGeneration.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=False,
            use_safetensors=False,
        ).to("cpu").eval()
        self.model_load_seconds = time.perf_counter() - started

    def caption(self, image_path: Path, max_tokens: int, prompt: str = PROMPT) -> str:
        from PIL import Image

        with Image.open(image_path) as image:
            inputs = self._processor(image.convert("RGB"), text=prompt, return_tensors="pt")
        started = time.perf_counter()
        with self._torch.inference_mode():
            output = self._model.generate(**inputs, max_new_tokens=max_tokens, num_beams=3)
        self.generation_seconds = time.perf_counter() - started
        caption = self._processor.decode(output[0], skip_special_tokens=True).strip()
        if not caption:
            raise RuntimeError("The local model returned an empty caption")
        return caption

    def close(self) -> None:
        self._model = None
        self._processor = None
        gc.collect()


def _open_caption_store(database_path: Path, media_id: str, image_path: Path):
    """Open an existing DB only and ensure the image matches its indexed ID."""
    from msa_indexer.db.sqlite_store import SQLiteStore

    if not SQLiteStore.is_valid_media_id(media_id):
        raise ValueError("Invalid media_id; expected SHA-256 hex or canonical UUID")
    db_path = database_path.expanduser().resolve(strict=True)
    if not db_path.is_file():
        raise ValueError(f"Database path is not a file: {db_path}")
    with db_path.open("rb") as db_file:
        if db_file.read(16) != SQLITE_HEADER:
            raise ValueError(f"Not an existing SQLite database: {db_path}")

    store = SQLiteStore(db_path, create_if_missing=False)
    try:
        media = store.get_image_caption_media(media_id)
        if media is None:
            raise ValueError(f"No live indexed image for media_id: {media_id}")
        if len(media_id) == 64:
            with image_path.open("rb") as image_file:
                image_hash = hashlib.file_digest(image_file, "sha256").hexdigest()
            if image_hash != media_id.lower():
                raise ValueError("Image content does not match the SHA-256 media_id")
        elif Path(media["path"]).expanduser().resolve() != image_path:
            raise ValueError("UUID media_id requires the exact indexed image path")
        return store
    except Exception:
        store.close()
        raise


def _emit_batch_event(**event) -> None:
    print(json.dumps(event, separators=(",", ":")), flush=True)


def _inside_roots(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            pass
    return False


def _caption_all_missing(args) -> int:
    from msa_indexer.db.sqlite_store import SQLiteStore

    database = args.database.expanduser().resolve(strict=True)
    with database.open("rb") as db_file:
        if db_file.read(16) != SQLITE_HEADER:
            raise ValueError(f"Not an existing SQLite database: {database}")
    roots = [root.expanduser().resolve(strict=True) for root in args.source_root]
    if not roots or any(not root.is_dir() for root in roots):
        raise ValueError("At least one existing --source-root directory is required")

    stop_requested = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_requested.set())

    def cancellation_requested() -> bool:
        if args.stop_file is not None and args.stop_file.exists():
            stop_requested.set()
        return stop_requested.is_set()
    store = SQLiteStore(database, create_if_missing=False)
    provider: CaptionProvider | None = None
    started = time.monotonic()
    generated = failed = 0
    current_error = None
    try:
        schema_path = Path(__file__).resolve().parents[1] / "src/msa_indexer/db/schema.sql"
        store.init_schema_no_migrations(schema_path)
        candidates, total, skipped = store.get_image_caption_candidates(MODEL_ID, PROMPT_VERSION)
        _emit_batch_event(
            event="started", status="running", total=total, generated=0, skipped=skipped,
            failed=0, elapsed_seconds=0.0,
        )
        if cancellation_requested():
            status = "cancelled"
        elif not candidates:
            status = "complete"
        else:
            try:
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
                from huggingface_hub import snapshot_download

                model_path = Path(snapshot_download(
                    MODEL_ID, revision=MODEL_REVISION,
                    cache_dir=str(args.cache_dir), local_files_only=True,
                ))
                provider = BlipCaptionProvider(model_path)
            except Exception as exc:
                failed = len(candidates)
                current_error = (
                    f"Could not load {MODEL_ID} from the offline cache "
                    f"({type(exc).__name__}); verify MSA_CAPTION_CACHE_DIR."
                )
                _emit_batch_event(event="error", message=current_error)
                status = "failed"
            else:
                status = "complete"
                for position, candidate in enumerate(candidates, start=1):
                    if cancellation_requested():
                        status = "cancelled"
                        break
                    media_id = candidate["media_id"]
                    path = None
                    try:
                        if not SQLiteStore.is_valid_media_id(media_id):
                            raise ValueError("invalid indexed media ID")
                        media = store.get_image_caption_media(media_id)
                        if media is None:
                            raise ValueError("indexed image is no longer available")
                        path = Path(media["path"]).expanduser().resolve(strict=True)
                        if path != Path(candidate["path"]).expanduser().resolve(strict=True):
                            raise ValueError("indexed image path changed")
                        if not _inside_roots(path, roots) or not path.is_file():
                            raise ValueError("indexed image is outside configured media roots")
                        if len(media_id) == 64:
                            with path.open("rb") as image_file:
                                if hashlib.file_digest(image_file, "sha256").hexdigest() != media_id.lower():
                                    raise ValueError("indexed image content changed")
                        from PIL import Image
                        with Image.open(path) as image:
                            image.verify()
                        caption = provider.caption(path, args.max_tokens)
                        store.store_image_caption(
                            media_id, caption=caption, model_id=MODEL_ID,
                            prompt_version=PROMPT_VERSION,
                            generated_at_utc=datetime.now(timezone.utc).isoformat(),
                        )
                        generated += 1
                    except Exception as exc:
                        failed += 1
                        message = str(exc).replace(str(path) if path is not None else "", "<indexed image>")
                        current_error = f"{type(exc).__name__}: {message[:240]}"
                        _emit_batch_event(
                            event="image_error", media_id=media_id, message=current_error,
                        )
                    _emit_batch_event(
                        event="progress", status="running", total=total,
                        generated=generated, skipped=skipped, failed=failed,
                        current=position, current_media_id=media_id,
                        elapsed_seconds=time.monotonic() - started,
                        error=current_error,
                    )
                if failed:
                    status = "failed"
    finally:
        if provider is not None:
            provider.close()
        store.close()

    _emit_batch_event(
        event="summary", status=status, total=total, generated=generated,
        skipped=skipped, failed=failed, elapsed_seconds=time.monotonic() - started,
        **({"error": current_error} if current_error else {}),
    )
    return 1 if status == "failed" else 0


def _caption_video_scenes(args) -> int:
    from msa_indexer.db.sqlite_store import SQLiteStore

    database = args.database.expanduser().resolve(strict=True)
    with database.open("rb") as db_file:
        if db_file.read(16) != SQLITE_HEADER:
            raise ValueError(f"Not an existing SQLite database: {database}")
    roots = [root.expanduser().resolve(strict=True) for root in args.source_root]
    if not roots or any(not root.is_dir() for root in roots):
        raise ValueError("At least one existing --source-root directory is required")

    stop_requested = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_requested.set())

    def cancellation_requested() -> bool:
        if args.stop_file is not None and args.stop_file.exists():
            stop_requested.set()
        return stop_requested.is_set()

    store = SQLiteStore(database, create_if_missing=False)
    provider: CaptionProvider | None = None
    started = time.monotonic()
    generated = failed = 0
    current_error = None
    try:
        schema_path = Path(__file__).resolve().parents[1] / "src/msa_indexer/db/schema.sql"
        store.init_schema_no_migrations(schema_path)
        candidates, total, skipped = store.get_video_scene_caption_candidates(
            MODEL_ID, VIDEO_SCENE_PROMPT_VERSION, args.video_id or None,
        )
        _emit_batch_event(
            event="started", status="running", total=total, generated=0,
            skipped=skipped, failed=0, elapsed_seconds=0.0,
        )
        if cancellation_requested():
            status = "cancelled"
        elif not candidates:
            status = "complete"
        else:
            try:
                os.environ.update({
                    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                })
                from huggingface_hub import snapshot_download
                from msa_indexer.io.video import extract_frame_at_timestamp
                from msa_indexer.io.video_frames import VideoFrameCache

                frame_cache_dir = getattr(args, "frame_cache_dir", None)
                frame_cache = (
                    VideoFrameCache(store, frame_cache_dir)
                    if frame_cache_dir is not None else None
                )
                model_path = Path(snapshot_download(
                    MODEL_ID, revision=MODEL_REVISION,
                    cache_dir=str(args.cache_dir), local_files_only=True,
                ))
                provider = BlipCaptionProvider(model_path)
            except Exception as exc:
                failed = len(candidates)
                detail = str(exc).replace(str(args.cache_dir), "<caption cache>")
                current_error = (
                    f"Could not load {MODEL_ID} from the offline cache "
                    f"({type(exc).__name__}: {detail[:200]})."
                )
                _emit_batch_event(event="error", message=current_error)
                for candidate in candidates:
                    try:
                        store.store_video_scene_caption(
                            candidate["video_id"], candidate["keyframe_id"], candidate["timestamp"],
                            caption=None, model_id=MODEL_ID,
                            prompt_version=VIDEO_SCENE_PROMPT_VERSION,
                            generated_at_utc=datetime.now(timezone.utc).isoformat(), status="failed",
                        )
                    except Exception:
                        pass
                status = "failed"
            else:
                path_by_video: dict[str, Path] = {}
                hashes: dict[str, str] = {}
                status = "complete"
                for position, candidate in enumerate(candidates, start=1):
                    if cancellation_requested():
                        status = "cancelled"
                        break
                    video_id = str(candidate["video_id"])
                    path: Path | None = None
                    frame = None
                    temp_path: Path | None = None
                    try:
                        if not SQLiteStore.is_valid_media_id(video_id):
                            raise ValueError("invalid indexed video ID")
                        path = path_by_video.get(video_id)
                        if path is None:
                            media = store.conn.execute(
                                "SELECT path, mime, deleted FROM media WHERE media_id=?", (video_id,)
                            ).fetchone()
                            if media is None or media[2] or not str(media[1] or "").lower().startswith("video/"):
                                raise ValueError("indexed video is no longer available")
                            path = Path(media[0]).expanduser().resolve(strict=True)
                            if path != Path(candidate["path"]).expanduser().resolve(strict=True):
                                raise ValueError("indexed video path changed")
                            if not _inside_roots(path, roots) or not path.is_file():
                                raise ValueError("indexed video is outside configured media roots")
                            if len(video_id) == 64:
                                with path.open("rb") as video_file:
                                    hashes[video_id] = hashlib.file_digest(video_file, "sha256").hexdigest()
                                if hashes[video_id] != video_id.lower():
                                    raise ValueError("indexed video content changed")
                            path_by_video[video_id] = path
                        cached = (
                            frame_cache.get_cached_image(candidate["frame_id"])
                            if frame_cache is not None and candidate.get("frame_id") else None
                        )
                        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
                            temp_path = Path(temp_file.name)
                        if cached is not None:
                            try:
                                shutil.copyfile(cached[0], temp_path)
                            except OSError:
                                cached = None  # Cache eviction between lookup and copy; source is the fallback.
                        if cached is None:
                            frame = extract_frame_at_timestamp(path, float(candidate["timestamp"]))
                            if frame is None:
                                raise ValueError("could not decode the indexed keyframe timestamp")
                            frame.convert("RGB").save(temp_path, format="JPEG", quality=95)
                        caption = provider.caption(
                            temp_path, args.max_tokens, prompt=VIDEO_SCENE_PROMPT,
                        )
                        store.store_video_scene_caption(
                            video_id, int(candidate["keyframe_id"]), float(candidate["timestamp"]),
                            caption=caption, model_id=MODEL_ID,
                            prompt_version=VIDEO_SCENE_PROMPT_VERSION,
                            generated_at_utc=datetime.now(timezone.utc).isoformat(),
                        )
                        generated += 1
                    except Exception as exc:
                        failed += 1
                        detail = str(exc).replace(str(path), "<indexed video>") if path else str(exc)
                        current_error = f"{type(exc).__name__}: {detail[:200]}"
                        try:
                            store.store_video_scene_caption(
                                video_id, int(candidate["keyframe_id"]), float(candidate["timestamp"]),
                                caption=None, model_id=MODEL_ID,
                                prompt_version=VIDEO_SCENE_PROMPT_VERSION,
                                generated_at_utc=datetime.now(timezone.utc).isoformat(), status="failed",
                            )
                        except Exception:
                            pass
                        _emit_batch_event(event="image_error", media_id=video_id, message=current_error)
                    finally:
                        if frame is not None:
                            frame.close()
                        if temp_path is not None:
                            temp_path.unlink(missing_ok=True)
                    _emit_batch_event(
                        event="progress", status="running", total=total,
                        generated=generated, skipped=skipped, failed=failed,
                        current=position, current_media_id=video_id,
                        elapsed_seconds=time.monotonic() - started,
                        error=current_error,
                    )
                if failed:
                    status = "failed"
    finally:
        if provider is not None:
            provider.close()
        store.close()

    _emit_batch_event(
        event="summary", status=status, total=total, generated=generated,
        skipped=skipped, failed=failed, elapsed_seconds=time.monotonic() - started,
        **({"error": current_error} if current_error else {}),
    )
    return 1 if status == "failed" else 0


def _rss_bytes() -> int | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            check=True,
            capture_output=True,
            text=True,
        )
        return int(result.stdout.strip()) * 1024  # macOS ps reports KiB
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _system_free_bytes() -> int | None:
    """Read macOS free pages only; this is not the OS's full reclaimable memory."""
    try:
        output = subprocess.run(["vm_stat"], check=True, capture_output=True, text=True).stdout
        page_size = int(re.search(r"page size of (\d+) bytes", output).group(1))
        free_pages = int(re.search(r"Pages free:\s+(\d+)", output).group(1))
        return page_size * free_pages
    except (AttributeError, OSError, ValueError, subprocess.CalledProcessError):
        return None


def _mib(value: int | None) -> str:
    return "unavailable" if value is None else f"{value / (1024 * 1024):.1f} MiB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, nargs="?", help="local image file (use a disposable copy)")
    parser.add_argument("--all-missing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--video-scenes", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--video-id", action="append", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--source-root", type=Path, action="append", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--stop-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path, required=True, help="local Hugging Face cache directory")
    parser.add_argument("--frame-cache-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--database", type=Path, help="existing SQLite DB; enables caption persistence")
    parser.add_argument("--media-id", help="existing indexed image ID; requires --database")
    args = parser.parse_args()

    if args.max_tokens < 1:
        parser.error("--max-tokens must be positive")
    if args.all_missing or args.video_scenes:
        if args.all_missing and args.video_scenes:
            parser.error("--all-missing and --video-scenes are mutually exclusive")
        if args.image is not None or args.database is None or args.media_id is not None:
            parser.error("caption batch modes require --database and do not accept an image or --media-id")
        if args.video_id and not args.video_scenes:
            parser.error("--video-id is only valid with --video-scenes")
        try:
            args.cache_dir = args.cache_dir.expanduser().resolve(strict=True)
            if not args.cache_dir.is_dir():
                raise ValueError("--cache-dir must be a local directory")
            if args.frame_cache_dir is not None:
                args.frame_cache_dir = args.frame_cache_dir.expanduser().resolve()
            return _caption_video_scenes(args) if args.video_scenes else _caption_all_missing(args)
        except Exception as exc:
            _emit_batch_event(event="error", message=f"{type(exc).__name__}: {exc}")
            _emit_batch_event(
                event="summary", status="failed", total=0, generated=0,
                skipped=0, failed=0, elapsed_seconds=0.0,
                error="Caption worker could not enumerate indexed media; verify the index and source paths.",
            )
            return 1
    if args.image is None:
        parser.error("image is required unless --all-missing is used")
    if args.source_root:
        parser.error("--source-root is only valid with --all-missing")

    image_path = args.image.expanduser().resolve(strict=True)
    cache_dir = args.cache_dir.expanduser().resolve(strict=True)
    if not image_path.is_file() or not cache_dir.is_dir():
        parser.error("image must be a file and --cache-dir must be a local directory")
    if (args.database is None) != (args.media_id is None):
        parser.error("--database and --media-id must be supplied together")

    caption_store = None
    if args.database is not None:
        try:
            caption_store = _open_caption_store(args.database, args.media_id, image_path)
        except (OSError, sqlite3.Error, ValueError) as exc:
            parser.error(f"caption persistence target rejected: {exc}")

    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        from huggingface_hub import snapshot_download
        model_path = Path(snapshot_download(
            MODEL_ID, revision=MODEL_REVISION,
            cache_dir=str(cache_dir), local_files_only=True,
        ))

        from PIL import Image

        with Image.open(image_path) as image:
            image.verify()

        process_start_rss = _rss_bytes()
        system_free_before = _system_free_bytes()
    except BaseException:
        if caption_store is not None:
            caption_store.close()
        raise

    provider: CaptionProvider | None = None
    try:
        provider = BlipCaptionProvider(model_path)
        process_after_load = _rss_bytes()
        system_free_after_load = _system_free_bytes()
        caption = provider.caption(image_path, args.max_tokens)
        generated_at_utc = datetime.now(timezone.utc).isoformat()
        process_after_generation = _rss_bytes()
        system_free_after_generation = _system_free_bytes()

        print(f"Model: {MODEL_ID}")
        print(f"transformers: {importlib.metadata.version('transformers')}")
        print(f"Model load: {provider.model_load_seconds:.2f} s")
        print(f"Generation: {provider.generation_seconds:.2f} s")
        print(f"Caption: {caption}")
        print("Process RSS (start / loaded / generated): "
              f"{_mib(process_start_rss)} / {_mib(process_after_load)} / "
              f"{_mib(process_after_generation)}")
        print(f"Process peak RSS: {_mib(_peak_rss_bytes())}")
        print("System free pages (before / loaded / generated): "
              f"{_mib(system_free_before)} / {_mib(system_free_after_load)} / "
              f"{_mib(system_free_after_generation)}")
        if caption_store is not None:
            schema_path = Path(__file__).resolve().parents[1] / "src/msa_indexer/db/schema.sql"
            caption_store.init_schema_no_migrations(schema_path)
            caption_store.store_image_caption(
                args.media_id,
                caption=caption,
                model_id=MODEL_ID,
                prompt_version=PROMPT_VERSION,
                generated_at_utc=generated_at_utc,
            )
            stored = caption_store.get_image_caption(
                args.media_id, MODEL_ID, PROMPT_VERSION
            )
            if stored is None or stored["caption"] != caption:
                raise RuntimeError("Caption write could not be verified")
            print(f"Persisted: {stored}")
        return 0
    finally:
        if provider is not None:
            provider.close()
        if caption_store is not None:
            caption_store.close()


if __name__ == "__main__":
    raise SystemExit(main())
