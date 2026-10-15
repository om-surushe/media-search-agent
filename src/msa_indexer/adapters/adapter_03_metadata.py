"""Stage 03: extract metadata across a configured source without persistence."""
from __future__ import annotations

from pathlib import Path

from msa_indexer.io.exif import get_exif_basic_result
from msa_indexer.io.video import get_video_meta_result
from msa_settings.paths import resolve_for_access
from msa_indexer.io.scanner import IMAGE_EXT, ScanStats, iter_media_entries
from .adapter_01_discovery import validated_sample_path


def preview_metadata(source, relative_path: str) -> dict:
    root, path = validated_sample_path(source, relative_path)
    if path.suffix.lower() in IMAGE_EXT:
        metadata, succeeded = get_exif_basic_result(path)
    else:
        metadata, succeeded = get_video_meta_result(path)
    return {
        "source": source.name,
        "relative_path": path.relative_to(root).as_posix(),
        "status": "completed" if succeeded else "unavailable",
        "metadata": metadata,
        "persisted": False,
    }


def preview_source_metadata(source, result_limit: int = 25) -> dict:
    """Extract metadata for every media file; return bounded result details."""
    if not 1 <= result_limit <= 100:
        raise ValueError("Result limit must be between 1 and 100")
    root = Path(resolve_for_access(str(source.path))).resolve()
    if not root.is_dir():
        raise ValueError("Configured source is not an accessible directory")
    results = []
    failures = 0
    completed = 0
    unavailable = 0
    total = 0
    stats = ScanStats()
    for path, _stat in iter_media_entries(root, stats=stats):
        total += 1
        try:
            result = preview_metadata(source, path.relative_to(root).as_posix())
            if result["status"] == "completed":
                completed += 1
            else:
                unavailable += 1
            if len(results) < result_limit:
                results.append(result)
        except (OSError, ValueError, RuntimeError):
            failures += 1
    return {
        "source": source.name,
        "scope": "whole_configured_source",
        "files_checked": total,
        "completed": completed,
        "unavailable": unavailable,
        "failures": failures,
        "scan_errors": stats.walk_errors,
        "complete": failures == 0 and stats.walk_errors == 0,
        "results_limit": result_limit,
        "results_truncated": total > len(results),
        "results": results,
        "persisted": False,
    }
