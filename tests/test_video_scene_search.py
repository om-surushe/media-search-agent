import json
from pathlib import Path

from msa_query.query_engine.filters import apply_filters
from msa_query.query_engine.video_scene_search import (
    merge_video_scene_matches,
    search_video_scene_captions,
)
from msa_query.storage.db import connect_readonly
from msa_apps.search_api.schemas import SearchItem

SCHEMA = Path(__file__).parents[1] / "src/msa_indexer/db/schema.sql"


def _add_video(db, video_id, path):
    db.conn.execute(
        "INSERT INTO media(media_id, path, mime, source_name, rel_path) VALUES(?, ?, ?, ?, ?)",
        (video_id, path, "video/mp4", "fixture", path.rsplit("/", 1)[-1]),
    )


def _add_scene(db, video_id, shot_index, timestamp, caption, *, status="completed", tags=None, model="model-a"):
    db.conn.execute(
        "INSERT INTO video_keyframes(video_id, shot_index, kf_index, timestamp, shot_start, shot_end, tags) "
        "VALUES(?, ?, 0, ?, ?, ?, ?)",
        (video_id, shot_index, timestamp, max(0.0, timestamp - 2), timestamp + 2, json.dumps(tags or [])),
    )
    keyframe_id = db.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.conn.execute(
        "INSERT INTO video_scene_caption(video_id, keyframe_id, timestamp, caption, model_id, "
        "prompt_version, generated_at_utc, status) VALUES(?, ?, ?, ?, ?, 'scene-v1', '2026-10-14T00:00:00Z', ?)",
        (video_id, keyframe_id, timestamp, caption, model, status),
    )
    return keyframe_id


def test_video_scene_search_groups_matches_and_is_readonly(isolated_db):
    db = isolated_db
    _add_video(db, "video-a", "/test/people.mp4")
    _add_video(db, "video-b", "/test/other.mp4")
    first = _add_scene(db, "video-a", 0, 6.8, "A group of people wearing pink shirts.", tags=["people"])
    second = _add_scene(db, "video-a", 1, 18.2, "People stand beside pink shirts and pink scarves.")
    _add_scene(db, "video-a", 2, 24.0, "Pink shirts are on a table.", status="failed")
    _add_scene(db, "video-b", 0, 1.5, "A person wears a pink shirt.")
    db.conn.execute("UPDATE media SET deleted=1 WHERE media_id='video-b'")
    db.commit()

    db_path = Path(db.conn.execute("PRAGMA database_list").fetchone()[2])
    conn = connect_readonly(db_path)
    try:
        before = conn.execute("SELECT COUNT(*) FROM video_scene_caption").fetchone()[0]
        hits = search_video_scene_captions(conn, "pink shirts", limit=10)
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM video_scene_caption").fetchone()[0] == before
        in_range = search_video_scene_captions(
            conn, "pink shirts", filters={"timestamp_range": [18.0, 19.0]}
        )
        assert [match["timestamp"] for match in in_range[0]["scene_matches"]] == [18.2]
    finally:
        conn.close()

    assert [hit["id"] for hit in hits] == ["video-a"]
    assert hits[0]["keyframe_id"] == second
    assert [match["timestamp"] for match in hits[0]["scene_matches"]] == [18.2, 6.8]
    assert hits[0]["scene_matches"][1]["keyframe_id"] == first
    assert hits[0]["caption_excerpt"] == hits[0]["scene_matches"][0]["caption_excerpt"]
    assert hits[0]["tags"] == ["people"]


def test_video_scene_search_respects_media_filters(isolated_db):
    db = isolated_db
    _add_video(db, "video-a", "/test/people.mp4")
    _add_scene(db, "video-a", 0, 6.8, "A group of people wearing pink shirts.")
    hits = search_video_scene_captions(db.conn, "pink shirts")

    assert len(apply_filters(hits, {"media_type": "video", "timestamp_range": [6.0, 8.0]})) == 1
    assert apply_filters(hits, {"timestamp_range": [9.0, 10.0]}) == []
    assert apply_filters(hits, {"min_duration": 10.0}) == []


def test_search_item_schema_accepts_timestamped_scene_matches():
    result = SearchItem.model_validate({
        "id": "video-a",
        "path": "/test/people.mp4",
        "thumbnail": None,
        "why": "Video scene caption match",
        "scene_timestamp": 6.8,
        "scene_matches": [{
            "keyframe_id": 11,
            "timestamp": 6.8,
            "caption_excerpt": "people wearing pink shirts",
        }],
    })

    assert result.scene_timestamp == 6.8
    assert result.scene_matches[0].keyframe_id == 11


def test_scene_matches_merge_without_changing_visual_rank_or_duplicate_videos():
    results = [
        {"id": "video-a", "type": "video", "score": 0.82, "timestamp": 2.0},
        {"id": "image-a", "type": "image", "score": 0.91},
        {"id": "video-a", "type": "video", "score": 0.70, "timestamp": 30.0},
    ]
    hit = {
        "id": "video-a", "path": "/test/a.mp4", "type": "video", "timestamp": 6.8,
        "caption_excerpt": "people wearing pink shirts", "scene_matches": [
            {"keyframe_id": 1, "timestamp": 6.8, "caption_excerpt": "people wearing pink shirts"},
            {"keyframe_id": 2, "timestamp": 18.2, "caption_excerpt": "pink shirts near the door"},
        ],
    }
    scene_only = {**hit, "id": "video-b", "timestamp": 3.0, "scene_matches": hit["scene_matches"][:1]}

    merged = merge_video_scene_matches(results, [hit, scene_only])

    assert [item["id"] for item in merged] == ["video-a", "image-a", "video-b"]
    assert merged[0]["score"] == 0.82 and merged[0]["timestamp"] == 2.0
    assert merged[0]["scene_timestamp"] == 6.8
    assert len(merged[0]["scene_matches"]) == 2
    assert merged[-1]["score"] is None and merged[-1]["timestamp"] == 3.0
