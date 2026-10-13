from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from msa_indexer.db.sqlite_store import SQLiteStore

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src/msa_indexer/db/schema.sql"
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/caption_image.py"


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "media.sqlite"
    db = SQLiteStore(db_path)
    db.init_schema_no_migrations(SCHEMA_PATH)
    yield db
    db.close()


def add_image(store, tmp_path, data=b"copied image"):
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(data)
    media_id = hashlib.sha256(data).hexdigest()
    store.upsert_media({
        "media_id": media_id,
        "path": str(image_path),
        "source_name": "caption-test",
        "rel_path": image_path.name,
        "size_bytes": len(data),
        "mime": "image/jpeg",
    })
    return image_path, media_id


def import_caption_script():
    spec = importlib.util.spec_from_file_location("caption_image_poc", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_caption_upsert_is_idempotent_and_models_coexist(store, tmp_path):
    _, media_id = add_image(store, tmp_path)
    ts1 = "2026-10-14T10:00:00+00:00"
    ts2 = "2026-10-14T10:01:00+00:00"
    store.store_image_caption(
        media_id, caption="First caption", model_id="mlx/model-a",
        prompt_version="caption-v1", generated_at_utc=ts1,
    )
    store.store_image_caption(
        media_id, caption="Regenerated caption", model_id="mlx/model-a",
        prompt_version="caption-v1", generated_at_utc=ts2,
    )
    store.store_image_caption(
        media_id, caption="Other model caption", model_id="mlx/model-b",
        prompt_version="caption-v1", generated_at_utc=ts2,
    )

    first = store.get_image_caption(media_id, "mlx/model-a", "caption-v1")
    second = store.get_image_caption(media_id, "mlx/model-b", "caption-v1")
    count = store.conn.execute(
        "SELECT COUNT(*) FROM image_caption WHERE media_id = ?", (media_id,)
    ).fetchone()[0]
    assert first == {
        "media_id": media_id,
        "caption": "Regenerated caption",
        "model_id": "mlx/model-a",
        "prompt_version": "caption-v1",
        "generated_at_utc": ts2,
        "status": "completed",
    }
    assert second["caption"] == "Other model caption"
    assert second["model_id"] == "mlx/model-b"
    assert count == 2


def test_caption_requires_valid_live_image_and_timestamp(store, tmp_path):
    _, media_id = add_image(store, tmp_path)
    args = {
        "caption": "A visible scene.", "model_id": "mlx/model",
        "prompt_version": "caption-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    for invalid in ("bad-id", "../escape", " "):
        with pytest.raises(ValueError):
            store.store_image_caption(invalid, **args)
    with pytest.raises(ValueError, match="No live indexed image"):
        store.store_image_caption("a" * 64, **args)
    with pytest.raises(ValueError, match="timezone"):
        store.store_image_caption(
            media_id, **{**args, "generated_at_utc": "2026-10-14T10:00:00"}
        )
    assert store.conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0] == 0

    video_id = hashlib.sha256(b"video").hexdigest()
    store.upsert_media({
        "media_id": video_id, "path": str(tmp_path / "clip.mp4"),
        "source_name": "caption-test", "rel_path": "clip.mp4",
        "size_bytes": 5, "mime": "video/mp4",
    })
    with pytest.raises(ValueError, match="not an indexed image"):
        store.store_image_caption(video_id, **args)
    assert store.conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0] == 0


