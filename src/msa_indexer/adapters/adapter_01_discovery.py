"""Stage 01: discover, snapshot, and schedule media files."""
from pathlib import Path
from itertools import islice

from msa_settings.paths import resolve_for_access

from msa_indexer.io.scanner import IMAGE_EXT, VIDEO_EXT, ScanStats, iter_media_entries


def db_relative_path(path: Path, root: Path) -> str:
    """Return the shared POSIX key for fingerprints and media rows (ADR-007)."""
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.name


def sort_media_entries(entries, order: str):
    """Schedule files while preserving scanner order for the default policy."""
    valid_orders = {"default", "fastest", "newest", "oldest"}
    if order not in valid_orders:
        raise ValueError(f"Invalid processing order: {order!r}")

    def stable_key(entry):
        source, root, path, _stat, source_index = entry
        relative = db_relative_path(path, root)
        return (source_index, str(source.name).casefold(), relative.casefold(), relative)

    if order == "default":
        return list(entries)

    ordered = sorted(entries, key=stable_key)
    if order == "fastest":
        def size_bytes(entry):
            try:
                value = int(getattr(entry[3], "st_size", 0))
            except (TypeError, ValueError, OverflowError):
                return 0
            return max(0, value)

        return sorted(
            ordered,
            key=lambda entry: (
                0 if entry[2].suffix.lower() in IMAGE_EXT else 1,
                size_bytes(entry),
                stable_key(entry),
            ),
        )

    def modified_ns(entry):
        stat = entry[3]
        try:
            value = int(getattr(stat, "st_mtime_ns"))
        except (AttributeError, TypeError, ValueError, OverflowError):
            try:
                value = int(float(getattr(stat, "st_mtime", 0)) * 1_000_000_000)
            except (TypeError, ValueError, OverflowError):
                value = 0
        return value if value >= 0 else 0

    return sorted(ordered, key=modified_ns, reverse=(order == "newest"))


def validated_sample_path(source, relative_path: str) -> tuple[Path, Path]:
    """Resolve a UI-supplied relative name under an enabled source, rejecting traversal."""
    if not isinstance(relative_path, str) or not relative_path or Path(relative_path).is_absolute():
        raise ValueError("A source-relative media name is required")
    if "\\" in relative_path:
        raise ValueError("Media name must use POSIX relative-path separators")
    root = Path(resolve_for_access(str(source.path))).resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Media name must stay inside the configured source") from exc
    if not candidate.is_file() or candidate.suffix.lower() not in IMAGE_EXT | VIDEO_EXT:
        raise ValueError("Selected source-relative name is not a supported media file")
    return root, candidate


def preview_media_entries(source, limit: int = 25) -> dict:
    """Return a bounded, read-only sample from one configured source."""
    if not 1 <= limit <= 100:
        raise ValueError("Sample limit must be between 1 and 100")
    root = Path(resolve_for_access(str(source.path))).resolve()
    if not root.is_dir():
        raise ValueError("Configured source is not an accessible directory")
    entries = list(islice(iter_media_entries(root), limit + 1))
    has_more = len(entries) > limit
    return {
        "source": source.name,
        "sample_limit": limit,
        "has_more": has_more,
        "entries": [
            {"name": path.name, "relative_path": path.relative_to(root).as_posix(),
             "extension": path.suffix.lower(), "size_bytes": stat.st_size}
            for path, stat in entries[:limit]
        ],
        "returned": min(len(entries), limit),
    }


def discover_media_entries(
    sources, stop_event=None, order: str = "default", *,
    entry_iterator=iter_media_entries, sorter=sort_media_entries,
):
    """Walk validated sources once and return the ordered worklist and walk stats."""
    # ponytail: retain only scan metadata for the global sort; use a disk-backed
    # queue only if real libraries make this O(n) snapshot costly.
    entries = []
    walk_stats: dict[str, ScanStats] = {}
    for source_index, source in enumerate(sources):
        root = Path(resolve_for_access(str(source.path)))
        stats = ScanStats()
        walk_stats[source.name] = stats
        for path, stat in entry_iterator(root, stop_event=stop_event, stats=stats):
            entries.append((source, root, path, stat, source_index))
    return sorter(entries, order), walk_stats
