from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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


def test_video_scene_captions_are_keyframe_versioned_retryable_and_incremental(store, tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"indexed video")
    video_id = hashlib.sha256(video_path.read_bytes()).hexdigest()
    store.upsert_media({
        "media_id": video_id, "path": str(video_path),
        "source_name": "caption-test", "rel_path": video_path.name,
        "size_bytes": video_path.stat().st_size, "mime": "video/mp4",
    })
    store.add_keyframes(video_id, [
        {"shot_index": 0, "kf_index": 0, "timestamp": 2.5, "shot_start": 0, "shot_end": 5},
        {"shot_index": 1, "kf_index": 0, "timestamp": 7.5, "shot_start": 5, "shot_end": 10},
    ])
    first_id = store.get_keyframe_id(video_id, 0, 0)
    second_id = store.get_keyframe_id(video_id, 1, 0)
    assert first_id and second_id

    store.store_video_scene_caption(
        video_id, first_id, 2.5, caption="A person stands beside a blue car.",
        model_id="mlx/model-a", prompt_version="scene-v1",
        generated_at_utc="2026-10-14T10:00:00+00:00",
    )
    store.store_video_scene_caption(
        video_id, first_id, 2.5, caption="A person is next to a blue car.",
        model_id="mlx/model-b", prompt_version="scene-v1",
        generated_at_utc="2026-10-14T10:01:00+00:00",
    )
    store.store_video_scene_caption(
        video_id, second_id, 7.5, caption=None,
        model_id="mlx/model-a", prompt_version="scene-v1",
        generated_at_utc="2026-10-14T10:02:00+00:00", status="failed",
    )

    candidates, total, skipped = store.get_video_scene_caption_candidates("mlx/model-a", "scene-v1")
    assert total == 2 and skipped == 1
    assert [row["keyframe_id"] for row in candidates] == [second_id]
    assert store.get_video_scene_caption_candidates("mlx/model-a", "scene-v2")[2] == 0

    store.store_video_scene_caption(
        video_id, second_id, 7.5, caption="A person opens the car door.",
        model_id="mlx/model-a", prompt_version="scene-v1",
        generated_at_utc="2026-10-14T10:03:00+00:00",
    )
    rows = store.conn.execute(
        "SELECT keyframe_id, timestamp, caption, model_id, prompt_version, status "
        "FROM video_scene_caption ORDER BY keyframe_id, model_id"
    ).fetchall()
    assert len(rows) == 3
    assert rows[-1] == (second_id, 7.5, "A person opens the car door.", "mlx/model-a", "scene-v1", "completed")
    with pytest.raises(ValueError, match="timestamp"):
        store.store_video_scene_caption(
            video_id, first_id, 9.0, caption="Wrong frame.", model_id="mlx/model-a",
            prompt_version="scene-v1", generated_at_utc="2026-10-14T10:04:00+00:00",
        )


