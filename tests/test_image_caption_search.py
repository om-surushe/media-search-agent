from pathlib import Path
from unittest.mock import Mock

import pytest

from msa_query.config import settings
from msa_query.query_engine.engine import QueryEngine
from msa_query.query_engine.image_caption_search import search_image_captions
from msa_query.storage.db import connect_readonly


def _add_media(db, media_id, path, mime="image/jpeg", deleted=0):
    db.conn.execute(
        "INSERT INTO media(media_id, path, mime, deleted) VALUES(?, ?, ?, ?)",
        (media_id, path, mime, deleted),
    )


def _add_caption(db, media_id, caption, model="model-a", prompt="v1", status="completed"):
    db.conn.execute(
        """INSERT INTO image_caption(
               media_id, caption, model_id, prompt_version, generated_at_utc, status
           ) VALUES(?, ?, ?, ?, '2026-10-14T00:00:00Z', ?)""",
        (media_id, caption, model, prompt, status),
    )


def test_caption_search_is_readonly_groups_variants_and_returns_images(isolated_db):
    db = isolated_db
    _add_media(db, "image-2", "/test/second.jpg")
    _add_media(db, "video-1", "/test/clip.mp4", "video/mp4")
    _add_media(db, "deleted-1", "/test/deleted.jpg", deleted=1)
    _add_caption(db, "test_media_001", "Red bicycle beside a red brick wall.", "model-a")
    _add_caption(db, "test_media_001", "A red bicycle parked near a wall.", "model-b")
    _add_caption(db, "image-2", "A red bicycle by the coast.")
    _add_caption(db, "video-1", "A red bicycle in a video.")
    _add_caption(db, "deleted-1", "A red bicycle in a deleted image.")
    _add_caption(db, "image-2", "A red bicycle that failed.", "model-failed", status="failed")
    db.commit()

    db_path = Path(db.conn.execute("PRAGMA database_list").fetchone()[2])
    conn = connect_readonly(db_path)
    try:
        before = conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0]
        hits = search_image_captions(conn, "show me a photo of red bicycle", limit=10)
        after = conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0]
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        conn.close()

    assert [hit["id"] for hit in hits] == ["test_media_001", "image-2"]
    assert hits[0]["caption_excerpt"] == "Red bicycle beside a red brick wall."
    assert after == before


def test_query_engine_keeps_visual_results_and_appends_deduplicated_caption_hits(isolated_db):
    db = isolated_db
    _add_media(db, "image-2", "/test/second.jpg")
    _add_media(db, "visual-only", "/test/visual-only.jpg")
    tag_id = db.conn.execute("INSERT INTO tag(name) VALUES('garden')").lastrowid
    db.conn.execute("INSERT INTO media_tag(media_id, tag_id) VALUES('image-2', ?)", (tag_id,))
    _add_caption(db, "test_media_001", "A red bicycle beside the fence.")
    _add_caption(db, "image-2", "A red bicycle beside a garden.")
    _add_caption(db, "image-2", "A red bicycle beside a garden.", "model-b")
    db.commit()

    db_path = Path(db.conn.execute("PRAGMA database_list").fetchone()[2])
    retriever = Mock()
    retriever.search.side_effect = lambda collection, *_args, **_kwargs: (
        [
            {"id": "test_media_001", "score": 0.91, "path": "/test/photo1.jpg", "date": None},
            {"id": "visual-only", "score": 0.73, "path": "/test/visual-only.jpg", "date": None},
        ] if collection == settings.vector_collection_image else []
    )
    encoder = Mock()
    encoder.encode.return_value = [0.1] * 768
    engine = QueryEngine(retriever, encoder, sqlite_path=db_path)

    results = engine.search("red bicycle")
    by_id = {item["id"]: item for item in results}

    assert [item["id"] for item in results].count("image-2") == 1
    assert by_id["test_media_001"]["caption_excerpt"] == "A red bicycle beside the fence."
    assert by_id["image-2"]["caption_excerpt"] == "A red bicycle beside a garden."
    assert by_id["visual-only"]["caption_excerpt"] is None
    assert by_id["test_media_001"]["score"] == pytest.approx(0.91)
    filtered = engine.search("red bicycle", filters={"tags": ["garden"]})
    assert [item["id"] for item in filtered] == ["image-2"]
    assert engine.search("red bicycle", filters={"media_type": "video"}) == []
    encoder.encode.assert_called_with("red bicycle")
