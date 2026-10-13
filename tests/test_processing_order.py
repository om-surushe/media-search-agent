from types import SimpleNamespace

import pytest

from msa_indexer.pipeline import _sort_media_entries


def _entry(root, name, *, size=1, mtime_ns=0, source="photos", source_index=0):
    path = root / name
    return (
        SimpleNamespace(name=source),
        root,
        path,
        SimpleNamespace(st_size=size, st_mtime_ns=mtime_ns),
        source_index,
    )


def _names(entries):
    return [entry[2].name for entry in entries]


def test_default_order_preserves_existing_scanner_order(tmp_path):
    entries = [
        _entry(tmp_path, "z.jpg"),
        _entry(tmp_path, "b.jpg"),
        _entry(tmp_path, "a.jpg"),
        _entry(tmp_path, "c.jpg", source="archive", source_index=1),
    ]
    assert _sort_media_entries(entries, "default") == entries


def test_fastest_orders_images_then_smaller_files_and_videos(tmp_path):
    entries = [
        _entry(tmp_path, "large.jpg", size=20),
        _entry(tmp_path, "large.mp4", size=20),
        _entry(tmp_path, "small.mp4", size=1),
        _entry(tmp_path, "small.png", size=1),
    ]
    assert _names(_sort_media_entries(entries, "fastest")) == [
        "small.png", "large.jpg", "small.mp4", "large.mp4"
    ]


def test_chronological_orders_use_mtime_and_stable_ties(tmp_path):
    entries = [
        _entry(tmp_path, "b.jpg", mtime_ns=10),
        _entry(tmp_path, "c.jpg", mtime_ns=20),
        _entry(tmp_path, "a.jpg", mtime_ns=10),
    ]
    assert _names(_sort_media_entries(entries, "newest")) == ["c.jpg", "a.jpg", "b.jpg"]
    assert _names(_sort_media_entries(entries, "oldest")) == ["a.jpg", "b.jpg", "c.jpg"]


def test_missing_or_invalid_metadata_falls_back_to_zero(tmp_path):
    missing = (SimpleNamespace(name="photos"), tmp_path, tmp_path / "missing.jpg", SimpleNamespace(), 0)
    invalid = (
        SimpleNamespace(name="photos"), tmp_path, tmp_path / "invalid.jpg",
        SimpleNamespace(st_size="bad", st_mtime_ns="bad", st_mtime="bad"), 0,
    )
    valid = _entry(tmp_path, "valid.jpg", size=1, mtime_ns=1)
    assert _names(_sort_media_entries([valid, invalid, missing], "fastest")) == [
        "invalid.jpg", "missing.jpg", "valid.jpg"
    ]
    assert _names(_sort_media_entries([valid, invalid, missing], "oldest")) == [
        "invalid.jpg", "missing.jpg", "valid.jpg"
    ]


def test_invalid_order_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Invalid processing order"):
        _sort_media_entries([_entry(tmp_path, "a.jpg")], "random")
