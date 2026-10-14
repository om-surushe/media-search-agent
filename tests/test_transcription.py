import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from msa_indexer.db.sqlite_store import SQLiteStore
from msa_indexer.models.asr import (
    LocalWhisperTranscriber,
    TranscriptResult,
    WHISPER_MODEL_NAME,
    WHISPER_MODEL_REVISION,
    WHISPER_RUNTIME_VERSION,
)
from msa_indexer.pipeline import (
    _count_phase_expects_free_skip,
    _transcription_needs_processing,
)
from msa_query.query_engine.transcript_search import search_transcripts

SCHEMA = Path(__file__).parents[1] / "src/msa_indexer/db/schema.sql"


@pytest.mark.parametrize(
    ("setting", "expected"),
    [(True, True), (False, False), (None, False)],
    ids=["enabled", "disabled", "default-disabled"],
)
def test_transcription_config_loading(tmp_path, monkeypatch, setting, expected):
    from msa_settings.config import reload_config

    monkeypatch.delenv("MSA_DEV", raising=False)
    monkeypatch.setenv("MSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MSA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MSA_LOG_DIR", str(tmp_path / "logs"))
    config_data = {"media_sources": []}
    if setting is not None:
        config_data["enable_speech_transcription"] = setting
    config_path = tmp_path / "config.yaml"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")

    assert reload_config(str(config_path)).enable_speech_transcription is expected


@pytest.fixture
def transcript_db(tmp_path):
    path = tmp_path / "media.sqlite"
    db = SQLiteStore(path)
    db.init_schema(SCHEMA)
    db.upsert_media({
        "media_id": "video-1", "path": "/media/park.mp4",
        "mime": "video/mp4", "size_bytes": 123,
    })
    db.store_transcript(
        "video-1",
        model_name=WHISPER_MODEL_NAME,
        model_revision=WHISPER_MODEL_REVISION,
        runtime_version=WHISPER_RUNTIME_VERSION,
        status="transcribed",
        language="en",
        segments=[{"start": 2.4, "end": 4.8, "text": "Welcome to the park."}],
    )
    db.commit()
    db.close()
    return path


def test_transcript_storage_fts_model_metadata_and_replacement(transcript_db):
    hits = search_transcripts(
        transcript_db, "Find the video where someone says welcome to the park"
    )
    assert len(hits) == 1
    assert hits[0]["media_id"] == "video-1"
    assert hits[0]["revision"] == WHISPER_MODEL_REVISION
    assert hits[0]["segments"] == [{"start": 2.4, "end": 4.8, "text": "Welcome to the park."}]

    db = SQLiteStore(transcript_db)
    db.store_transcript(
        "video-1", model_name=WHISPER_MODEL_NAME,
        model_revision=WHISPER_MODEL_REVISION,
        runtime_version=WHISPER_RUNTIME_VERSION, status="transcribed",
        language="en", segments=[{"start": 8.0, "end": 9.0, "text": "Meeting adjourned."}],
    )
    db.commit()
    db.close()

    assert search_transcripts(transcript_db, "welcome park") == []
    assert search_transcripts(transcript_db, "meeting adjourned")[0]["segments"][0]["start"] == 8.0


def test_failed_reprocessing_preserves_but_hides_old_transcript(transcript_db):
    db = SQLiteStore(transcript_db)
    db.mark_transcription_failed(
        "video-1", model_name=WHISPER_MODEL_NAME,
        model_revision=WHISPER_MODEL_REVISION,
        runtime_version=WHISPER_RUNTIME_VERSION,
    )
    db.commit()
    assert db.conn.execute("SELECT COUNT(*) FROM transcript_segment").fetchone()[0] == 1
    db.close()
    assert search_transcripts(transcript_db, "welcome park") == []


