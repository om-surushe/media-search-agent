"""Temporary index execution shared by isolated Workbench previews."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
import shutil
import socket
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from msa_indexer.db.sqlite_store import SQLiteStore
from msa_indexer.pipeline import run_index
from msa_indexer.models.clip_artifacts import (
    CLIP_CHECKPOINT_SHA256,
    CLIP_HF_REPO,
    CLIP_MODEL_NAME,
    CLIP_PRETRAINED,
    clip_checkpoint_candidates,
)
from msa_indexer.io.scanner import IMAGE_EXT, VIDEO_EXT, ScanStats, iter_media_entries
from msa_settings.paths import resolve_for_access
from .adapter_01_discovery import validated_sample_path


def _clip_checkpoint(config) -> tuple[Path | None, str | None]:
    if importlib.util.find_spec("open_clip") is None:
        return None, "open_clip is not installed."
    try:
        import open_clip
        model_name = getattr(config, "model_name", "ViT-L-14")
        pretrained_name = getattr(config, "pretrained", "openai")
        pretrained = open_clip.get_pretrained_cfg(model_name, pretrained_name)
    except Exception:
        return None, "Configured CLIP model/pretrained pair is unavailable."
    if model_name != CLIP_MODEL_NAME or pretrained_name != CLIP_PRETRAINED:
        return None, "Workbench currently supports only the managed ViT-L-14/openai checkpoint."
    hf_repo = str(pretrained.get("hf_hub", "")).rstrip("/") if pretrained else ""
    if hf_repo != CLIP_HF_REPO:
        return None, "Configured CLIP checkpoint is not in the managed local model catalog."

    models_dir = Path(getattr(config, "models_dir", "models"))
    clip_cache = models_dir / "clip"
    hub_cache = clip_cache / f"models--{CLIP_HF_REPO.replace('/', '--')}"
    candidates = clip_checkpoint_candidates(models_dir)
    for checkpoint in candidates:
        # Hub checkpoints must belong to the configured repo; direct .pt is
        # accepted as a platform fallback only in the managed cache root.
        if checkpoint.name == "ViT-L-14.pt":
            if checkpoint.parent != clip_cache:
                continue
        elif hub_cache not in checkpoint.parents:
            continue
        expected_sha256 = CLIP_CHECKPOINT_SHA256.get(checkpoint.name)
        digest = hashlib.sha256()
        with checkpoint.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual == expected_sha256 or (expected_sha256 is None and actual in CLIP_CHECKPOINT_SHA256.values()):
            return checkpoint, None
    return None, "Managed CLIP weights are not cached with a valid checksum; start model setup first."


def _optional_model_capability(config, *, force_object_detection: bool = False) -> str | None:
    from msa_indexer.pipeline import _object_detection_enabled

    models_dir = Path(getattr(config, "models_dir", "models"))
    if force_object_detection or _object_detection_enabled(config):
        if getattr(config, "object_detector_backend", "rtdetr") != "rtdetr":

            return "Workbench object detection supports only the RT-DETR cache layout."
        try:
            from msa_indexer.models._detection_backends._rtdetr import KNOWN_REVISIONS, RtDetrBackend
            if not RtDetrBackend._is_cached(
                getattr(config, "object_model", "PekingU/rtdetr_r18vd"), str(models_dir / "rtdetr"),
                KNOWN_REVISIONS.get(getattr(config, "object_model", "PekingU/rtdetr_r18vd")),
            ):
                return "Configured RT-DETR weights are not cached; no download was attempted."
        except Exception:
            return "RT-DETR runtime is unavailable."
    if getattr(config, "enable_face_recognition", False):
        if getattr(config, "face_recognizer_backend", "facenet_pytorch") != "facenet_pytorch":
            return "Workbench face inference supports only the local FaceNet cache layout."
        checkpoints = models_dir / "facenet_pytorch" / "checkpoints"
        model = getattr(config, "face_model", "vggface2")
        if not any(checkpoints.glob(f"*{model}*.pt")):
            return "Configured FaceNet weights are not cached; no download was attempted."
        if importlib.util.find_spec("facenet_pytorch") is None:
            return "facenet-pytorch is not installed."
    return None


def index_capability(
    config, *, force_object_detection: bool = False,
) -> dict[str, bool | str | None]:
    """Report cache/runtime availability without constructing model loaders."""
    checkpoint, reason = _clip_checkpoint(config)
    if reason:
        return {"available": False, "reason": reason}
    reason = _optional_model_capability(config, force_object_detection=force_object_detection)
    if reason:
        return {"available": False, "reason": reason}
    return {"available": True, "reason": None}


def _copy_model_cache(
    config, target: Path, checkpoint: Path, *, force_object_detection: bool = False,
    include_object_detection: bool | None = None,
) -> Path:
    from msa_indexer.pipeline import _object_detection_enabled

    target.mkdir(parents=True, exist_ok=True)
    clip_target = target / "clip"
    clip_target.mkdir()
    local_checkpoint = clip_target / checkpoint.name
    shutil.copyfile(checkpoint, local_checkpoint)
    source_models = Path(getattr(config, "models_dir", "models"))
    copy_detector = force_object_detection or (
        _object_detection_enabled(config) if include_object_detection is None else include_object_detection
    )
    if copy_detector:
        shutil.copytree(source_models / "rtdetr", target / "rtdetr")
    if getattr(config, "enable_face_recognition", False):
        shutil.copytree(source_models / "facenet_pytorch", target / "facenet_pytorch")
    return local_checkpoint


@contextmanager
def _offline_model_runtime(model_cache: Path):
    """Fail closed if any model loader attempts network access during a preview."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    environ = os.environ
    original_environment = {
        key: environ.get(key)
        for key in ("TORCH_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    }
    torch = sys.modules.get("torch")
    original_torch_hub_dir = torch.hub.get_dir() if torch is not None else None
    environ["TORCH_HOME"] = str(model_cache / "facenet_pytorch")
    environ["HF_HUB_OFFLINE"] = "1"
    environ["TRANSFORMERS_OFFLINE"] = "1"

    def deny_network(*_args, **_kwargs):
        raise RuntimeError("Workbench model loading is offline; network access is blocked.")

    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        for key, value in original_environment.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        if torch is not None and original_torch_hub_dir is not None:
            torch.hub.set_dir(original_torch_hub_dir)


def _run_staged_source(
    config, source, workspace: Path, staged_root: Path, checkpoint: Path,
    *, result_limit: int, after_index=None, force_object_detection: bool = False,
    include_object_detection: bool | None = None, after_source=None,
) -> tuple[int, int, dict, list[dict]]:
    model_cache = workspace / "models"
    local_checkpoint = _copy_model_cache(
        config, model_cache, checkpoint, force_object_detection=force_object_detection,
        include_object_detection=include_object_detection,
    )
    isolated = copy.copy(config)
    isolated.media_sources = [type(source)(name=source.name, path=str(staged_root), enabled=True)]
    isolated.media_source_override = None
    isolated.index_dir = workspace / "index"
    isolated.sqlite_path = isolated.index_dir / "media.sqlite"
    isolated.faiss_path = isolated.index_dir / "image_vec.faiss"
    isolated.face_faiss_path = isolated.index_dir / "face_vec.faiss"
    isolated.thumb_dir = workspace / "thumbnails"
    isolated.face_thumb_dir = workspace / "face-thumbnails"
    isolated.models_dir = model_cache
    isolated.pretrained = str(local_checkpoint)
    if force_object_detection:
        isolated.object_detection_override = True
    isolated.video_frame_cache_dir = workspace / "video-frames"
    isolated.qdrant_path = workspace / "qdrant"
    isolated.log_dir = workspace / "logs"
    isolated.enable_speech_transcription = False
    isolated.image_captions_enabled = False
    isolated.video_scene_captions_enabled = False
    isolated.export_to_qdrant = False
    isolated.index_dir.mkdir(parents=True)

    with _offline_model_runtime(model_cache):
        run_index(isolated, stop_after_local_finalize=True)
    db = SQLiteStore(isolated.sqlite_path)
    try:
        total = db.conn.execute(
            "SELECT COUNT(*) FROM media WHERE source_name=? AND deleted=0", (source.name,),
        ).fetchone()[0]
        embedding_count = db.conn.execute(
            "SELECT COUNT(*) FROM image_embedding e JOIN media m ON m.media_id=e.media_id "
            "WHERE m.source_name=? AND m.deleted=0", (source.name,),
        ).fetchone()[0]
        summary = {
            "shots": int(db.conn.execute(
                "SELECT COUNT(*) FROM shots s JOIN media m ON m.media_id=s.video_id "
                "WHERE m.source_name=? AND m.deleted=0", (source.name,),
            ).fetchone()[0]),
            "video_keyframes": int(db.conn.execute(
                "SELECT COUNT(*) FROM video_keyframes vk JOIN media m ON m.media_id=vk.video_id "
                "WHERE m.source_name=? AND m.deleted=0", (source.name,),
            ).fetchone()[0]),
            "embedded_keyframes": int(db.conn.execute(
                "SELECT COUNT(*) FROM keyframe_embedding ke JOIN video_keyframes vk "
                "ON vk.id=ke.keyframe_id JOIN media m ON m.media_id=vk.video_id "
                "WHERE m.source_name=? AND m.deleted=0 AND ke.embedding IS NOT NULL", (source.name,),
            ).fetchone()[0]),
            "videos_with_keyframes": int(db.conn.execute(
                "SELECT COUNT(DISTINCT vk.video_id) FROM video_keyframes vk "
                "JOIN media m ON m.media_id=vk.video_id WHERE m.source_name=? AND m.deleted=0",
                (source.name,),
            ).fetchone()[0]),
        }
        cache_row = db.conn.execute(
            "SELECT COUNT(DISTINCT vf.frame_id), COUNT(DISTINCT vfr.rendition_id) "
            "FROM video_frame vf JOIN media m ON m.media_id=vf.video_id "
            "LEFT JOIN video_frame_rendition vfr ON vfr.frame_id=vf.frame_id "
            "WHERE m.source_name=? AND m.deleted=0", (source.name,),
        ).fetchone()
        summary["decoded_frames"] = int(cache_row[0])
        summary["cached_renditions"] = int(cache_row[1])
        summary["selection_statuses"] = dict(db.conn.execute(
            "SELECT state.status, COUNT(DISTINCT state.video_id) "
            "FROM video_keyframe_selection_state state JOIN media m ON m.media_id=state.video_id "
            "WHERE m.source_name=? AND m.deleted=0 GROUP BY state.status", (source.name,),
        ).fetchall())
        if after_source is not None:
            summary.update(after_source(db, isolated, workspace))
        rows = db.conn.execute(
            "SELECT media_id, rel_path FROM media WHERE source_name=? AND deleted=0 "
            "ORDER BY rel_path LIMIT ?", (source.name, result_limit),
        ).fetchall()
        results = []
        for media_id, relative_path in rows:
            result = _read_result(db, source.name, relative_path, media_id)
            if after_index is not None:
                result.update(after_index(db, isolated, workspace, media_id))
            results.append(result)
        return int(total), int(embedding_count), summary, results
    finally:
        db.close()


def run_one_file(
    config, source, relative_path: str, *, expected_type: str = "any", after_index=None,
    force_object_detection: bool = False,
) -> dict:
    """Run the existing index coordinator in a temporary source/index/cache tree."""
    root, original = validated_sample_path(source, relative_path)
    allowed = IMAGE_EXT if expected_type == "image" else VIDEO_EXT if expected_type == "video" else IMAGE_EXT | VIDEO_EXT
    if original.suffix.lower() not in allowed:
        raise ValueError(f"This stage requires a {expected_type} file")
    if original.stat().st_size > 2 * 1024 * 1024 * 1024:
        raise ValueError("Selected media exceeds the 2 GiB workbench limit")
    capability = index_capability(config, force_object_detection=force_object_detection)
    if not capability["available"]:
        raise RuntimeError(str(capability["reason"]))
    checkpoint, reason = _clip_checkpoint(config)
    if checkpoint is None:
        raise RuntimeError(reason or "Configured CLIP checkpoint is unavailable")

    with tempfile.TemporaryDirectory(prefix="msa-adapter-workbench-") as temp_dir:
        workspace = Path(temp_dir)
        staged_root = workspace / "source"
        staged_file = staged_root / original.relative_to(root)
        staged_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, staged_file)
        total, _embeddings, _summary, results = _run_staged_source(
            config, source, workspace, staged_root, checkpoint,
            result_limit=1, after_index=after_index,
            force_object_detection=force_object_detection,
        )
        if total != 1 or not results:
            raise RuntimeError("Selected file did not produce an indexed media row")
        return results[0]


def run_image_folder(config, source, *, result_limit: int = 25, after_index=None) -> dict:
    """Index all source images once in a disposable copy; return bounded details."""
    if not 1 <= result_limit <= 25:
        raise ValueError("Result limit must be between 1 and 25")
    capability = index_capability(config, force_object_detection=True)
    if not capability["available"]:
        raise RuntimeError(str(capability["reason"]))
    checkpoint, reason = _clip_checkpoint(config)
    if checkpoint is None:
        raise RuntimeError(reason or "Configured CLIP checkpoint is unavailable")

    root = Path(resolve_for_access(str(source.path))).resolve()
    if not root.is_dir():
        raise ValueError("Configured source is not an accessible directory")
    with tempfile.TemporaryDirectory(prefix="msa-adapter-workbench-") as temp_dir:
        workspace = Path(temp_dir)
        staged_root = workspace / "source"
        stats = ScanStats()
        images_found = 0
        for original, stat in iter_media_entries(root, media_type="image", stats=stats):
            relative = original.relative_to(root)
            if stat.st_size > 2 * 1024 * 1024 * 1024:
                raise ValueError("An image exceeds the 2 GiB workbench limit")
            _, safe_original = validated_sample_path(source, relative.as_posix())
            staged_file = staged_root / relative
            staged_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(safe_original, staged_file)
            except OSError as exc:
                raise RuntimeError("Could not stage every image from the configured source") from exc
            images_found += 1
        if stats.walk_errors:
            raise RuntimeError("Could not scan the configured source completely; preview was not run")
        if images_found == 0:
            return {
                "scope": "whole_configured_source_images", "images_found": 0,
                "images_processed": 0, "image_embeddings": 0,
                "images_without_embedding": 0, "complete": True,
                "results": [], "results_truncated": False, "persisted": False,
            }
        processed, embeddings, _summary, results = _run_staged_source(
            config, source, workspace, staged_root, checkpoint,
            result_limit=result_limit, after_index=after_index,
            force_object_detection=True,
        )
        return {
            "scope": "whole_configured_source_images",
            "images_found": images_found,
            "images_processed": processed,
            "image_embeddings": embeddings,
            "images_without_embedding": max(0, images_found - embeddings),
            "complete": processed == images_found and embeddings == images_found,
            "results": results,
            "results_truncated": images_found > len(results),
            "persisted": False,
        }


def run_video_folder(config, source, *, result_limit: int = 25, after_index=None) -> dict:
    """Process every configured-source video once in disposable index/cache state."""
    if not 1 <= result_limit <= 25:
        raise ValueError("Result limit must be between 1 and 25")
    stage_config = copy.copy(config)
    stage_config.enable_object_detection = True
    stage_config.enable_video_object_detection = True
    stage_config.enable_face_recognition = True
    stage_config.object_detection_override = True
    capability = index_capability(stage_config, force_object_detection=True)
    if not capability["available"]:
        raise RuntimeError(str(capability["reason"]))
    checkpoint, reason = _clip_checkpoint(config)
    if checkpoint is None:
        raise RuntimeError(reason or "Configured CLIP checkpoint is unavailable")

    root = Path(resolve_for_access(str(source.path))).resolve()
    if not root.is_dir():
        raise ValueError("Configured source is not an accessible directory")
    with tempfile.TemporaryDirectory(prefix="msa-adapter-workbench-") as temp_dir:
        workspace = Path(temp_dir)
        staged_root = workspace / "source"
        stats = ScanStats()
        videos_found = 0
        for original, stat in iter_media_entries(root, media_type="video", stats=stats):
            relative = original.relative_to(root)
            if stat.st_size > 2 * 1024 * 1024 * 1024:
                raise ValueError("A video exceeds the 2 GiB workbench limit")
            _, safe_original = validated_sample_path(source, relative.as_posix())
            staged_file = staged_root / relative
            staged_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(safe_original, staged_file)
            except OSError as exc:
                raise RuntimeError("Could not stage every video from the configured source") from exc
            videos_found += 1
        if stats.walk_errors:
            raise RuntimeError("Could not scan the configured source completely; preview was not run")
        if videos_found == 0:
            return {
                "scope": "whole_configured_source_videos", "videos_found": 0,
                "videos_processed": 0, "complete": True, "video_keyframes": {},
                "results": [], "results_truncated": False, "persisted": False,
            }
        processed, _image_embeddings, summary, results = _run_staged_source(
            stage_config, source, workspace, staged_root, checkpoint,
            result_limit=result_limit, after_index=after_index,
            force_object_detection=True, include_object_detection=True,
        )
        return {
            "scope": "whole_configured_source_videos",
            "videos_found": videos_found,
            "videos_processed": processed,
            "complete": processed == videos_found,
            "video_keyframes": summary,
            "results": results,
            "results_truncated": videos_found > len(results),
            "persisted": False,
        }


def run_source_folder(
    config, source, *, result_limit: int = 25, after_source=None, after_index=None,
) -> dict:
    """Run the complete local index pipeline for every supported source media item in disposable state."""
    if not 1 <= result_limit <= 25:
        raise ValueError("Result limit must be between 1 and 25")
    capability = index_capability(config)
    if not capability["available"]:
        raise RuntimeError(str(capability["reason"]))
    checkpoint, reason = _clip_checkpoint(config)
    if checkpoint is None:
        raise RuntimeError(reason or "Configured CLIP checkpoint is unavailable")

    root = Path(resolve_for_access(str(source.path))).resolve()
    if not root.is_dir():
        raise ValueError("Configured source is not an accessible directory")
    with tempfile.TemporaryDirectory(prefix="msa-adapter-workbench-") as temp_dir:
        workspace = Path(temp_dir)
        staged_root = workspace / "source"
        stats = ScanStats()
        files_found = 0
        for original, stat in iter_media_entries(root, stats=stats):
            relative = original.relative_to(root)
            if stat.st_size > 2 * 1024 * 1024 * 1024:
                raise ValueError("A media file exceeds the 2 GiB workbench limit")
            _, safe_original = validated_sample_path(source, relative.as_posix())
            staged_file = staged_root / relative
            staged_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(safe_original, staged_file)
            except OSError as exc:
                raise RuntimeError("Could not stage every supported media file from the configured source") from exc
            files_found += 1
        if stats.walk_errors:
            raise RuntimeError("Could not scan the configured source completely; preview was not run")
        if files_found == 0:
            return {
                "scope": "whole_configured_source", "media_found": 0, "media_processed": 0,
                "image_embeddings": 0, "summary": {}, "results": [],
                "results_truncated": False, "complete": True, "persisted": False,
            }
        processed, embeddings, summary, results = _run_staged_source(
            config, source, workspace, staged_root, checkpoint,
            result_limit=result_limit, after_source=after_source, after_index=after_index,
        )
        return {
            "scope": "whole_configured_source", "media_found": files_found,
            "media_processed": processed, "image_embeddings": embeddings,
            "summary": summary, "results": results,
            "results_truncated": files_found > len(results),
            "complete": processed == files_found, "persisted": False,
        }


def _read_result(db: SQLiteStore, source_name: str, relative_path: str, media_id: str) -> dict:
    row = db.conn.execute(
        "SELECT mime, width, height, duration, gps_lat, gps_lon FROM media WHERE media_id=?",
        (media_id,),
    ).fetchone()
    statuses = {
        item[0]: item[1]
        for item in db.conn.execute(
            "SELECT pipeline, status FROM media_pipeline_status WHERE media_id=?", (media_id,),
        ).fetchall()
    }
    state = db.get_index_state()
    return {
        "source": source_name,
        "relative_path": relative_path,
        "media_id": media_id,
        "metadata": {
            "mime": row[0], "width": row[1], "height": row[2], "duration": row[3],
            "gps_lat": row[4], "gps_lon": row[5],
        },
        "statuses": statuses,
        "finalization": {
            "index_version_seq": state.get("index_version_seq", 0),
            "committed": True,
        },
        "persisted": False,
    }
