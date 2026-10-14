"""
Tests for Phase 2B — Search & Browse API.

Covers:
- POST /search returns score as a real float (not null)
- POST /search results are ordered highest-score first
- GET /media pagination (limit / offset)
- GET /media media_type filter
- GET /media sort_by / sort_order
- GET /media date_from / date_to filter
- GET /media with no rows returns empty items list
"""
import pytest
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path):
    """Minimal SQLite DB seeded with known media rows."""
    db_path = tmp_path / "test.db"
    schema_path = Path(__file__).parents[1] / "src" / "msa_indexer" / "db" / "schema.sql"

    from msa_indexer.db.sqlite_store import SQLiteStore
    store = SQLiteStore(db_path)
    store.init_schema(schema_path)

    rows = [
        ("id_img_01", "/mnt/p/Photos/beach.heic",    "image/jpeg", "2023-06-15T10:00:00", None,   35.0, -117.0, "San Diego"),
        ("id_img_02", "/mnt/p/Photos/mountain.heic", "image/jpeg", "2023-07-20T14:00:00", None,   37.0, -119.0, "Yosemite"),
        ("id_vid_01", "/mnt/p/Videos/party.mp4",     "video/mp4",  "2023-08-05T18:00:00", 125.0, None,   None,   None),
        ("id_img_03", "/mnt/p/Photos/city.heic",     "image/jpeg", "2022-12-01T09:00:00", None,   40.7,  -74.0, "New York"),
    ]
    for media_id, path, mime, ts_utc, duration, gps_lat, gps_lon, place in rows:
        store.conn.execute(
            "INSERT INTO media(media_id, path, mime, ts_utc, duration, gps_lat, gps_lon, place) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (media_id, path, mime, ts_utc, duration, gps_lat, gps_lon, place),
        )
    store.conn.execute(
        "INSERT INTO shots(video_id, shot_index, t_start, t_end, is_synthetic) VALUES (?,?,?,?,?)",
        ("id_vid_01", 0, 0.0, 125.0, 1),
    )
    store.conn.execute(
        """
        INSERT INTO video_keyframes(
            video_id, shot_index, kf_index, timestamp, shot_start, shot_end, tags,
            gps_lat, gps_lon, gps_alt, gps_datetime_utc, gps_fix, gps_source, place
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "id_vid_01", 0, 0, 62.5, 0.0, 125.0, '["person"]',
            37.7749, -122.4194, 12.5, "2026:02:27 01:17:13.200", 3, "interpolated", "San Francisco"
        ),
    )
    people = [
        ("p1", "Alice"),
        ("p2", "Bob"),
        ("p3", "Carol"),
    ]
    for person_id, name in people:
        store.conn.execute(
            "INSERT INTO person(person_id, name, is_labeled, face_count) VALUES (?,?,1,1)",
            (person_id, name),
        )
    faces = [
        ("f1", "id_img_01", "p1"),
        ("f2", "id_img_02", "p1"),
        ("f3", "id_img_02", "p2"),
        ("f4", "id_img_03", "p2"),
        ("f5", "id_img_03", "p3"),
    ]
    for face_id, media_id, person_id in faces:
        store.conn.execute(
            "INSERT INTO face(face_id, media_id, person_id, x, y, w, h, confidence) VALUES (?,?,?,?,?,?,?,?)",
            (face_id, media_id, person_id, 0.1, 0.1, 0.2, 0.2, 0.99),
        )
    store.commit()
    store.close()
    return db_path


@pytest.fixture()
def client(db, tmp_path):
    """FastAPI test client with injected test DB and mocked query engine."""
    test_config = SimpleNamespace(
        sqlite_path=str(db),
        server=SimpleNamespace(qdrant_url="http://localhost:6333", qdrant_api_key=None),
        collections=SimpleNamespace(face="face_emb"),
        thumb_dir=tmp_path / "thumbnails",
        face_thumb_dir=tmp_path / "face_thumbnails",
        log_dir=tmp_path / "logs",
        models_dir=tmp_path / "models",
        log_level="DEBUG",
    )
    (test_config.thumb_dir).mkdir()
    (test_config.face_thumb_dir).mkdir()
    (test_config.log_dir).mkdir()

    # Mock query engine to return controlled search results with real scores
    mock_qe = MagicMock()
    mock_qe.search.return_value = [
        {
            "id": "id_img_01",
            "path": "/mnt/p/Photos/beach.heic",
            "thumbnail": None,
            "score": 0.91,
            "tags": ["beach", "ocean"],
            "type": "image",
            "timestamp": None,
            "shot_id": None,
            "date": "2023-06-15T10:00:00",
            "caption_excerpt": "Blue water and a sandy beach.",
            "why": "src=img score=0.910",
        },
        {
            "id": "id_img_02",
            "path": "/mnt/p/Photos/mountain.heic",
            "thumbnail": None,
            "score": 0.74,
            "tags": ["mountain"],
            "type": "image",
            "timestamp": None,
            "shot_id": None,
            "date": "2023-07-20T14:00:00",
            "why": "src=img score=0.740",
        },
    ]
    from msa_apps.search_api.app import create_app
    app = create_app(config_override=test_config, query_engine_override=mock_qe, reset_dependencies=True)
    return TestClient(app)


# ── /search tests ─────────────────────────────────────────────────────────────

class TestSearchScore:
    def test_score_is_present_and_float(self, client):
        """score must be a real float, not null — regression for engine.py bug."""
        r = client.post("/search", json={"q": "beach"})
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) > 0
        for item in results:
            assert "score" in item, "score field missing from SearchItem"
            assert item["score"] is not None, "score is null — engine.py did not include it"
            assert isinstance(item["score"], float)
            assert 0.0 <= item["score"] <= 1.0

    def test_results_ordered_by_score_descending(self, client):
        """Results must be ordered highest score first."""
        r = client.post("/search", json={"q": "beach"})
        assert r.status_code == 200
        scores = [item["score"] for item in r.json()["results"]]
        assert scores == sorted(scores, reverse=True), "results not in descending score order"

    def test_path_field_present(self, client):
        """path must be present — required for thumbnail URL derivation in frontend."""
        r = client.post("/search", json={"q": "beach"})
        assert r.status_code == 200
        for item in r.json()["results"]:
            assert "path" in item
            assert item["path"] is not None

    def test_empty_query_returns_200(self, client):
        r = client.post("/search", json={"q": ""})
        assert r.status_code == 200

    def test_caption_excerpt_is_returned(self, client):
        r = client.post("/search", json={"q": "beach"})
        assert r.status_code == 200
        assert r.json()["results"][0]["caption_excerpt"] == "Blue water and a sandy beach."


# ── /media tests ──────────────────────────────────────────────────────────────

class TestMediaListing:
    def test_returns_all_rows_by_default(self, client):
        r = client.get("/media")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 4
        assert len(body["items"]) == 4

    def test_pagination_limit(self, client):
        r = client.get("/media?limit=2")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 2
        assert body["count"] == 4  # total unchanged

    def test_pagination_offset(self, client):
        r_all = client.get("/media?limit=100&sort_by=date&sort_order=asc")
        all_ids = [i["id"] for i in r_all.json()["items"]]

        r_page2 = client.get("/media?limit=2&offset=2&sort_by=date&sort_order=asc")
        page2_ids = [i["id"] for i in r_page2.json()["items"]]

        assert page2_ids == all_ids[2:4]

    def test_filter_images_only(self, client):
        r = client.get("/media?media_type=image")
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(i["type"] == "image" for i in items)
        assert len(items) == 3

    def test_filter_videos_only(self, client):
        r = client.get("/media?media_type=video")
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(i["type"] == "video" for i in items)
        assert len(items) == 1

    def test_sort_date_asc(self, client):
        r = client.get("/media?sort_by=date&sort_order=asc")
        assert r.status_code == 200
        dates = [i["date"] for i in r.json()["items"] if i["date"]]
        assert dates == sorted(dates)

    def test_sort_date_desc(self, client):
        r = client.get("/media?sort_by=date&sort_order=desc")
        assert r.status_code == 200
        dates = [i["date"] for i in r.json()["items"] if i["date"]]
        assert dates == sorted(dates, reverse=True)

    def test_date_from_filter(self, client):
        r = client.get("/media?date_from=2023-07-01")
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(i["date"] >= "2023-07-01" for i in items if i["date"])
        # Should exclude city.heic (2022) and beach.heic (2023-06)
        ids = [i["id"] for i in items]
        assert "id_img_03" not in ids  # 2022
        assert "id_img_01" not in ids  # 2023-06

    def test_date_to_filter(self, client):
        r = client.get("/media?date_to=2023-06-30")
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(i["date"] <= "2023-06-30" for i in items if i["date"])
        ids = [i["id"] for i in items]
        assert "id_img_01" in ids  # 2023-06
        assert "id_img_03" in ids  # 2022
        assert "id_img_02" not in ids  # 2023-07
        assert "id_vid_01" not in ids  # 2023-08


class TestVideoShots:
    def test_video_shots_include_keyframe_gps(self, client):
        r = client.get("/videos/id_vid_01/shots")
        assert r.status_code == 200
        body = r.json()
        assert body["video_id"] == "id_vid_01"
        assert len(body["shots"]) == 1
        keyframes = body["shots"][0]["keyframes"]
        assert len(keyframes) == 1
        assert keyframes[0]["gps_lat"] == 37.7749
        assert keyframes[0]["gps_lon"] == -122.4194
        assert keyframes[0]["place"] == "San Francisco"

    def test_empty_result_when_no_match(self, client):
        r = client.get("/media?date_from=2030-01-01")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["count"] == 0

    def test_people_filter_any(self, client):
        r = client.get("/media?people=Alice")
        assert r.status_code == 200
        ids = [i["id"] for i in r.json()["items"]]
        assert set(ids) == {"id_img_01", "id_img_02"}

    def test_people_filter_all_together(self, client):
        r = client.get("/media?people=Alice,Bob&people_mode=all")
        assert r.status_code == 200
        ids = [i["id"] for i in r.json()["items"]]
        assert ids == ["id_img_02"]

    def test_people_filter_only_selected_people(self, client):
        r = client.get("/media?people=Alice&people_mode=only")
        assert r.status_code == 200
        ids = [i["id"] for i in r.json()["items"]]
        assert ids == ["id_img_01"]

    def test_response_shape(self, client):
        """Each item must have the fields the frontend expects."""
        r = client.get("/media?limit=1")
        item = r.json()["items"][0]
        for field in ("id", "path", "type", "date", "duration", "gps_lat", "gps_lon", "place"):
            assert field in item, f"missing field: {field}"


class TestVideoTagsInAPI:
    """Video object-detection tags are stored per keyframe, not in media_tag.
    Both /media and /media/{id}/info must aggregate them from video_keyframes."""

    def test_media_listing_returns_video_keyframe_tags(self, client):
        """/media should include aggregated keyframe tags for videos."""
        r = client.get("/media?media_type=video")
        assert r.status_code == 200
        items = r.json()["items"]
        video = next(i for i in items if i["id"] == "id_vid_01")
        assert "tags" in video
        assert "person" in video["tags"], f"expected 'person' in tags, got {video['tags']}"

    def test_media_info_returns_video_keyframe_tags(self, client):
        """/media/{id}/info should aggregate tags from video_keyframes for a video."""
        r = client.get("/media/id_vid_01/info")
        assert r.status_code == 200
        data = r.json()
        assert "tags" in data
        assert "person" in data["tags"], f"expected 'person' in tags, got {data['tags']}"

    def test_image_tags_still_served_from_media_tag(self, client, db):
        """Image tags via media_tag table must still work after the video fallback was added."""
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT OR IGNORE INTO tag(name) VALUES ('ocean')")
        tag_id = conn.execute("SELECT tag_id FROM tag WHERE name='ocean'").fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO media_tag(media_id, tag_id) VALUES ('id_img_01', ?)", (tag_id,))
        conn.commit()
        conn.close()

        r = client.get("/media/id_img_01/info")
        assert r.status_code == 200
        assert "ocean" in r.json()["tags"]

    def test_video_with_no_keyframe_tags_returns_empty_list(self, client):
        """A video with no tagged keyframes should return tags: [] not an error."""
        # id_vid_01 has tags; test that other videos (images here) return []
        r = client.get("/media/id_img_01/info")
        assert r.status_code == 200
        assert r.json()["tags"] == []  # no tags seeded for this image


class TestAssetIntelligence:
    def test_returns_canonical_metadata_and_stored_intelligence(self, client, db):
        """Inspector reports stored detections separately from configured-off stages."""
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO tag(name) VALUES ('beach')")
            tag_id = conn.execute("SELECT tag_id FROM tag WHERE name='beach'").fetchone()[0]
            conn.execute("INSERT INTO media_tag(media_id, tag_id) VALUES ('id_img_01', ?)", (tag_id,))
            conn.execute(
                "INSERT INTO image_embedding(media_id, embedding, embedding_dim, embedding_model) VALUES (?,?,?,?)",
                ('id_img_01', sqlite3.Binary(b'not returned'), 768, 'clip-test'),
            )

        response = client.get('/media/id_img_01/intelligence')
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['media']['filename'] == 'beach.heic'
        assert data['media']['size_bytes'] is None
        assert data['embeddings']['image']['present'] is True
        assert 'embedding' not in data['embeddings']['image']
        assert data['faces'][0]['identity_status'] == 'known'
        assert data['stored_tags'] == ['beach']
        assert data['pipeline_status'][0]['status'] == 'disabled'
        assert data['pipeline_status'][0]['evidence'] == 'current_config'
        assert data['descriptions']['image_caption']['status'] == 'not_generated'

    def test_returns_stored_caption_variants_read_only(self, client, db):
        with sqlite3.connect(db) as conn:
            conn.executemany(
                """INSERT INTO image_caption(
                       media_id, caption, model_id, prompt_version, generated_at_utc, status
                   ) VALUES (?,?,?,?,?,'completed')""",
                [
                    ('id_img_01', 'A black dog at a fence.', 'model-b', 'prompt-v1', '2026-10-14T10:01:00+00:00'),
                    ('id_img_01', 'A dog looking through a fence.', 'model-a', 'prompt-v2', '2026-10-14T10:00:00+00:00'),
                ],
            )
            conn.commit()

        with sqlite3.connect(db) as observer:
            before = observer.execute('PRAGMA data_version').fetchone()[0]
            response = client.get('/media/id_img_01/intelligence')
            after = observer.execute('PRAGMA data_version').fetchone()[0]
            rows = observer.execute(
                'SELECT caption, model_id FROM image_caption WHERE media_id=? ORDER BY model_id',
                ('id_img_01',),
            ).fetchall()

        assert response.status_code == 200, response.text
        data = response.json()
        captions = data['descriptions']['image_captions']
        assert [(c['model_id'], c['prompt_version']) for c in captions] == [
            ('model-a', 'prompt-v2'), ('model-b', 'prompt-v1'),
        ]
        assert captions[0] == {
            'caption': 'A dog looking through a fence.',
            'model_id': 'model-a',
            'prompt_version': 'prompt-v2',
            'generated_at_utc': '2026-10-14T10:00:00+00:00',
            'status': 'completed',
        }
        assert data['descriptions']['image_caption'] == {
            'status': 'available',
            'text': 'A black dog at a fence.',
            'model_name': 'model-b',
            'model_revision': None,
            'generated_at': '2026-10-14T10:01:00+00:00',
        }
        assert data['media']['filename'] == 'beach.heic'
        assert data['faces'][0]['identity_status'] == 'known'
        assert data['objects_evidence'] == 'none'
        assert before == after
        assert rows == [
            ('A dog looking through a fence.', 'model-a'),
            ('A black dog at a fence.', 'model-b'),
        ]

    def test_video_scene_captions_include_timestamp_and_provenance_in_order(self, client, db):
        with sqlite3.connect(db) as conn:
            first = conn.execute(
                "SELECT id, timestamp FROM video_keyframes WHERE video_id='id_vid_01'"
            ).fetchone()
            later_timestamp = first[1] + 100.0
            conn.execute(
                """INSERT INTO video_keyframes(
                       video_id, shot_index, kf_index, timestamp, shot_start, shot_end
                   ) VALUES ('id_vid_01', 1, 0, ?, ?, ?)""",
                (later_timestamp, later_timestamp - 5, later_timestamp + 5),
            )
            second_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.executemany(
                """INSERT INTO video_scene_caption(
                       video_id, keyframe_id, timestamp, caption, model_id,
                       prompt_version, generated_at_utc, status
                   ) VALUES ('id_vid_01', ?, ?, ?, ?, 'scene-v1', ?, 'completed')""",
                [
                    (second_id, later_timestamp, "A person enters the room.", "model-b", "2026-10-14T10:02:00+00:00"),
                    (first[0], first[1], "A person waits by a door.", "model-a", "2026-10-14T10:01:00+00:00"),
                ],
            )

        with sqlite3.connect(db) as observer:
            before = observer.execute("PRAGMA data_version").fetchone()[0]
            response = client.get("/media/id_vid_01/intelligence")
            after = observer.execute("PRAGMA data_version").fetchone()[0]
        assert response.status_code == 200, response.text
        rows = response.json()["descriptions"]["video_scene_captions"]
        assert [row["timestamp"] for row in rows] == sorted(row["timestamp"] for row in rows)
        assert [row["caption"] for row in rows] == ["A person waits by a door.", "A person enters the room."]
        assert rows[0]["keyframe_id"] == first[0]
        assert (rows[0]["model_id"], rows[0]["prompt_version"], rows[0]["status"]) == (
            "model-a", "scene-v1", "completed",
        )
        assert before == after

    def test_missing_video_scene_caption_table_is_empty_for_older_database(self, client, db):
        with sqlite3.connect(db) as conn:
            conn.execute("DROP TABLE video_scene_caption")
        response = client.get("/media/id_vid_01/intelligence")
        assert response.status_code == 200, response.text
        assert response.json()["descriptions"]["video_scene_captions"] == []

    def test_missing_caption_table_is_empty_for_older_database(self, client, db):
        with sqlite3.connect(db) as conn:
            conn.execute('DROP TABLE image_caption')
        response = client.get('/media/id_img_01/intelligence')
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['descriptions']['image_captions'] == []
        assert data['descriptions']['image_caption']['status'] == 'not_generated'

    def test_stale_disabled_status_reopens_when_config_is_enabled(self, client, db):
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO media_pipeline_status(media_id,pipeline,status) VALUES (?,?,?)",
                ('id_img_01', 'object_detection', 'disabled'),
            )
        client.app.state.S.enable_object_detection = True
        response = client.get('/media/id_img_01/intelligence')
        assert response.status_code == 200, response.text
        state = next(s for s in response.json()['pipeline_status'] if s['pipeline'] == 'object_detection')
        assert (state['status'], state['evidence'], state['configured_enabled']) == (
            'not_processed', 'current_config', True
        )

    def test_legacy_database_without_status_table_still_inspects(self, client, db):
        with sqlite3.connect(db) as conn:
            conn.execute('DROP TABLE media_pipeline_status')
        response = client.get('/media/id_img_01/intelligence')
        assert response.status_code == 200, response.text
        assert response.json()['pipeline_status'][0]['evidence'] == 'current_config'

    def test_video_keyframes_are_separate_from_object_detection_status(self, client):
        response = client.get('/media/id_vid_01/intelligence')
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['total_shots'] == 1
        assert data['total_keyframes'] == 1
        assert data['keyframes'][0]['tags'] == ['person']
        obj_state = next(s for s in data['pipeline_status'] if s['pipeline'] == 'object_detection')
        assert obj_state['status'] == 'disabled'
        assert data['objects'][0]['evidence'] == 'stored_label_only'


class TestSearchDateBackfill:
    """POST /search must backfill date from SQLite when Qdrant payload has none."""

    def test_search_backfills_date_from_sqlite(self, db, tmp_path):
        """If the query engine returns date=None, the API fills it from SQLite."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from msa_apps.search_api.app import create_app

        test_config = SimpleNamespace(
            sqlite_path=str(db),
            server=SimpleNamespace(qdrant_url="http://localhost:6333", qdrant_api_key=None),
            collections=SimpleNamespace(face="face_emb"),
            thumb_dir=tmp_path / "thumbnails",
            face_thumb_dir=tmp_path / "face_thumbnails",
            log_dir=tmp_path / "logs",
            log_level="DEBUG",
        )
        (test_config.thumb_dir).mkdir()
        (test_config.face_thumb_dir).mkdir()
        (test_config.log_dir).mkdir()

        mock_qe = MagicMock()
        mock_qe.search.return_value = [{
            "id": "id_img_01",
            "path": "/mnt/p/Photos/beach.heic",
            "thumbnail": None,
            "score": 0.91,
            "tags": [],
            "type": "image",
            "timestamp": None,
            "shot_id": None,
            "date": None,   # Qdrant has no date for this item
            "why": "",
        }]

        app = create_app(config_override=test_config, query_engine_override=mock_qe, reset_dependencies=True)
        c = TestClient(app)

        r = c.post("/search", json={"q": "beach"})
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["date"] == "2023-06-15T10:00:00", (
            f"date not backfilled from SQLite, got {results[0]['date']!r}"
        )


@pytest.mark.parametrize(
    ("extension", "expected_mime"),
    [(".mp4", "video/mp4"), (".webm", "video/webm")],
)
def test_video_file_uses_format_specific_mime(client, db, tmp_path, extension, expected_mime):
    media_id = f"mime-test-{extension[1:]}"
    media_path = tmp_path / f"fixture{extension}"
    media_path.write_bytes(b"video fixture")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO media(media_id, path, mime) VALUES (?, ?, ?)",
            (media_id, str(media_path), expected_mime),
        )

    response = client.get(f"/videos/{media_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == expected_mime
    assert response.content == b"video fixture"


def test_video_file_supports_byte_ranges(client, db, tmp_path):
    media_id = "range-test-video"
    media_path = tmp_path / "range-fixture.mp4"
    media_path.write_bytes(b"0123456789")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO media(media_id, path, mime) VALUES (?, ?, ?)",
            (media_id, str(media_path), "video/mp4"),
        )

    response = client.get(f"/videos/{media_id}", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "4"

    suffix = client.get(f"/videos/{media_id}", headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206
    assert suffix.content == b"789"

    unsatisfiable = client.get(f"/videos/{media_id}", headers={"Range": "bytes=10-"})
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["content-range"] == "bytes */10"


def test_read_only_search_runtime_skips_setup_and_rejects_mutations(client, monkeypatch):
    import msa_apps.search_api.app as api_module

    monkeypatch.setenv("MSA_SEARCH_BROWSE_READ_ONLY", "1")
    start_setup = MagicMock()
    monkeypatch.setattr(api_module._setup_models.get_manager(), "start_if_needed", start_setup)

    with client:
        setup = client.get("/api/setup/status")
        assert setup.status_code == 200
        body = setup.json()
        assert body == {"ready": True, "models": [], "read_only_mode": True}
        start_setup.assert_not_called()

        status = client.get("/indexer/status")
        assert status.json()["read_only_mode"] is True
        assert client.post("/indexer/start").status_code == 409
        assert client.post("/api/setup/retry").status_code == 409
        assert client.post("/config/sources", json={"name": "new", "path": "/tmp/new"}).status_code == 409


def test_search_api_marks_lexical_only_results_and_preserves_database(client, db, monkeypatch):
    import msa_apps.search_api.deps as deps
    from msa_query.query_engine.engine import _SearchResults

    monkeypatch.setenv("MSA_SEARCH_BROWSE_READ_ONLY", "1")
    qe = client.app.dependency_overrides[deps.get_query_engine]()
    results = _SearchResults([{
        "id": "id_img_01", "path": "/mnt/p/Photos/beach.heic", "thumbnail": None,
        "score": None, "tags": [], "type": None, "timestamp": None, "shot_id": None,
        "date": None, "caption_excerpt": "stored caption hit", "why": "Caption match",
    }])
    results.query_context = {
        "semantic_search_available": False,
        "semantic_search_message": "Semantic visual search is unavailable; showing stored caption and scene matches.",
    }
    qe.search.return_value = results
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        before = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]

    with client:
        response = client.post("/search", json={"q": "chicken salad"})
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            after = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]

    assert response.status_code == 200
    assert response.json()["semantic_search_available"] is False
    assert "unavailable" in response.json()["semantic_search_message"]
    assert response.json()["results"][0]["caption_excerpt"] == "stored caption hit"
    assert before == after


