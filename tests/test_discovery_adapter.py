import os
from types import SimpleNamespace

from msa_indexer.adapters.adapter_01_discovery import discover_media_entries


def test_discovery_returns_ordered_worklist_and_per_source_walk_stats(tmp_path):
    source_root = tmp_path / "photos"
    (source_root / "nested").mkdir(parents=True)
    (source_root / "b.jpg").write_bytes(b"b")
    (source_root / "nested" / "a.jpg").write_bytes(b"a")
    (source_root / ".hidden.jpg").write_bytes(b"hidden")
    (source_root / "notes.txt").write_text("not media")
    os.utime(source_root / "nested" / "a.jpg", ns=(1_000_000_000, 1_000_000_000))
    os.utime(source_root / "b.jpg", ns=(2_000_000_000, 2_000_000_000))
    source = SimpleNamespace(name="photos", path=str(source_root))

    entries, stats = discover_media_entries([source], order="oldest")

    assert [entry[2].name for entry in entries] == ["a.jpg", "b.jpg"]
    assert [entry[4] for entry in entries] == [0, 0]
    assert stats["photos"].walk_errors == 0