def test_failed_upsert_preserves_existing_caption_and_metadata(store, tmp_path):
    image_path, media_id = add_image(store, tmp_path)
    store.store_image_caption(
        media_id, caption="Keep me", model_id="mlx/model",
        prompt_version="caption-v1", generated_at_utc="2026-10-14T10:00:00+00:00",
    )
    store.conn.execute(
        """CREATE TRIGGER reject_caption BEFORE INSERT ON image_caption
           WHEN NEW.model_id = 'mlx/fail'
           BEGIN SELECT RAISE(ABORT, 'injected persistence failure'); END"""
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected persistence failure"):
        store.store_image_caption(
            media_id, caption="Should not persist", model_id="mlx/fail",
            prompt_version="caption-v1", generated_at_utc="2026-10-14T10:01:00+00:00",
        )
    assert store.get_image_caption(media_id, "mlx/model", "caption-v1")["caption"] == "Keep me"
    assert store.conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0] == 1
    assert store.conn.execute("SELECT path FROM media WHERE media_id=?", (media_id,)).fetchone()[0] == str(image_path)


def test_existing_db_migration_only_adds_caption_table(store, tmp_path):
    _, media_id = add_image(store, tmp_path)
    store.upsert_image_embedding(media_id, [0.25, 0.75], model="clip-v1")
    store.store_transcript(
        media_id, model_name="whisper-test", model_revision="r1",
        runtime_version="test", status="transcribed", language="en",
        segments=[{"start": 0.0, "end": 1.0, "text": "existing transcript"}],
    )
    store.set_pipeline_status(media_id, "object_detection", "completed", model_name="detector")
    store.conn.execute("DROP TABLE image_caption")
    store.commit()

    store.init_schema_no_migrations(SCHEMA_PATH)

    assert store.conn.execute("SELECT object_detection_done FROM media WHERE media_id=?", (media_id,)).fetchone()[0] == 1
    assert store.conn.execute("SELECT embedding_model FROM image_embedding WHERE media_id=?", (media_id,)).fetchone()[0] == "clip-v1"
    assert store.conn.execute("SELECT text FROM transcript_segment WHERE media_id=?", (media_id,)).fetchone()[0] == "existing transcript"
    assert store.conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0] == 0


def test_caption_candidates_include_prior_images_and_skip_only_completed(store, tmp_path):
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    _, first_id = add_image(store, tmp_path / "first", b"first")
    _, second_id = add_image(store, tmp_path / "second", b"second")
    store.store_image_caption(
        first_id, caption="Already done", model_id="mlx/model",
        prompt_version="caption-v1", generated_at_utc="2026-10-14T10:00:00+00:00",
    )
    store.conn.execute(
        """INSERT INTO image_caption(
               media_id, caption, model_id, prompt_version, generated_at_utc, status
           ) VALUES (?, 'Failed prior attempt', 'mlx/model', 'caption-v1', '2026-10-14T10:00:00+00:00', 'failed')""",
        (second_id,),
    )
    video_id = hashlib.sha256(b"video-candidate").hexdigest()
    store.upsert_media({
        "media_id": video_id, "path": str(tmp_path / "clip.mp4"),
        "source_name": "caption-test", "rel_path": "clip.mp4",
        "size_bytes": 5, "mime": "video/mp4",
    })

    candidates, total, skipped = store.get_image_caption_candidates("mlx/model", "caption-v1")

    assert total == 2
    assert skipped == 1
    assert [row["media_id"] for row in candidates] == [second_id]


def test_persistence_helper_rejects_missing_or_wrong_database_and_mismatched_image(store, tmp_path):
    image_path, media_id = add_image(store, tmp_path)
    script = import_caption_script()

    missing = tmp_path / "must-not-be-created.sqlite"
    with pytest.raises(FileNotFoundError):
        script._open_caption_store(missing, media_id, image_path)
    assert not missing.exists()

    invalid_db = tmp_path / "not-sqlite.db"
    invalid_db.write_bytes(b"do not modify")
    with pytest.raises(ValueError, match="Not an existing SQLite database"):
        script._open_caption_store(invalid_db, media_id, image_path)
    assert invalid_db.read_bytes() == b"do not modify"

    with pytest.raises(ValueError, match="Invalid media_id"):
        script._open_caption_store(store.path, "not-a-media-id", image_path)

    other_image = tmp_path / "different.jpg"
    other_image.write_bytes(b"different image")
    with pytest.raises(ValueError, match="does not match"):
        script._open_caption_store(store.path, media_id, other_image)
    assert store.conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0] == 0