def test_transcription_incremental_skip_and_eta_account_for_stale_state():
    current = {
        "transcription_status": "transcribed",
        "transcription_model": WHISPER_MODEL_NAME,
        "transcription_revision": WHISPER_MODEL_REVISION,
    }
    assert not _transcription_needs_processing(
        current, model_name=WHISPER_MODEL_NAME, model_revision=WHISPER_MODEL_REVISION
    )
    assert _transcription_needs_processing(
        {**current, "transcription_revision": "old"},
        model_name=WHISPER_MODEL_NAME, model_revision=WHISPER_MODEL_REVISION,
    )
    assert _transcription_needs_processing(
        {**current, "transcription_status": "failed"},
        model_name=WHISPER_MODEL_NAME, model_revision=WHISPER_MODEL_REVISION,
    )
    snapshot = {
        **current, "gps_processed": True, "object_detection_done": True,
        "face_detection_done": True, "embeddings_version": "clip-1",
        "has_shots": True, "has_keyframes": True,
        "has_unembedded_keyframes": False,
    }
    assert _count_phase_expects_free_skip(
        snapshot, model_version="clip-1", is_image=False, is_video=True,
        objects_enabled=False, faces_enabled=False,
        transcription_enabled=True,
    )
    assert not _count_phase_expects_free_skip(
        {**snapshot, "transcription_status": None},
        model_version="clip-1", is_image=False, is_video=True,
        objects_enabled=False, faces_enabled=False,
        transcription_enabled=True,
    )


def test_existing_database_gets_additive_transcript_schema(tmp_path):
    path = tmp_path / "legacy.sqlite"
    db = SQLiteStore(path)
    legacy_sql = SCHEMA.read_text().split("-- Local ASR output is canonical SQLite data.")[0]
    db.conn.executescript(legacy_sql)
    db.conn.execute(
        "INSERT INTO media(media_id, path, mime) VALUES ('keep-me', '/media/old.jpg', 'image/jpeg')"
    )
    db.commit()
    db.close()

    upgraded = SQLiteStore(path)
    upgraded.init_schema_no_migrations(SCHEMA)
    assert upgraded.conn.execute(
        "SELECT path FROM media WHERE media_id='keep-me'"
    ).fetchone()[0] == "/media/old.jpg"
    assert upgraded.conn.execute(
        "SELECT name FROM sqlite_master WHERE name='transcript_segment_fts'"
    ).fetchone() is not None
    upgraded.close()


