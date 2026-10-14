"""Read-only lexical search over stored timestamped video-scene captions."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from msa_query.query_engine.transcript_search import _fts_query

_TOKEN_RE = re.compile(r"\w+")
_MAX_EXCERPT_CHARS = 120
_MAX_MATCHES_PER_VIDEO = 3


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


def search_video_scene_captions(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return one deterministic, timestamped lexical result per matching video.

    Only completed captions are considered. The caller supplies a read-only SQLite
    connection; this function neither loads models nor changes the index.
    """
    terms = list(dict.fromkeys(re.findall(r'"([^\"]+)"', _fts_query(query))))
    limit = max(0, int(limit))
    if not terms or not limit:
        return []

    rows = conn.execute(
        """SELECT c.video_id, c.keyframe_id, c.timestamp, c.caption,
                  c.model_id, c.prompt_version, m.path, m.ts_utc,
                  m.gps_lat, m.gps_lon, m.place, vk.shot_index,
                  vk.shot_start, vk.shot_end, vk.tags
           FROM video_scene_caption c
           JOIN media m ON m.media_id = c.video_id
           JOIN video_keyframes vk ON vk.id = c.keyframe_id
           WHERE c.status = 'completed'
             AND m.mime LIKE 'video/%'
             AND COALESCE(m.deleted, 0) = 0
           ORDER BY c.video_id, c.timestamp, c.keyframe_id,
                    c.model_id, c.prompt_version"""
    ).fetchall()

    wanted = set(terms)
    filters = filters or {}
    timestamp_range = filters.get("timestamp_range")
    by_video: dict[str, dict[int, tuple[tuple[Any, ...], dict[str, Any]]]] = {}
    for (
        video_id, keyframe_id, timestamp, caption, model_id, prompt_version,
        path, date, gps_lat, gps_lon, place, shot_index, shot_start,
        shot_end, frame_tags,
    ) in rows:
        text = str(caption)
        tokens = _TOKEN_RE.findall(text.casefold())
        if not wanted.issubset(tokens):
            continue
        timestamp_value = float(timestamp)
        shot_duration = float(shot_end) - float(shot_start)
        if timestamp_range and len(timestamp_range) == 2 and not (
            float(timestamp_range[0]) <= timestamp_value <= float(timestamp_range[1])
        ):
            continue
        if filters.get("min_duration") and shot_duration < float(filters["min_duration"]):
            continue
        if filters.get("max_duration") and shot_duration > float(filters["max_duration"]):
            continue
        occurrence_count = sum(tokens.count(term) for term in terms)
        match = {
            "keyframe_id": int(keyframe_id),
            "timestamp": timestamp_value,
            "caption_excerpt": _excerpt(text, terms),
        }
        item = {
            "id": str(video_id),
            "path": path,
            "date": date,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "place": place,
            "type": "video",
            "timestamp": timestamp_value,
            "shot_id": int(shot_index),
            "shot_start": float(shot_start),
            "shot_end": float(shot_end),
            "tags": [],
            "caption_excerpt": match["caption_excerpt"],
            "scene_matches": [match],
        }
        # Prefer more term occurrences; break ties by timestamp and stable model IDs.
        rank = (-occurrence_count, float(timestamp), int(keyframe_id), str(model_id), str(prompt_version))
        video_matches = by_video.setdefault(str(video_id), {})
        previous = video_matches.get(int(keyframe_id))
        if previous is None or rank < previous[0]:
            video_matches[int(keyframe_id)] = (rank, item)
        if frame_tags:
            try:
                item["tags"] = [str(tag) for tag in json.loads(frame_tags) if tag]
            except (TypeError, ValueError):
                pass

    ranked_videos = sorted(
        (
            (min(match[0] for match in matches.values()), video_id, matches)
            for video_id, matches in by_video.items()
        ),
        key=lambda value: (value[0], value[1]),
    )[:limit]
    if not ranked_videos:
        return []

    ids = [video_id for _, video_id, _ in ranked_videos]
    placeholders = ",".join("?" for _ in ids)
    tag_rows = conn.execute(
        f"""SELECT mt.media_id, t.name
            FROM media_tag mt JOIN tag t ON t.tag_id = mt.tag_id
            WHERE mt.media_id IN ({placeholders})
            ORDER BY mt.media_id, t.name COLLATE NOCASE""",
        ids,
    ).fetchall()
    media_tags: dict[str, set[str]] = {}
    for video_id, tag in tag_rows:
        media_tags.setdefault(str(video_id), set()).add(str(tag))

    results = []
    for _, video_id, matches in ranked_videos:
        best = sorted(matches.values(), key=lambda value: value[0])[:_MAX_MATCHES_PER_VIDEO]
        item = best[0][1]
        scene_matches = [match[1]["scene_matches"][0] for match in best]
        tags = set(media_tags.get(video_id, set()))
        for _, match_item in matches.values():
            tags.update(match_item["tags"])
        item["tags"] = sorted(tags, key=str.casefold)
        item["scene_matches"] = scene_matches
        item["caption_excerpt"] = scene_matches[0]["caption_excerpt"]
        item["timestamp"] = scene_matches[0]["timestamp"]
        item["keyframe_id"] = scene_matches[0]["keyframe_id"]
        results.append(item)
    return results


def merge_video_scene_matches(
    results: list[dict[str, Any]], scene_hits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach lexical scene evidence to visual hits, then append one result per video."""
    hits_by_video = {str(hit["id"]): hit for hit in scene_hits}
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for result in results:
        video_id = str(result.get("id", ""))
        hit = hits_by_video.get(video_id)
        if hit is None:
            merged.append(result)
            continue
        if video_id in seen:
            continue
        seen.add(video_id)
        result["caption_excerpt"] = hit["caption_excerpt"]
        result["scene_timestamp"] = hit["timestamp"]
        result["scene_matches"] = hit["scene_matches"]
        merged.append(result)

    for hit in scene_hits:
        video_id = str(hit["id"])
        if video_id in seen:
            continue
        seen.add(video_id)
        merged.append({
            "id": video_id,
            "path": hit.get("path"),
            "thumbnail": None,
            "score": None,
            "tags": hit.get("tags", []),
            "type": "video",
            "timestamp": hit["timestamp"],
            "scene_timestamp": hit["timestamp"],
            "shot_id": hit.get("shot_id"),
            "date": hit.get("date"),
            "gps_lat": hit.get("gps_lat"),
            "gps_lon": hit.get("gps_lon"),
            "place": hit.get("place"),
            "caption_excerpt": hit["caption_excerpt"],
            "scene_matches": hit["scene_matches"],
            "why": f"Video scene caption match: {hit['caption_excerpt']}",
        })
    return merged
