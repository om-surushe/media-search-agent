"""Read-only lexical search over stored image-caption variants."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from msa_query.query_engine.transcript_search import _fts_query

_TOKEN_RE = re.compile(r"\w+")
_QUERY_MODIFIERS = {"image", "images", "photo", "photos", "picture", "pictures"}
_MAX_EXCERPT_CHARS = 120


def _excerpt(caption: str, terms: list[str]) -> str:
    if len(caption) <= _MAX_EXCERPT_CHARS:
        return caption

    positions = [
        match.start()
        for term in terms
        for match in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", caption, re.IGNORECASE)
    ]
    start = max(0, (min(positions) if positions else 0) - 32)
    end = min(len(caption), start + _MAX_EXCERPT_CHARS)
    return ("…" if start else "") + caption[start:end].strip() + ("…" if end < len(caption) else "")


def search_image_captions(
    conn: sqlite3.Connection, query: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Return completed image-caption matches, grouped and ordered by media ID.

    Search uses the same quoted-token normalization as transcript FTS. The existing
    FTS5 table indexes transcripts only; this read-only path scans stored captions
    rather than creating or backfilling an index in the user's database.
    """
    terms = [
        term for term in dict.fromkeys(re.findall(r'"([^\"]+)"', _fts_query(query)))
        if term not in _QUERY_MODIFIERS
    ]
    limit = max(0, int(limit))
    if not terms or not limit:
        return []

    # ponytail: scan the small caption table to keep live search read-only; add a
    # persisted caption FTS projection only if this scan becomes measurable.
    rows = conn.execute(
        """SELECT c.media_id, c.caption, c.model_id, c.prompt_version,
                  m.path, m.ts_utc, m.gps_lat, m.gps_lon, m.place
           FROM image_caption c
           JOIN media m ON m.media_id = c.media_id
           WHERE c.status = 'completed'
             AND m.mime LIKE 'image/%'
             AND COALESCE(m.deleted, 0) = 0
           ORDER BY c.media_id, c.model_id, c.prompt_version, c.generated_at_utc"""
    ).fetchall()

    best: dict[str, tuple[int, str, str, dict[str, Any]]] = {}
    wanted = set(terms)
    for media_id, caption, model_id, prompt_version, path, date, lat, lon, place in rows:
        tokens = _TOKEN_RE.findall(str(caption).casefold())
        token_set = set(tokens)
        if not wanted.issubset(token_set):
            continue
        occurrences = sum(tokens.count(term) for term in terms)
        item = {
            "id": str(media_id),
            "path": path,
            "date": date,
            "gps_lat": lat,
            "gps_lon": lon,
            "place": place,
            "tags": [],
            "caption_excerpt": _excerpt(str(caption), terms),
        }
        current = best.get(str(media_id))
        rank = (-occurrences, str(model_id), str(prompt_version))
        if current is None or rank < current[:3]:
            best[str(media_id)] = (*rank, item)

    ordered = sorted(best.values(), key=lambda row: (row[0], row[3]["id"]))[:limit]
    if not ordered:
        return []

    ids = [row[3]["id"] for row in ordered]
    placeholders = ",".join("?" for _ in ids)
    tag_rows = conn.execute(
        f"""SELECT mt.media_id, t.name
            FROM media_tag mt JOIN tag t ON t.tag_id = mt.tag_id
            WHERE mt.media_id IN ({placeholders})
            ORDER BY mt.media_id, t.name""",
        ids,
    ).fetchall()
    tags: dict[str, list[str]] = {}
    for media_id, name in tag_rows:
        tags.setdefault(str(media_id), []).append(str(name))

    results = [row[3] for row in ordered]
    for item in results:
        item["tags"] = tags.get(item["id"], [])
    return results
