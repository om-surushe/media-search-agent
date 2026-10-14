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


def test_query_engine_returns_caption_and_scene_matches_without_clip(isolated_db):
    db = isolated_db
    _add_media(db, "caption-image", "/test/chicken-salad.jpg")
    _add_caption(db, "caption-image", "A bowl of chicken salad with lettuce.")
    _add_media(db, "scene-video", "/test/pink-shirts.mp4", mime="video/mp4")
    db.conn.execute(
        "INSERT INTO video_keyframes(video_id, shot_index, kf_index, timestamp, shot_start, shot_end, tags) "
        "VALUES('scene-video', 0, 0, 6.8, 5.0, 8.0, '[]')"
    )
    keyframe_id = db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.conn.execute(
        "INSERT INTO video_scene_caption(video_id, keyframe_id, timestamp, caption, model_id, "
        "prompt_version, generated_at_utc, status) "
        "VALUES('scene-video', ?, 6.8, 'A group wearing pink shirts.', 'model-a', 'scene-v1', "
        "'2026-10-14T00:00:00Z', 'completed')",
        (keyframe_id,),
    )
    db.commit()

    db_path = Path(db.conn.execute("PRAGMA database_list").fetchone()[2])
    retriever = Mock()
    engine = QueryEngine(retriever, None, sqlite_path=db_path, semantic_fallback_on_error=True)
    before = db.conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0]

    captions = engine.search("chicken salad")
    scenes = engine.search("pink shirts")

    assert captions[0]["id"] == "caption-image"
    assert captions[0]["caption_excerpt"] == "A bowl of chicken salad with lettuce."
    assert scenes[0]["id"] == "scene-video"
    assert scenes[0]["timestamp"] == 6.8
    assert scenes[0]["scene_matches"][0]["timestamp"] == 6.8
    assert scenes.query_context["semantic_search_available"] is False
    assert "unavailable" in scenes.query_context["semantic_search_message"]
    retriever.search.assert_not_called()
    assert db.conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0] == before


def test_query_engine_falls_back_to_lexical_matches_if_clip_inference_fails(isolated_db):
    db = isolated_db
    _add_media(db, "caption-image", "/test/chicken-salad.jpg")
    _add_caption(db, "caption-image", "A bowl of chicken salad with lettuce.")
    db.commit()
    db_path = Path(db.conn.execute("PRAGMA database_list").fetchone()[2])
    retriever = Mock()
    encoder = Mock()
    encoder.encode.side_effect = RuntimeError("offline cache miss")
    engine = QueryEngine(retriever, encoder, sqlite_path=db_path, semantic_fallback_on_error=True)

    results = engine.search("chicken salad")

    assert results[0]["id"] == "caption-image"
    assert results.query_context["semantic_search_available"] is False
    retriever.search.assert_not_called()


def test_query_engine_merges_scene_text_without_changing_visual_rank_or_time_filter(isolated_db):
    db = isolated_db
    _add_media(db, "scene-video", "/test/scene.mp4", mime="video/mp4")
    for shot_index, timestamp, caption in [
        (0, 6.8, "A group of people wearing pink shirts."),
        (1, 18.2, "People stand beside pink shirts and pink scarves."),
    ]:
        db.conn.execute(
            "INSERT INTO video_keyframes(video_id, shot_index, kf_index, timestamp, shot_start, shot_end, tags) "
            "VALUES('scene-video', ?, 0, ?, ?, ?, '[]')",
            (shot_index, timestamp, timestamp - 2, timestamp + 2),
        )
        keyframe_id = db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.conn.execute(
            "INSERT INTO video_scene_caption(video_id, keyframe_id, timestamp, caption, model_id, "
            "prompt_version, generated_at_utc, status) "
            "VALUES('scene-video', ?, ?, ?, 'model-a', 'scene-v1', '2026-10-14T00:00:00Z', 'completed')",
            (keyframe_id, timestamp, caption),
        )
    db.commit()

    db_path = Path(db.conn.execute("PRAGMA database_list").fetchone()[2])
    retriever = Mock()
    retriever.search.side_effect = lambda collection, *_args, **_kwargs: (
        [
            {"id": "scene-video", "score": 0.91, "path": "/test/scene.mp4", "type": "video", "timestamp": 1.0},
            {"id": "scene-video", "score": 0.73, "path": "/test/scene.mp4", "type": "video", "timestamp": 30.0},
        ] if collection == settings.vector_collection_video else []
    )
    encoder = Mock()
    encoder.encode.return_value = [0.1] * 768
    engine = QueryEngine(retriever, encoder, sqlite_path=db_path)

    results = engine.search("pink shirts")
    assert [result["id"] for result in results] == ["scene-video"]
    assert results[0]["score"] == pytest.approx(0.91)
    assert results[0]["timestamp"] == 1.0
    assert results[0]["scene_timestamp"] == 18.2
    assert [match["timestamp"] for match in results[0]["scene_matches"]] == [18.2, 6.8]

    filtered = engine.search("pink shirts", filters={"timestamp_range": [18.0, 19.0]})
    assert [result["id"] for result in filtered] == ["scene-video"]
    assert filtered[0]["score"] is None
    assert filtered[0]["timestamp"] == 18.2
    assert [match["timestamp"] for match in filtered[0]["scene_matches"]] == [18.2]
