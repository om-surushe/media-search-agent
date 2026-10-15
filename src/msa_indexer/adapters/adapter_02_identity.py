"""Stage 02: read-only identity preview for a whole configured source."""
from __future__ import annotations

import hashlib
from pathlib import Path

from msa_settings.paths import resolve_for_access
from msa_indexer.io.scanner import ScanStats, iter_media_entries
from .adapter_01_discovery import validated_sample_path


def preview_identity(source, relative_path: str) -> dict:
    """Hash one validated configured-source file without changing it or an index."""
    root, path = validated_sample_path(source, relative_path)
    digest = hashlib.sha256()
    with path.open("rb") as media:
        for chunk in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "source": source.name,
        "relative_path": path.relative_to(root).as_posix(),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
        "incremental_match": None,
        "incremental_match_reason": "Live SQLite fingerprints are intentionally not read by the workbench.",
    }


def preview_source_identity(source, result_limit: int = 25) -> dict:
    """Hash every media file in a configured source; return bounded result details."""
    if not 1 <= result_limit <= 100:
        raise ValueError("Result limit must be between 1 and 100")
    root = Path(resolve_for_access(str(source.path))).resolve()
    if not root.is_dir():
        raise ValueError("Configured source is not an accessible directory")
    results = []
    failures = 0
    total = 0
    stats = ScanStats()
    for path, _stat in iter_media_entries(root, stats=stats):
        total += 1
        try:
            result = preview_identity(source, path.relative_to(root).as_posix())
            if len(results) < result_limit:
                results.append(result)
        except (OSError, ValueError):
            failures += 1
    return {
        "source": source.name,
        "scope": "whole_configured_source",
        "files_checked": total,
        "failures": failures,
        "scan_errors": stats.walk_errors,
        "complete": failures == 0 and stats.walk_errors == 0,
        "results_limit": result_limit,
        "results_truncated": total > len(results),
        "results": results,
        "persisted": False,
    }
