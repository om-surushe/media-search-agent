"""SQLite full-text retrieval over locally persisted speech segments."""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from msa_query.storage.db import connect_readonly

class TranscriptSegmentHit(TypedDict):
    start: float
    end: float
    text: str


class TranscriptVideoHit(TypedDict):
    media_id: str
    path: str
    status: str
    language: str | None
    model: str
    revision: str
    segments: list[TranscriptSegmentHit]


_STOPWORDS = {
    "a", "an", "and", "are", "at", "be", "by", "can", "clip", "clips",
    "could", "did", "do", "does", "find", "for", "from", "hear", "heard",
    "in", "is",
    "me", "mentions", "mentioned", "of", "on", "or", "person", "people",
    "phrase", "phrases", "please", "saying", "say", "says", "search", "show",
    "someone", "spoken", "the", "to", "there", "video", "videos", "voice",
    "was", "where", "which", "with", "who", "you",
}


def _fts_query(query: str) -> str:
    terms = [
        token for token in re.findall(r"\w+", query.casefold())
        if token not in _STOPWORDS
    ]
    return " AND ".join(f'"{term}"' for term in terms)


def search_transcripts(
    db_path: Path, query: str, limit: int = 20
) -> list[TranscriptVideoHit]:
    """Search only SQLite transcript data; never opens media or loads Whisper."""
    match = _fts_query(query)
    if not match:
        return []

    conn = connect_readonly(db_path)
    try:
        rows = conn.execute(
            """SELECT s.media_id, m.path, t.status, t.language, t.model_name,
                      t.model_revision, s.t_start, s.t_end, s.text,
                      bm25(transcript_segment_fts) AS relevance
               FROM transcript_segment_fts
               JOIN transcript_segment s ON s.id = transcript_segment_fts.rowid
               JOIN transcription_state t ON t.media_id = s.media_id
               JOIN media m ON m.media_id = s.media_id
               WHERE transcript_segment_fts MATCH ?
                 AND t.status = 'transcribed'
                 AND m.mime LIKE 'video/%'
                 AND COALESCE(m.deleted, 0) = 0
               ORDER BY relevance, s.media_id, s.t_start
               LIMIT ?""",
            (match, min(max(int(limit), 1) * 20, 2000)),
        ).fetchall()
    finally:
        conn.close()

    videos: dict[str, TranscriptVideoHit] = {}
    for media_id, path, status, language, model, revision, start, end, text, _ in rows:
        item = videos.get(media_id)
        if item is None:
            if len(videos) >= limit:
                continue
            item = videos[media_id] = {
                "media_id": media_id,
                "path": path,
                "status": status,
                "language": language,
                "model": model,
                "revision": revision,
                "segments": [],
            }
        if len(item["segments"]) < 3:
            item["segments"].append(
                TranscriptSegmentHit(start=float(start), end=float(end), text=str(text))
            )
    return list(videos.values())
