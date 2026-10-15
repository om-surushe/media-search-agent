"""Stage 08: export a disposable source preview into a temporary Qdrant store."""
from __future__ import annotations

import importlib.util

from ._workbench_sandbox import index_capability, run_one_file, run_source_folder


def qdrant_export_capability(config) -> dict[str, bool | str | None]:
    if importlib.util.find_spec("qdrant_client") is None:
        return {"available": False, "reason": "qdrant-client is not installed.", "can_prepare": False}
    capability = index_capability(config)
    if capability["available"]:
        return {"available": True, "reason": None, "can_prepare": False}
    reason = str(capability["reason"] or "")
    can_prepare = "weights are not cached" in reason or "not cached with a valid checksum" in reason
    return {**capability, "can_prepare": can_prepare}


def _export_disposable_store(db, isolated, workspace) -> dict:
    from msa_indexer.db.qdrant_export import (
        delete_tombstoned_points_from_qdrant,
        export_faces_to_qdrant,
        export_images_to_qdrant,
        export_video_frames_to_qdrant,
        get_qdrant_export_version,
        record_qdrant_export_version,
    )

    qdrant_path = workspace / "qdrant-preview"
    image = export_images_to_qdrant(
        isolated.sqlite_path, recreate=True, qdrant_path=qdrant_path,
    )
    video = export_video_frames_to_qdrant(
        isolated.sqlite_path, collection="video_emb", recreate=True,
        qdrant_path=qdrant_path,
    )
    faces = export_faces_to_qdrant(
        isolated.sqlite_path, collection="face_emb", recreate=True,
        qdrant_path=qdrant_path,
    )
    deleted = delete_tombstoned_points_from_qdrant(
        isolated.sqlite_path, image_collection=None, video_collection="video_emb",
        face_collection="face_emb", qdrant_path=qdrant_path,
    )
    errors = int(image.get("errors", 0)) + int(video.get("errors", 0)) + int(faces.get("errors", 0))
    sent = int(image.get("sent", 0)) + int(video.get("sent", 0)) + int(faces.get("sent", 0))
    version_recorded = errors == 0 and sent > 0
    if version_recorded:
        state = db.get_index_state()
        record_qdrant_export_version(
            int(state.get("index_version_seq") or 0),
            state.get("index_version_ts"), qdrant_path=qdrant_path,
        )
    return {
        "image": image, "video": video, "faces": faces,
        "deletions": deleted, "version_recorded": version_recorded,
        "export_version": get_qdrant_export_version(qdrant_path=qdrant_path),
        "store": "disposable", "persisted": False,
    }


def preview_qdrant_export_folder(config, source, result_limit: int = 25) -> dict:
    """Index every supported source item and export all resulting vectors locally."""
    return run_source_folder(
        config, source, result_limit=result_limit,
        after_source=lambda db, isolated, workspace: {
            "qdrant_export": _export_disposable_store(db, isolated, workspace),
        },
    )


def preview_qdrant_export(config, source, relative_path: str) -> dict:
    """Legacy internal single-file preview; the Workbench uses whole-source runs."""
    return run_one_file(
        config, source, relative_path,
        after_index=lambda db, isolated, workspace, _media_id: {
            "qdrant_export": _export_disposable_store(db, isolated, workspace),
        },
    )