def test_script_remains_print_only_without_persistence_options(tmp_path, monkeypatch, capsys):
    from PIL import Image
    import huggingface_hub

    image = tmp_path / "image.jpg"
    Image.new("RGB", (2, 2), "white").save(image)
    cache = tmp_path / "cache"
    cache.mkdir()
    script = import_caption_script()
    seen = {}

    def resolve_model(model_id, **kwargs):
        seen.update(model_id=model_id, **kwargs)
        return str(cache / "snapshot")

    class FakeProvider:
        model_load_seconds = 0.1
        generation_seconds = 0.2
        metal_peak_load_bytes = 0
        metal_active_after_load_bytes = 0
        metal_peak_generation_bytes = 0
        metal_active_after_generation_bytes = 0
        closed = []

        def __init__(self, _path):
            pass

        def caption(self, _image, _max_tokens):
            return "A test caption."

        def close(self):
            type(self).closed.append(True)

        def active_metal_memory_bytes(self):
            return 0

    provider = FakeProvider
    monkeypatch.setattr(huggingface_hub, "snapshot_download", resolve_model)
    monkeypatch.setattr(script, "SmolVLM2Provider", provider)
    monkeypatch.setattr(script.importlib.metadata, "version", lambda _name: "test-version")
    monkeypatch.setattr(script, "_rss_bytes", lambda: None)
    monkeypatch.setattr(script, "_system_free_bytes", lambda: None)
    monkeypatch.setattr(script, "_peak_rss_bytes", lambda: 0)
    monkeypatch.setattr(sys, "argv", [
        "caption_image.py", str(image), "--cache-dir", str(cache),
    ])

    assert script.main() == 0
    output = capsys.readouterr().out
    assert "Caption: A test caption." in output
    assert "Persisted:" not in output
    assert seen["model_id"] == script.MODEL_ID
    assert seen["local_files_only"] is True
    assert FakeProvider.closed == [True]


def _add_real_caption_image(store, source_root, filename):
    from PIL import Image

    path = source_root / filename
    Image.new("RGB", (8, 8), "white" if filename == "one.jpg" else "black").save(path)
    media_id = hashlib.sha256(path.read_bytes()).hexdigest()
    store.upsert_media({
        "media_id": media_id, "path": str(path), "source_name": "caption-test",
        "rel_path": filename, "size_bytes": path.stat().st_size, "mime": "image/jpeg",
    })
    return path, media_id


def _run_batch_script(script, store, source_root, cache, monkeypatch, *, stop_file=None):
    args = [
        "caption_image.py", "--all-missing", "--database", str(store.path),
        "--cache-dir", str(cache), "--source-root", str(source_root),
    ]
    if stop_file is not None:
        args.extend(("--stop-file", str(stop_file)))
    monkeypatch.setattr(sys, "argv", args)
    return script.main()


def test_batch_captions_previous_images_once_then_skips_completed(store, tmp_path, monkeypatch, capsys):
    import huggingface_hub

    source_root = tmp_path / "photos"
    source_root.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    _, media_id = _add_real_caption_image(store, source_root, "one.jpg")
    script = import_caption_script()
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *_a, **_kw: str(cache))

    class FakeProvider:
        created = 0
        closed = 0

        def __init__(self, _path):
            type(self).created += 1

        def caption(self, _path, _max_tokens):
            return "A factual caption of the visible scene."

        def close(self):
            type(self).closed += 1

    monkeypatch.setattr(script, "SmolVLM2Provider", FakeProvider)
    assert _run_batch_script(script, store, source_root, cache, monkeypatch) == 0
    first_events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert first_events[-1]["status"] == "complete"
    assert first_events[-1]["generated"] == 1
    assert store.get_image_caption(media_id, script.MODEL_ID, script.PROMPT_VERSION)["caption"].startswith("A factual")
    assert FakeProvider.created == FakeProvider.closed == 1

    def should_not_load(*_args, **_kwargs):
        raise AssertionError("completed captions must skip model loading")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", should_not_load)
    assert _run_batch_script(script, store, source_root, cache, monkeypatch) == 0
    second_events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert second_events[-1]["generated"] == 0
    assert second_events[-1]["skipped"] == 1
    assert FakeProvider.created == FakeProvider.closed == 1


