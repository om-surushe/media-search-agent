import sqlite3

import pytest

from msa_indexer.db.organization import (
    add_collection_media,
    collection_items,
    create_collection,
    ensure_organization_schema,
    get_media_tags,
    list_collections,
    set_media_tags,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "library.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE media (media_id TEXT PRIMARY KEY, path TEXT NOT NULL, mime TEXT, ts_utc TEXT, duration REAL, deleted INTEGER DEFAULT 0)")
    conn.executemany("INSERT INTO media(media_id,path) VALUES (?,?)", [("a" * 64, "/media/a"), ("b" * 64, "/media/b")])
    ensure_organization_schema(conn)
    yield conn
    conn.close()


def test_user_tags_and_virtual_collections_persist_without_copying_media(db, tmp_path):
    media_path = tmp_path / "original.jpg"
    media_path.write_bytes(b"unchanged")

    assert set_media_tags(db, "a" * 64, [" Family ", "family", "Trip"]) == ["Family", "Trip"]
    collection = create_collection(db, "Summer", "family photos")
    add_collection_media(db, collection["collection_id"], ["a" * 64, "b" * 64, "a" * 64])
    db.close()

    conn = sqlite3.connect(tmp_path / "library.sqlite")
    try:
        ensure_organization_schema(conn)
        assert get_media_tags(conn, "a" * 64) == ["Family", "Trip"]
        collections, count = list_collections(conn)
        assert count == 1 and collections[0]["media_count"] == 2
        items, item_count = collection_items(conn, collection["collection_id"])
        assert item_count == 2
        assert {item["id"] for item in items} == {"a" * 64, "b" * 64}
        assert media_path.read_bytes() == b"unchanged"
    finally:
        conn.close()


def test_user_tags_can_filter_search_candidates_without_changing_detector_tags(db):
    from msa_query.query_engine.engine import _enrich_user_tags
    from msa_query.query_engine.filters import apply_filters

    set_media_tags(db, "a" * 64, ["family"])
    candidates = [{"id": "a" * 64, "tags": ["person"]}, {"id": "b" * 64, "tags": ["dog"]}]
    _enrich_user_tags(db, candidates)
    assert candidates[0]["tags"] == ["person"]
    assert candidates[0]["user_tags"] == ["family"]
    assert [item["id"] for item in apply_filters(candidates, {"user_tags": ["family"]})] == ["a" * 64]


def test_organization_rejects_unknown_media_and_bounds_input(db):
    with pytest.raises(KeyError):
        set_media_tags(db, "missing", ["tag"])
    with pytest.raises(ValueError):
        set_media_tags(db, "a" * 64, ["x" * 101])
    with pytest.raises(ValueError):
        set_media_tags(db, "a" * 64, ["family, trip"])
    collection = create_collection(db, "Trips")
    with pytest.raises(KeyError):
        add_collection_media(db, collection["collection_id"], ["missing"])
    with pytest.raises(ValueError):
        add_collection_media(db, collection["collection_id"], ["a" * 64] * 101)
