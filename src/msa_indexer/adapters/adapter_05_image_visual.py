"""Stage 05: isolated image embeddings, object labels, and face enrichment."""
from __future__ import annotations

from ._workbench_sandbox import run_image_folder, run_one_file


def image_visual_capability(config) -> dict[str, bool | str | None]:
    from ._workbench_sandbox import index_capability

    return index_capability(config, force_object_detection=True)


def _inspect_image_visual(db, _isolated, _workspace, media_id):
    embedding = db.conn.execute(
        "SELECT embedding_dim, embedding_model FROM image_embedding WHERE media_id=?",
        (media_id,),
    ).fetchone()
    tags = [row[0] for row in db.conn.execute(
        "SELECT t.name FROM tag t JOIN media_tag mt ON mt.tag_id=t.tag_id "
        "WHERE mt.media_id=? ORDER BY t.name LIMIT 100", (media_id,),
    ).fetchall()]
    faces = db.conn.execute(
        "SELECT face_id, x, y, w, h, confidence, gender, age FROM face "
        "WHERE media_id=? ORDER BY face_id LIMIT 100", (media_id,),
    ).fetchall()
    return {
        "image_visual": {
            "embedding": None if embedding is None else {
                "dimension": int(embedding[0]), "model": embedding[1],
            },
            "object_tags": tags,
            "object_tags_truncated": len(tags) == 100,
            "faces": [
                {"face_id": row[0], "bbox": [row[1], row[2], row[3], row[4]],
                 "confidence": row[5], "gender": row[6], "age": row[7]}
                for row in faces
            ],
            "faces_truncated": len(faces) == 100,
            "detector_status": db.get_processing_status(media_id),
        },
    }


def preview_image_visual(config, source, relative_path: str) -> dict:
    """Preview one image; retained for internal callers and isolated tests."""
    return run_one_file(
        config, source, relative_path, expected_type="image", after_index=_inspect_image_visual,
        force_object_detection=True,
    )


def preview_image_visual_folder(config, source, result_limit: int = 25) -> dict:
    """Process every configured-source image; return at most result_limit details."""
    return run_image_folder(
        config, source, result_limit=result_limit, after_index=_inspect_image_visual,
    )