def test_batch_caption_cancellation_finishes_current_image_and_releases_model(store, tmp_path, monkeypatch, capsys):
    import huggingface_hub

    source_root = tmp_path / "photos"
    source_root.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    _add_real_caption_image(store, source_root, "one.jpg")
    _add_real_caption_image(store, source_root, "two.jpg")
    stop_file = tmp_path / "stop"
    script = import_caption_script()
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *_a, **_kw: str(cache))

    class FakeProvider:
        closed = False

        def __init__(self, _path):
            pass

        def caption(self, _path, _max_tokens):
            stop_file.write_text("stop")
            return "Caption completed before stop."

        def close(self):
            type(self).closed = True

    monkeypatch.setattr(script, "SmolVLM2Provider", FakeProvider)
    assert _run_batch_script(script, store, source_root, cache, monkeypatch, stop_file=stop_file) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["status"] == "cancelled"
    assert events[-1]["generated"] == 1
    assert FakeProvider.closed
    assert store.conn.execute("SELECT COUNT(*) FROM image_caption").fetchone()[0] == 1


def test_batch_caption_failure_is_reported_and_releases_model(store, tmp_path, monkeypatch, capsys):
    import huggingface_hub

    source_root = tmp_path / "photos"
    source_root.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    _add_real_caption_image(store, source_root, "one.jpg")
    script = import_caption_script()
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *_a, **_kw: str(cache))

    class FakeProvider:
        closed = False

        def __init__(self, _path):
            pass

        def caption(self, _path, _max_tokens):
            raise RuntimeError("injected failure")

        def close(self):
            type(self).closed = True

    monkeypatch.setattr(script, "SmolVLM2Provider", FakeProvider)
    assert _run_batch_script(script, store, source_root, cache, monkeypatch) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["status"] == "failed"
    assert events[-1]["failed"] == 1
    assert "injected failure" in events[-1]["error"]
    assert FakeProvider.closed


def test_caption_runtime_validation_requires_a_cached_model_and_isolated_python(tmp_path):
    from msa_indexer.captioning import (
        CaptioningError, MODEL_ID, validate_captioning_runtime,
    )

    target = tmp_path / "caption-python-target"
    target.write_text("#!/bin/sh\\nexit 0\\n")
    target.chmod(0o755)
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.symlink_to(target)
    cache = tmp_path / "hub"
    snapshots = cache / f"models--{MODEL_ID.replace('/', '--')}" / "snapshots"
    snapshot = snapshots / "local-revision"
    snapshot.mkdir(parents=True)
    env = {"MSA_CAPTION_PYTHON": str(python), "MSA_CAPTION_CACHE_DIR": str(cache)}

    assert validate_captioning_runtime(env) == (
        python, cache.resolve(), SCRIPT_PATH,
    )
    assert validate_captioning_runtime(env)[0].is_symlink()
    (snapshot / "placeholder").write_text("cached")
    (snapshot / "placeholder").unlink()
    snapshot.rmdir()
    with pytest.raises(CaptioningError, match="will not download"):
        validate_captioning_runtime(env)
    with pytest.raises(CaptioningError, match="MSA_CAPTION_PYTHON"):
        validate_captioning_runtime({})


def test_safe_store_open_does_not_create_missing_database(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        SQLiteStore(missing, create_if_missing=False)
    assert not missing.exists()
