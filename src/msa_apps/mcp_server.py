"""Local MCP interface for the existing media library; stdio only."""
from __future__ import annotations

import base64
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mcp.server import MCPServer

mcp = MCPServer("local-media-intelligence")
_ALLOW_WRITES = os.environ.get("MSA_MCP_ALLOW_WRITES", "").strip().lower() in {"1", "true", "yes"}


def _config():
    from msa_settings import load_config
    return load_config()


def _api_request(cfg):
    # The API handlers already centralize path resolution and asset-inspection logic.
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(S=cfg)))


def _page(cursor: str, limit: int, maximum: int = 100) -> tuple[int, int]:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    try:
        offset = int(cursor) if cursor else 0
    except (TypeError, ValueError) as exc:
        raise ValueError("cursor must be a non-negative integer offset") from exc
    if offset < 0 or offset > 1_000_000:
        raise ValueError("cursor must be a non-negative integer offset")
    return offset, limit


def _json_value(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


@mcp.tool()
def search_media(
    query: str,
    limit: int = 20,
    cursor: str = "",
    media_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    tags: list[str] | None = None,
    user_tags: list[str] | None = None,
    people: list[str] | None = None,
) -> dict[str, Any]:
    """Search indexed images and videos by stored captions, scenes, and available visual similarity; use search_transcripts for speech."""
    from datetime import date

    # The default prevents any cache miss from downloading model weights.
    os.environ.setdefault("MSA_SEARCH_BROWSE_READ_ONLY", "1")
    from msa_apps.search_api.deps import get_query_engine

    if not query.strip() or len(query) > 512:
        raise ValueError("query must contain 1-512 characters")
    if media_type not in (None, "image", "video"):
        raise ValueError("media_type must be image or video")
    for value in (date_from, date_to):
        if value is not None:
            date.fromisoformat(value)
    if date_from and date_to and date_from > date_to:
        raise ValueError("date_from must not be after date_to")
    filter_values = (tags or []) + (user_tags or []) + (people or [])
    if len(tags or []) > 50 or len(user_tags or []) > 50 or len(people or []) > 50:
        raise ValueError("at most 50 tag and people filters are allowed")
    if any(len(value) > 100 for value in filter_values):
        raise ValueError("tag and people filters must be at most 100 characters")
    offset, limit = _page(cursor, limit, 50)
    filters = {k: v for k, v in {
        "media_type": media_type, "date_from": date_from, "date_to": date_to,
        "tags": tags, "user_tags": user_tags, "people": people,
    }.items() if v is not None}
    results = get_query_engine().search(query, filters=filters or None)
    items = []
    for row in results[offset:offset + limit]:
        items.append({key: row.get(key) for key in (
            "id", "type", "score", "date", "timestamp", "scene_timestamp",
            "scene_matches", "caption_excerpt", "tags", "user_tags", "place", "why",
        ) if key in row})
    next_cursor = str(offset + len(items)) if offset + len(items) < len(results) else None
    context = getattr(results, "query_context", {})
    return {
        "items": items, "count": len(results), "limit": limit, "cursor": cursor,
        "next_cursor": next_cursor,
        "semantic_search_available": context.get("semantic_search_available", True),
        "semantic_search_message": context.get("semantic_search_message"),
    }


@mcp.tool()
def search_transcripts(query: str, limit: int = 20) -> dict[str, Any]:
    """Search stored speech segments with SQLite full-text search; never opens media or loads Whisper."""
    if not query.strip() or len(query) > 512:
        raise ValueError("query must contain 1-512 characters")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    from msa_query.query_engine.transcript_search import search_transcripts as _search
    path = Path(_config().sqlite_path).expanduser()
    return {"items": _search(path, query, limit), "limit": limit}


@mcp.tool()
def list_media(
    limit: int = 50,
    cursor: str = "",
    media_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    tags: str | None = None,
    user_tags: str | None = None,
    people: str | None = None,
    place: str | None = None,
) -> dict[str, Any]:
    """Browse indexed media with date, type, people, tag, and place filters."""
    from msa_apps.search_api.app import list_media as api_list_media

    offset, limit = _page(cursor, limit)
    if media_type not in (None, "image", "video"):
        raise ValueError("media_type must be image or video")
    cfg = _config()
    result = api_list_media(
        _api_request(cfg), limit=limit, offset=offset, media_type=media_type,
        date_from=date_from, date_to=date_to, tags=tags, user_tags=user_tags,
        people=people, place=place,
    )
    next_cursor = str(offset + len(result["items"])) if offset + len(result["items"]) < result["count"] else None
    return {**result, "cursor": cursor, "next_cursor": next_cursor}


def _asset_intelligence(media_id: str) -> dict[str, Any]:
    from msa_apps.search_api.app import get_asset_intelligence as api_get_asset_intelligence
    return _json_value(api_get_asset_intelligence(media_id, _api_request(_config())))


@mcp.tool()
def get_asset_intelligence(media_id: str) -> dict[str, Any]:
    """Return stored metadata, captions, scenes, transcript, detections, and pipeline status for one asset."""
    return _asset_intelligence(media_id)


@mcp.tool()
def get_video_scenes(media_id: str) -> dict[str, Any]:
    """Return timestamped stored scene captions for a video; no video decoding is performed."""
    asset = _asset_intelligence(media_id)
    if asset["media"]["type"] != "video":
        raise ValueError("media_id is not a video")
    scenes = asset["descriptions"]["video_scene_captions"]
    return {"media_id": media_id, "scenes": scenes, "count": len(scenes)}


@mcp.tool()
def fetch_thumbnail(media_id: str) -> dict[str, Any]:
    """Fetch an indexed JPEG thumbnail as base64 (maximum 1 MiB); never reads the original media."""
    from msa_indexer.db.sqlite_store import SQLiteStore

    if not SQLiteStore.is_valid_media_id(media_id):
        raise ValueError("Invalid media ID")
    path = Path(_config().thumb_dir).expanduser() / f"{media_id}.jpg"
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError as exc:
        raise ValueError("Thumbnail not found") from exc
    with os.fdopen(fd, "rb") as thumbnail:
        if not stat.S_ISREG(os.fstat(thumbnail.fileno()).st_mode):
            raise ValueError("Thumbnail is not a regular file")
        data = thumbnail.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Thumbnail exceeds the 1 MiB response limit")
    return {"media_id": media_id, "mime_type": "image/jpeg", "data_base64": base64.b64encode(data).decode("ascii")}


@contextmanager
def _organization_db(writable: bool = False):
    from msa_indexer.db.sqlite_store import SQLiteStore
    from msa_indexer.db.organization import ensure_organization_schema
    from msa_query.storage.db import connect_readonly

    path = Path(_config().sqlite_path).expanduser()
    if not path.is_file():
        raise ValueError("Media library database is not initialized")
    if writable:
        if not _ALLOW_WRITES:
            raise PermissionError("Writes are disabled; set MSA_MCP_ALLOW_WRITES=1 and restart the MCP server")
        store = SQLiteStore(path, create_if_missing=False)
        try:
            ensure_organization_schema(store.conn)
            yield store.conn
        finally:
            store.close()
    else:
        conn = connect_readonly(path)
        try:
            yield conn
        finally:
            conn.close()


@mcp.tool()
def get_media_tags(media_id: str) -> dict[str, Any]:
    """Return user-authored tags for an indexed asset, separate from detector labels."""
    import sqlite3
    from msa_indexer.db.organization import get_media_tags as _get_tags
    try:
        with _organization_db() as conn:
            if conn.execute("SELECT 1 FROM media WHERE media_id=? AND deleted=0", (media_id,)).fetchone() is None:
                raise ValueError("Media not found")
            return {"media_id": media_id, "tags": _get_tags(conn, media_id)}
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return {"media_id": media_id, "tags": []}
        raise


@mcp.tool()
def list_user_tags() -> dict[str, Any]:
    """List distinct user-authored tags."""
    import sqlite3
    from msa_indexer.db.organization import list_tags as _list_tags
    try:
        with _organization_db() as conn:
            return {"tags": _list_tags(conn)}
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return {"tags": []}
        raise


@mcp.tool()
def list_collections(limit: int = 50, cursor: str = "") -> dict[str, Any]:
    """List persistent virtual collections with media counts and offset pagination."""
    import sqlite3
    from msa_indexer.db.organization import list_collections as _list

    offset, limit = _page(cursor, limit)
    try:
        with _organization_db() as conn:
            items, count = _list(conn, limit, offset)
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        items, count = [], 0
    return {"items": items, "count": count, "limit": limit, "cursor": cursor,
            "next_cursor": str(offset + len(items)) if offset + len(items) < count else None}


@mcp.tool()
def get_collection_items(collection_id: str, limit: int = 50, cursor: str = "") -> dict[str, Any]:
    """List one collection's indexed media IDs with offset pagination."""
    offset, limit = _page(cursor, limit)
    from msa_indexer.db.organization import collection_items
    with _organization_db() as conn:
        items, count = collection_items(conn, collection_id, limit, offset)
    return {"items": items, "count": count, "limit": limit, "cursor": cursor,
            "next_cursor": str(offset + len(items)) if offset + len(items) < count else None}


if _ALLOW_WRITES:
    @mcp.tool()
    def set_media_tags(media_id: str, tags: list[str]) -> dict[str, Any]:
        """Replace user-authored tags on an indexed asset; detector labels are preserved."""
        from msa_indexer.db.organization import set_media_tags as _set
        with _organization_db(writable=True) as conn:
            return {"media_id": media_id, "tags": _set(conn, media_id, tags)}

    @mcp.tool()
    def create_collection(name: str, description: str = "") -> dict[str, Any]:
        """Create an empty virtual collection; media files are never moved or copied."""
        from msa_indexer.db.organization import create_collection as _create
        with _organization_db(writable=True) as conn:
            return _create(conn, name, description)

    @mcp.tool()
    def add_media_to_collection(collection_id: str, media_ids: list[str]) -> dict[str, Any]:
        """Add 1-100 existing indexed assets to a virtual collection by media ID."""
        from msa_indexer.db.organization import add_collection_media
        with _organization_db(writable=True) as conn:
            add_collection_media(conn, collection_id, media_ids)
        return {"added": len(set(media_ids))}

    @mcp.tool()
    def remove_media_from_collection(collection_id: str, media_id: str) -> dict[str, Any]:
        """Remove one membership without deleting the media or original file."""
        from msa_indexer.db.organization import remove_collection_media
        with _organization_db(writable=True) as conn:
            remove_collection_media(conn, collection_id, media_id)
        return {"removed": True}

    @mcp.tool()
    def delete_collection(collection_id: str) -> dict[str, Any]:
        """Delete a virtual collection and its memberships; media files remain untouched."""
        from msa_indexer.db.organization import delete_collection as _delete
        with _organization_db(writable=True) as conn:
            _delete(conn, collection_id)
        return {"deleted": True}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