def test_indexer_transcribes_visual_noop_and_skips_current_transcript(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from msa_indexer import pipeline
    import hashlib

    source = tmp_path / "videos"
    source.mkdir()
    video = source / "clip.mp4"
    video.write_bytes(b"fixture video bytes")
    media_id = hashlib.sha256(video.read_bytes()).hexdigest()
    db_path = tmp_path / "index.sqlite"
    db = SQLiteStore(db_path)
    db.init_schema(SCHEMA)
    db.conn.execute(
        """INSERT INTO media(
               media_id, path, source_name, rel_path, mime, size_bytes,
               gps_processed, object_detection_done, face_detection_done, embeddings_version
           ) VALUES (?, ?, 'videos', 'clip.mp4', 'video/mp4', ?, 1, 1, 1, 'test-v1')""",
        (media_id, str(video), video.stat().st_size),
    )
    db.conn.execute(
        "INSERT INTO shots(video_id, shot_index, t_start, t_end) VALUES (?, 0, 0, 5)",
        (media_id,),
    )
    cursor = db.conn.execute(
        """INSERT INTO video_keyframes(
               video_id, shot_index, kf_index, timestamp, shot_start, shot_end
           ) VALUES (?, 0, 0, 0, 0, 5)""",
        (media_id,),
    )
    db.conn.execute(
        """INSERT INTO keyframe_embedding(
               keyframe_id, embedding, embedding_dim, embedding_model
           ) VALUES (?, ?, 1, 'test')""",
        (cursor.lastrowid, b"\\0\\0\\0\\0"),
    )
    db.commit()
    db.close()

    calls = []

    class FakeTranscriber:
        def __init__(self, *_args):
            pass

        def transcribe(self, path):
            calls.append(path)
            return TranscriptResult(
                "transcribed", "en", ({"start": 1.0, "end": 2.0, "text": "Hello there."},)
            )

    monkeypatch.setattr(pipeline, "ClipEmbedder", lambda *_a, **_k: object())
    monkeypatch.setattr(pipeline, "LocalWhisperTranscriber", FakeTranscriber)
    monkeypatch.setattr(pipeline, "_load_historical_perf", lambda _p: (0.0, 0.0, 0.0))
    monkeypatch.setattr(pipeline, "_emit_indexer_summary", lambda **_p: None)
    monkeypatch.setattr(pipeline.qdrant_handoff, "handoff_window", lambda **_k: nullcontext())
    monkeypatch.setattr(pipeline.qdrant_handoff, "call_with_lock_retry", lambda fn: fn())
    monkeypatch.setattr(pipeline, "get_qdrant_export_version", lambda: None)
    monkeypatch.setattr(pipeline, "record_qdrant_export_version", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "_do_qdrant_export", lambda *_a, **_k: None)
    from msa_settings.config import reload_config

    monkeypatch.delenv("MSA_DEV", raising=False)
    monkeypatch.setenv("MSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MSA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MSA_LOG_DIR", str(tmp_path / "logs"))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(json.dumps({
        "media_sources": [{"name": "videos", "path": str(source), "enabled": True}],
        "index_dir": str(tmp_path / "index"),
        "sqlite_path": str(db_path),
        "models_dir": str(tmp_path / "models"),
        "log_dir": str(tmp_path / "logs"),
        "model_version": "test-v1",
        "device": "cpu",
        "enable_speech_transcription": True,
        "enable_object_detection": False,
        "enable_face_recognition": False,
        "enable_video_shot_detection": False,
        "incremental": {"fingerprint_enabled": False, "deletion_sweep": False},
    }), encoding="utf-8")
    config = reload_config(str(config_path))

    pipeline.run_index(config)
    db = SQLiteStore(db_path)
    assert db.get_processing_status(media_id)["transcription_status"] == "transcribed"
    db.close()
    pipeline.run_index(config)
    assert calls == [video]


def test_transcriber_defers_model_loading_until_audio_is_processed(tmp_path):
    transcriber = LocalWhisperTranscriber(tmp_path, "mps")
    assert transcriber.device == "cpu"
    assert transcriber._model is None
    assert not (tmp_path / "whisper").exists()


def test_transcript_search_api_returns_video_and_timestamp(transcript_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MSA_SEARCH_BROWSE_READ_ONLY", "1")
    with sqlite3.connect(f"file:{transcript_db}?mode=ro", uri=True) as conn:
        before = conn.execute("SELECT COUNT(*) FROM transcript_segment").fetchone()[0]
    config = SimpleNamespace(
        sqlite_path=transcript_db,
        server=SimpleNamespace(qdrant_url="http://localhost:6333", qdrant_api_key=None),
        collections=SimpleNamespace(face="face_emb"),
        thumb_dir=tmp_path / "thumbnails",
        face_thumb_dir=tmp_path / "face_thumbnails",
        log_dir=tmp_path / "logs",
        models_dir=tmp_path / "models",
        log_level="DEBUG",
    )
    config.thumb_dir.mkdir()
    config.face_thumb_dir.mkdir()
    config.log_dir.mkdir()
    from msa_apps.search_api.app import create_app

    app = create_app(
        config_override=config, query_engine_override=MagicMock(), reset_dependencies=True
    )
    with TestClient(app) as client:
        response = client.post(
            "/transcripts/search",
            json={"q": "Find the video where someone says welcome to the park"},
        )
    assert response.status_code == 200
    match = response.json()["results"][0]
    assert match["path"] == "/media/park.mp4"
    assert match["segments"][0]["start"] == 2.4
    assert match["segments"][0]["end"] == 4.8
    assert match["segments"][0]["text"] == "Welcome to the park."
    with sqlite3.connect(f"file:{transcript_db}?mode=ro", uri=True) as conn:
        after = conn.execute("SELECT COUNT(*) FROM transcript_segment").fetchone()[0]
    assert before == after
