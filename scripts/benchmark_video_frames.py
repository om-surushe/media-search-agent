#!/usr/bin/env python3
"""Compare independent timestamp seeks, grouped PyAV seeks, and one sequential pass."""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
from queue import Empty
from pathlib import Path
import tempfile
import time
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - Windows has no resource module
    resource = None


def _rss_peak_mb() -> float | None:
    if resource is None:
        return None
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / (1024 * 1024 if os.uname().sysname == "Darwin" else 1024)


def _worker(mode: str, video_path: str, timestamps: list[float], consumer_passes: int, result_queue) -> None:
    start = time.perf_counter()
    decoder_opens = 0
    frames_selected = 0
    cache_bytes = 0
    first_pass_seconds = 0.0
    reuse_pass_seconds = 0.0
    cache_reuse_hits = 0
    try:
        import cv2
        if mode == "independent-seeks":
            from msa_indexer.io import video as video_io
            real_open = cv2.VideoCapture

            def counted_open(*args, **kwargs):
                nonlocal decoder_opens
                decoder_opens += 1
                return real_open(*args, **kwargs)

            video_io.cv2.VideoCapture = counted_open
            try:
                for pass_index in range(consumer_passes):
                    pass_start = time.perf_counter()
                    frames_selected += sum(
                        video_io.extract_frame_at_timestamp(Path(video_path), timestamp) is not None
                        for timestamp in timestamps
                    )
                    pass_elapsed = time.perf_counter() - pass_start
                    if pass_index == 0:
                        first_pass_seconds = pass_elapsed
                    else:
                        reuse_pass_seconds += pass_elapsed
            finally:
                video_io.cv2.VideoCapture = real_open
        elif mode == "sequential":
            capture = cv2.VideoCapture(video_path)
            decoder_opens = 1
            fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
            target_index = 0
            previous = None
            frame_index = 0
            while target_index < len(timestamps):
                ok, frame = capture.read()
                if not ok:
                    break
                timestamp = frame_index / fps
                while target_index < len(timestamps) and timestamp >= timestamps[target_index]:
                    if previous is None or timestamp - timestamps[target_index] <= timestamps[target_index] - previous[0]:
                        chosen = frame
                    else:
                        chosen = previous[1]
                    frames_selected += int(chosen is not None)
                    target_index += 1
                previous = (timestamp, frame)
                frame_index += 1
            if previous is not None:
                frames_selected += len(timestamps) - target_index
            capture.release()
            first_pass_seconds = time.perf_counter() - start
        else:
            import av
            from msa_indexer.db.sqlite_store import SQLiteStore
            from msa_indexer.io.video_frames import FrameRequest, VideoFrameCache

            real_open = av.open

            def counted_open(*args, **kwargs):
                nonlocal decoder_opens
                decoder_opens += 1
                return real_open(*args, **kwargs)

            av.open = counted_open
            with tempfile.TemporaryDirectory(prefix="msa-frame-bench-") as temporary:
                root = Path(temporary)
                store = SQLiteStore(root / "bench.sqlite3")
                try:
                    schema = Path(__file__).resolve().parents[1] / "src" / "msa_indexer" / "db" / "schema.sql"
                    store.init_schema_no_migrations(schema)
                    source = Path(video_path)
                    with source.open("rb") as source_file:
                        video_id = hashlib.file_digest(source_file, "sha256").hexdigest()
                    store.upsert_media({
                        "media_id": video_id, "path": str(source),
                        "source_name": "frame-benchmark", "rel_path": source.name,
                        "size_bytes": source.stat().st_size, "mime": "video/test",
                    })
                    cache = VideoFrameCache(store, root / "cache", budget_mb=256)
                    requests = [
                        FrameRequest(0, index, timestamp)
                        for index, timestamp in enumerate(timestamps)
                    ]
                    first_start = time.perf_counter()
                    extracted = list(cache.extract_batch(video_id, source, requests))
                    first_pass_seconds = time.perf_counter() - first_start
                    frames_selected = sum(item.reference is not None for item in extracted)
                    reuse_start = time.perf_counter()
                    for _pass in range(consumer_passes - 1):
                        reused = list(cache.extract_batch(
                            video_id,
                            source,
                            [
                                FrameRequest(
                                    item.request.shot_index,
                                    item.request.keyframe_index,
                                    item.request.requested_timestamp,
                                    existing_frame_id=item.reference.frame_id,
                                )
                                for item in extracted if item.reference is not None
                            ],
                        ))
                        cache_reuse_hits += sum(
                            item.reference is not None for item in reused
                        )
                    reuse_pass_seconds = time.perf_counter() - reuse_start
                    cache_bytes = store.video_frame_cache_size()
                finally:
                    store.close()
            av.open = real_open
        result_queue.put({
            "mode": mode,
            "elapsed_seconds": round(time.perf_counter() - start, 4),
            "first_pass_seconds": round(first_pass_seconds, 4),
            "reuse_pass_seconds": round(reuse_pass_seconds, 4),
            "decoder_opens": decoder_opens,
            "consumer_passes": consumer_passes,
            "frames_selected": frames_selected,
            "cache_reuse_hits": cache_reuse_hits,
            "cache_bytes": cache_bytes,
            "peak_rss_mb": _rss_peak_mb(),
        })
    except Exception as exc:
        result_queue.put({"mode": mode, "error": type(exc).__name__})


def _run_worker(
    mode: str, video_path: Path, timestamps: list[float], consumer_passes: int
) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(
        target=_worker,
        args=(mode, str(video_path), timestamps, consumer_passes, queue),
    )
    process.start()
    process.join()
    if process.exitcode != 0:
        return {"mode": mode, "error": f"worker exited {process.exitcode}"}
    try:
        result = queue.get(timeout=2)
    except Empty:
        return {"mode": mode, "error": "worker returned no result"}
    finally:
        queue.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="local video file (read-only)")
    parser.add_argument("--samples", type=int, default=8, help="timestamp count (default: 8)")
    parser.add_argument("--consumer-passes", type=int, default=3, help="independent consumers (default: 3)")
    args = parser.parse_args()
    if args.samples < 1 or args.consumer_passes < 1 or not args.video.is_file():
        parser.error("video must exist; sample and consumer counts must be positive")

    import cv2
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    capture.release()
    if fps <= 0 or count <= 0:
        parser.error("could not read video duration/FPS")
    duration = count / fps
    timestamps = [duration * (index + 0.5) / args.samples for index in range(args.samples)]
    with args.video.open("rb") as source:
        original_hash = hashlib.file_digest(source, "sha256").hexdigest()

    results = [
        _run_worker(mode, args.video.resolve(), timestamps, args.consumer_passes)
        for mode in ("independent-seeks", "grouped-pyav-seeks", "sequential")
    ]
    with args.video.open("rb") as source:
        unchanged = hashlib.file_digest(source, "sha256").hexdigest() == original_hash
    print(json.dumps({
        "video_name": args.video.name,
        "duration_seconds": round(duration, 3),
        "sample_count": len(timestamps),
        "source_unchanged": unchanged,
        "results": results,
    }, indent=2))
    return 0 if unchanged and all("error" not in result for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