def test_video_scene_worker_reuses_one_provider_and_skips_completed_keyframes(store, tmp_path, monkeypatch, capsys):
    import huggingface_hub
    from PIL import Image

    source_root = tmp_path / "videos"
    source_root.mkdir()
    video_path = source_root / "clip.mp4"
    video_path.write_bytes(b"indexed video")
    video_id = hashlib.sha256(video_path.read_bytes()).hexdigest()
    store.upsert_media({
        "media_id": video_id, "path": str(video_path),
        "source_name": "caption-test", "rel_path": video_path.name,
        "size_bytes": video_path.stat().st_size, "mime": "video/mp4",
    })
    from msa_indexer.io.video_frames import FRAME_RENDITION_PROFILE, make_frame_id

    frame_id = make_frame_id(video_id, 0, 2500, 1, 1000, None)
    rendition_id = hashlib.sha256(
        f"{frame_id}\\0{FRAME_RENDITION_PROFILE}".encode()
    ).hexdigest()
    frame_cache_dir = tmp_path / "video-frame-cache"
    cached_image = frame_cache_dir / frame_id[:2] / f"{rendition_id}.jpg"
    cached_image.parent.mkdir(parents=True)
    Image.new("RGB", (4, 4), "white").save(cached_image, format="JPEG", quality=90)
    with cached_image.open("rb") as cached_file:
        cached_checksum = hashlib.file_digest(cached_file, "sha256").hexdigest()
    store.upsert_video_frame({
        "frame_id": frame_id, "video_id": video_id, "source_revision": video_id,
        "stream_index": 0, "pts": 2500, "time_base_num": 1, "time_base_den": 1000,
        "frame_ordinal": None, "actual_timestamp": 2.5, "frame_id_version": 1,
    })
    store.upsert_video_frame_rendition({
        "rendition_id": rendition_id, "frame_id": frame_id,
        "profile": FRAME_RENDITION_PROFILE,
        "cache_relpath": f"{frame_id[:2]}/{rendition_id}.jpg",
        "checksum_sha256": cached_checksum, "size_bytes": cached_image.stat().st_size,
        "width": 4, "height": 4, "rotation_degrees": 0,
    })
    store.add_keyframes(video_id, [
        {"shot_index": 0, "kf_index": 0, "timestamp": 2.5, "frame_id": frame_id, "shot_start": 0, "shot_end": 5},
        {"shot_index": 1, "kf_index": 0, "timestamp": 7.5, "shot_start": 5, "shot_end": 10},
    ])
    store.commit()
    cache = tmp_path / "cache"
    cache.mkdir()
    script = import_caption_script()
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *_a, **_kw: str(cache))
    seen = []

    class FakeProvider:
        loads = 0
        def __init__(self, _path):
            type(self).loads += 1
        def caption(self, _image, _max_tokens, prompt):
            seen.append(prompt)
            return f"Visible scene {len(seen)}."
        def close(self):
            pass

    monkeypatch.setattr(script, "BlipCaptionProvider", FakeProvider)
    import msa_indexer.io.video as video
    fallback_times = []
    monkeypatch.setattr(
        video, "extract_frame_at_timestamp",
        lambda _path, timestamp: (fallback_times.append(timestamp) or Image.new("RGB", (4, 4), "white")),
    )
    args = SimpleNamespace(
        database=store.path, source_root=[source_root], cache_dir=cache,
        frame_cache_dir=frame_cache_dir, stop_file=None, video_id=[video_id], max_tokens=80,
    )

    assert script._caption_video_scenes(args) == 0
    rows = store.conn.execute(
        "SELECT timestamp, caption, status FROM video_scene_caption ORDER BY timestamp"
    ).fetchall()
    assert rows == [(2.5, "Visible scene 1.", "completed"), (7.5, "Visible scene 2.", "completed")]
    assert len(set(seen)) == 1 and seen[0] == "a video frame showing"
    assert FakeProvider.loads == 1
    assert fallback_times == [7.5]

    assert script._caption_video_scenes(args) == 0
    assert FakeProvider.loads == 1
    assert '"generated":0' in capsys.readouterr().out

    stop_file = tmp_path / "stop-captioning"
    stop_file.write_text("stop")
    args.stop_file = stop_file
    assert script._caption_video_scenes(args) == 0
    assert FakeProvider.loads == 1
    assert '"status":"cancelled"' in capsys.readouterr().out


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


def test_blip_caption_provider_uses_cpu_and_only_local_weights(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from PIL import Image
    script = import_caption_script()
    BlipCaptionProvider = script.BlipCaptionProvider

    calls = {}

    class Processor:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls["processor_load"] = (path, kwargs)
            return cls()

        def __call__(self, image, *, text, return_tensors):
            calls["seed"] = text
            return {"pixel_values": image.size}

        def decode(self, _output, *, skip_special_tokens):
            return "a photograph of a red car"

    class Model:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            calls["model_load"] = (path, kwargs)
            return cls()

        def to(self, device):
            calls["device"] = device
            return self

        def eval(self):
            return self

        def generate(self, **kwargs):
            calls["generation"] = kwargs
            return [1]

    import sys
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        BlipProcessor=Processor, BlipForConditionalGeneration=Model,
    ))
    image_path = tmp_path / "frame.jpg"
    Image.new("RGB", (4, 3), "white").save(image_path)

    provider = BlipCaptionProvider(tmp_path / "snapshot")
    caption = provider.caption(image_path, 32)
    provider.close()

    assert caption == "a photograph of a red car"
    assert calls["seed"] == script.PROMPT
    assert calls["device"] == "cpu"
    assert calls["processor_load"][1] == {"local_files_only": True, "trust_remote_code": False}
    assert calls["model_load"][1]["local_files_only"] is True
    assert calls["model_load"][1]["use_safetensors"] is False
    assert calls["generation"]["max_new_tokens"] == 32


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

    provider = FakeProvider
    monkeypatch.setattr(huggingface_hub, "snapshot_download", resolve_model)
    monkeypatch.setattr(script, "BlipCaptionProvider", provider)
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

    monkeypatch.setattr(script, "BlipCaptionProvider", FakeProvider)
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

    monkeypatch.setattr(script, "BlipCaptionProvider", FakeProvider)
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

    monkeypatch.setattr(script, "BlipCaptionProvider", FakeProvider)
    assert _run_batch_script(script, store, source_root, cache, monkeypatch) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]["status"] == "failed"
    assert events[-1]["failed"] == 1
    assert "injected failure" in events[-1]["error"]
    assert FakeProvider.closed


