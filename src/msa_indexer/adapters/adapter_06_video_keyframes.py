"""Stage 06: complete isolated video shot/keyframe processing and enrichment."""
from __future__ import annotations

import json

from ._workbench_sandbox import run_video_folder, run_one_file


def _tags(value) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(tag)[:120] for tag in parsed[:30] if isinstance(tag, str)] if isinstance(parsed, list) else []


def video_keyframe_capability(config) -> dict[str, bool | str | None]:
    from copy import copy
    from ._workbench_sandbox import index_capability

    capability_config = copy(config)
    capability_config.enable_object_detection = True
    capability_config.enable_video_object_detection = True
    capability_config.enable_face_recognition = True
    capability_config.object_detection_override = True
    capability = index_capability(capability_config, force_object_detection=True)
    if not capability["available"]:
        return capability
    if getattr(config, "enable_video_shot_detection", False):
        try:
            from msa_indexer.io.shot_detection import ContentDetector
        except Exception:
            ContentDetector = None
        if ContentDetector is None:
            return {"available": False, "reason": "PySceneDetect/OpenCV shot detector is unavailable."}
    return capability


def _inspect_video_keyframes(db, _isolated, _workspace, media_id):
    shots = db.get_shots_for_video(media_id)
    keyframes = db.conn.execute(
        "SELECT shot_index, kf_index, timestamp, gps_lat, gps_lon, gps_alt, gps_source, "
        "frame_id, selection_version, tags, "
        "(SELECT COUNT(*) FROM face f WHERE f.media_id=video_id "
        "AND f.shot_index=video_keyframes.shot_index AND f.kf_index=video_keyframes.kf_index) "
        "FROM video_keyframes WHERE video_id=? ORDER BY shot_index, kf_index LIMIT 100",
        (media_id,),
    ).fetchall()
    face_rows = []
    if keyframes:
        frame_pairs = [(row[0], row[1]) for row in keyframes]
        pair_clause = " OR ".join("(shot_index=? AND kf_index=?)" for _ in frame_pairs)
        params = [media_id, *(value for pair in frame_pairs for value in pair)]
        face_rows = db.conn.execute(
            "SELECT shot_index, kf_index, x, y, w, h, confidence FROM face "
            f"WHERE media_id=? AND ({pair_clause}) "
            "ORDER BY shot_index, kf_index, face_id LIMIT 5000",
            params,
        ).fetchall()
    faces_by_keyframe = {}
    for row in face_rows:
        faces_by_keyframe.setdefault((row[0], row[1]), []).append(row)
    counts = db.conn.execute(
        "SELECT COUNT(*), COUNT(ke.embedding) FROM video_keyframes vk "
        "LEFT JOIN keyframe_embedding ke ON ke.keyframe_id=vk.id WHERE vk.video_id=?",
        (media_id,),
    ).fetchone()
    selection = db.conn.execute(
        "SELECT selector_version, status, error_type FROM video_keyframe_selection_state "
        "WHERE video_id=? ORDER BY selector_version LIMIT 20", (media_id,),
    ).fetchall()
    frame_cache = db.conn.execute(
        "SELECT COUNT(DISTINCT vf.frame_id), COUNT(vfr.rendition_id) "
        "FROM video_frame vf LEFT JOIN video_frame_rendition vfr ON vfr.frame_id=vf.frame_id "
        "WHERE vf.video_id=?", (media_id,),
    ).fetchone()
    synthetic_by_shot = dict(db.conn.execute(
        "SELECT shot_index, is_synthetic FROM shots WHERE video_id=?", (media_id,),
    ).fetchall())
    return {
        "video_keyframes": {
            "shot_count": len(shots),
            "shots": [
                {"shot_index": int(shot.get("shot_index", index)),
                 "start": shot["t_start"], "end": shot["t_end"],
                 "is_synthetic": bool(synthetic_by_shot.get(shot.get("shot_index", index), False))}
                for index, shot in enumerate(shots[:100])
            ],
            "shots_truncated": len(shots) > 100,
            "keyframe_count": int(counts[0]),
            "embedded_keyframe_count": int(counts[1]),
            "frame_cache": {"decoded_frames": int(frame_cache[0]), "cached_renditions": int(frame_cache[1])},
            "face_bbox_format": "normalized_xywh_0_to_1",
            "keyframes": [
                {"shot_index": row[0], "keyframe_index": row[1], "timestamp": row[2],
                 "gps_lat": row[3], "gps_lon": row[4], "gps_alt": row[5],
                 "gps_source": row[6], "frame_id": row[7],
                 "selection_version": row[8], "object_tags": _tags(row[9]),
                 "face_count": int(row[10]),
                 "faces": [
                     {"bbox": [float(face[2]), float(face[3]), float(face[4]), float(face[5])],
                      "confidence": float(face[6])}
                     for face in faces_by_keyframe.get((row[0], row[1]), [])[:20]
                 ],
                 "faces_truncated": (
                     len(faces_by_keyframe.get((row[0], row[1]), [])) < int(row[10])
                     or int(row[10]) > 20
                 )}
                for row in keyframes
            ],
            "keyframes_truncated": int(counts[0]) > len(keyframes),
            "selection_status": [
                {"version": row[0], "status": row[1], "error_type": row[2]}
                for row in selection
            ],
            "detector_status": db.get_processing_status(media_id),
        },
    }


def preview_video_keyframes(config, source, relative_path: str) -> dict:
    """Inspect one video; retained for internal callers and isolated tests."""
    return run_one_file(
        config, source, relative_path, expected_type="video",
        after_index=_inspect_video_keyframes,
    )


def preview_video_keyframes_folder(config, source, result_limit: int = 25) -> dict:
    """Run the complete keyframe pipeline for every configured-source video."""
    return run_video_folder(
        config, source, result_limit=result_limit, after_index=_inspect_video_keyframes,
    )
