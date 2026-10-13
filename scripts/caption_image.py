#!/usr/bin/env python3
"""Offline, one-image SmolVLM2 captioning proof of concept."""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
import re
import resource
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

MODEL_ID = "mlx-community/SmolVLM2-500M-Video-Instruct-mlx"
PROMPT_VERSION = "stage4a2-caption-v1"
SQLITE_HEADER = b"SQLite format 3\x00"
PROMPT = (
    "Write a detailed factual caption in 2–3 sentences and at least 30 words. "
    "Describe the main subject's visible appearance and posture, visible action, "
    "framing, foreground objects, and background. Use only visual evidence; do "
    "not guess identity, emotion, exact location, relationships, or causes."
)


class CaptionProvider(Protocol):
    model_load_seconds: float
    generation_seconds: float

    def caption(self, image_path: Path, max_tokens: int) -> str: ...

    def close(self) -> None: ...

    def active_metal_memory_bytes(self) -> int: ...


class SmolVLM2Provider:
    """One local MLX-VLM checkpoint; model resolution never contacts the Hub."""

    def __init__(self, model_path: Path) -> None:
        config_path = model_path / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("model_type") != "smolvlm":
            raise ValueError(f"Unexpected checkpoint architecture: {config.get('model_type')!r}")
        if "SmolVLMForConditionalGeneration" not in config.get("architectures", []):
            raise ValueError("Checkpoint does not declare the expected SmolVLM architecture")
        if not (model_path / "model.safetensors").is_file():
            raise FileNotFoundError(f"Missing local model weights under {model_path}")

        import mlx.core as mx
        from mlx_vlm import generate, load
        from mlx_vlm.prompt_utils import apply_chat_template

        self._mx = mx
        self._generate = generate
        self._apply_chat_template = apply_chat_template
        self._model = None
        self._processor = None
        mx.reset_peak_memory()
        started = time.perf_counter()
        self._model, self._processor = load(str(model_path))
        self.model_load_seconds = time.perf_counter() - started
        self.metal_peak_load_bytes = mx.get_peak_memory()
        self.metal_active_after_load_bytes = mx.get_active_memory()

    def caption(self, image_path: Path, max_tokens: int) -> str:
        self._mx.reset_peak_memory()
        started = time.perf_counter()
        images = [str(image_path)]
        prompt = self._apply_chat_template(
            self._processor, self._model.config, PROMPT, num_images=len(images)
        )
        result = self._generate(
            self._model,
            self._processor,
            prompt,
            image=images,
            max_tokens=max_tokens,
            verbose=False,
        )
        self.generation_seconds = time.perf_counter() - started
        self.metal_peak_generation_bytes = self._mx.get_peak_memory()
        self.metal_active_after_generation_bytes = self._mx.get_active_memory()
        caption = result.text.strip()
        if not caption:
            raise RuntimeError("The local model returned an empty caption")
        return caption

    def close(self) -> None:
        self._model = None
        self._processor = None
        gc.collect()
        self._mx.clear_cache()

    def active_metal_memory_bytes(self) -> int:
        return self._mx.get_active_memory()


def _open_caption_store(database_path: Path, media_id: str, image_path: Path):
    """Open an existing DB only and ensure the image matches its indexed ID."""
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
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


def _peak_rss_bytes() -> int:
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
    parser.add_argument("image", type=Path, help="local image file (use a disposable copy)")
    parser.add_argument("--cache-dir", type=Path, required=True, help="local Hugging Face cache directory")
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--database", type=Path, help="existing SQLite DB; enables caption persistence")
    parser.add_argument("--media-id", help="existing indexed image ID; requires --database")
    args = parser.parse_args()

    image_path = args.image.expanduser().resolve(strict=True)
    cache_dir = args.cache_dir.expanduser().resolve(strict=True)
    if not image_path.is_file() or not cache_dir.is_dir():
        parser.error("image must be a file and --cache-dir must be a local directory")
    if args.max_tokens < 1:
        parser.error("--max-tokens must be positive")
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
            MODEL_ID, cache_dir=str(cache_dir), local_files_only=True
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
        provider = SmolVLM2Provider(model_path)
        process_after_load = _rss_bytes()
        system_free_after_load = _system_free_bytes()
        caption = provider.caption(image_path, args.max_tokens)
        generated_at_utc = datetime.now(timezone.utc).isoformat()
        process_after_generation = _rss_bytes()
        system_free_after_generation = _system_free_bytes()

        print(f"Model: {MODEL_ID}")
        print(f"mlx-vlm: {importlib.metadata.version('mlx-vlm')}")
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
        print("Metal active (loaded / generated): "
              f"{_mib(provider.metal_active_after_load_bytes)} / "
              f"{_mib(provider.metal_active_after_generation_bytes)}")
        print("Metal peak (load / generation): "
              f"{_mib(provider.metal_peak_load_bytes)} / "
              f"{_mib(provider.metal_peak_generation_bytes)}")
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
            print(f"Metal active after release: {_mib(provider.active_metal_memory_bytes())}")
        if caption_store is not None:
            caption_store.close()


if __name__ == "__main__":
    raise SystemExit(main())