def test_caption_worker_does_not_inherit_parent_python_launcher(store, tmp_path, monkeypatch):
    import io
    import threading
    from msa_indexer import captioning

    media_root = tmp_path / "media"
    media_root.mkdir()
    cache = tmp_path / "hub"
    snapshot = cache / f"models--{captioning.MODEL_ID.replace('/', '--')}" / "snapshots" / captioning.MODEL_REVISION
    snapshot.mkdir(parents=True)
    for name in captioning.MODEL_REQUIRED_FILES:
        (snapshot / name).write_text("cached")
    monkeypatch.setenv("MSA_CAPTION_PYTHON", sys.executable)
    monkeypatch.setenv("MSA_CAPTION_CACHE_DIR", str(cache))
    monkeypatch.setenv("__PYVENV_LAUNCHER__", "/protected-app/python")
    captured = {}
    output = "\n".join(json.dumps(event) for event in [
        {"event": "started", "status": "running", "total": 0},
        {"event": "summary", "status": "complete", "total": 0, "generated": 0, "skipped": 0, "failed": 0},
    ]) + "\n"

    class FakeProcess:
        stdout = io.StringIO(output)
        def poll(self): return 0
        def wait(self): return 0

    def fake_popen(_command, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(captioning.subprocess, "Popen", fake_popen)
    config = SimpleNamespace(
        sqlite_path=store.path, media_source_override=None,
        media_sources=[SimpleNamespace(enabled=True, path=str(media_root))],
    )
    result = captioning.run_video_scene_captioning_worker(config, threading.Event(), lambda _event: None)

    assert result["status"] == "complete"
    assert "__PYVENV_LAUNCHER__" not in captured["env"]


def test_caption_runtime_validation_requires_a_cached_model_and_isolated_python(tmp_path):
    from msa_indexer.captioning import (
        CaptioningError, MODEL_ID, MODEL_REVISION, validate_captioning_runtime,
    )

    target = tmp_path / "caption-python-target"
    target.write_text("#!/bin/sh\\nexit 0\\n")
    target.chmod(0o755)
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.symlink_to(target)
    cache = tmp_path / "hub"
    snapshot = cache / f"models--{MODEL_ID.replace('/', '--')}" / "snapshots" / MODEL_REVISION
    snapshot.mkdir(parents=True)
    from msa_indexer.captioning import MODEL_REQUIRED_FILES
    for name in MODEL_REQUIRED_FILES:
        (snapshot / name).write_text("cached")
    env = {"MSA_CAPTION_PYTHON": str(python), "MSA_CAPTION_CACHE_DIR": str(cache)}

    assert validate_captioning_runtime(env) == (
        python, cache.resolve(), SCRIPT_PATH,
    )
    assert validate_captioning_runtime(env)[0].is_symlink()
    (snapshot / "pytorch_model.bin").unlink()
    with pytest.raises(CaptioningError, match="will not download"):
        validate_captioning_runtime(env)
    with pytest.raises(CaptioningError, match="configured local model directory"):
        validate_captioning_runtime({})


def test_safe_store_open_does_not_create_missing_database(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        SQLiteStore(missing, create_if_missing=False)
    assert not missing.exists()