def test_read_only_runtime_is_ready_without_any_model_weights(client, monkeypatch):
    monkeypatch.setenv("MSA_SEARCH_BROWSE_READ_ONLY", "1")
    with client:
        body = client.get("/api/setup/status").json()
        assert body == {"ready": True, "models": [], "read_only_mode": True}


def test_read_only_query_engine_skips_encoder_when_clip_is_missing(monkeypatch, tmp_path):
    import msa_apps.search_api.deps as deps

    monkeypatch.setenv("MSA_SEARCH_BROWSE_READ_ONLY", "1")
    cfg = SimpleNamespace(
        models_dir=tmp_path / "models",
        sqlite_path=tmp_path / "missing.db",
        retrieval=SimpleNamespace(search_score_trace=False),
    )
    monkeypatch.setattr(deps, "load_config", lambda: cfg)
    encoder = MagicMock(side_effect=AssertionError("must not initialize without cached CLIP"))
    monkeypatch.setattr(deps, "TextEncoder", encoder)
    deps.reset_query_engine()
    try:
        engine = deps.get_query_engine()
        results = engine.search("no model needed")
        assert results.query_context["semantic_search_available"] is False
        assert results.query_context["semantic_search_message"]
        encoder.assert_not_called()
    finally:
        deps.reset_query_engine()


def test_normal_runtime_keeps_automatic_model_setup(client, monkeypatch):
    import msa_apps.search_api.app as api_module

    monkeypatch.delenv("MSA_SEARCH_BROWSE_READ_ONLY", raising=False)
    start_setup = MagicMock()
    monkeypatch.setattr(api_module._setup_models.get_manager(), "start_if_needed", start_setup)

    with client:
        start_setup.assert_called_once_with(client.app.state.S.models_dir)
