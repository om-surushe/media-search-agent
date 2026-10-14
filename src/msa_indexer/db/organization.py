"""Persistent user-authored tags and virtual collections."""
from __future__ import annotations

import sqlite3
import uuid
from typing import Iterable


_ORGANIZATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_tag (
  tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS media_user_tag (
  media_id TEXT NOT NULL,
  tag_id INTEGER NOT NULL,
  PRIMARY KEY (media_id, tag_id),
  FOREIGN KEY (media_id) REFERENCES media(media_id) ON DELETE CASCADE,
  FOREIGN KEY (tag_id) REFERENCES user_tag(tag_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS media_collection (
  collection_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS media_collection_item (
  collection_id TEXT NOT NULL,
  media_id TEXT NOT NULL,
  added_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (collection_id, media_id),
  FOREIGN KEY (collection_id) REFERENCES media_collection(collection_id) ON DELETE CASCADE,
  FOREIGN KEY (media_id) REFERENCES media(media_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_media_collection_item_media
  ON media_collection_item(media_id);
"""


def ensure_organization_schema(conn: sqlite3.Connection) -> None:
    """Apply only additive, idempotent organization tables to an existing DB."""
    conn.executescript(_ORGANIZATION_SCHEMA)
    conn.commit()


def normalize_user_tags(tags: Iterable[str]) -> list[str]:
    values = list(tags)
    if len(values) > 50:
        raise ValueError("At most 50 tags are allowed")
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError("Tags must be strings")
        tag = raw.strip()
        if not tag:
            continue
        if len(tag) > 100 or "," in tag or any(ord(ch) < 32 for ch in tag):
            raise ValueError("Tags must be at most 100 characters and contain no commas or control characters")
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def set_media_tags(conn: sqlite3.Connection, media_id: str, tags: Iterable[str]) -> list[str]:
    normalized = normalize_user_tags(tags)
    if conn.execute("SELECT 1 FROM media WHERE media_id=? AND deleted=0", (media_id,)).fetchone() is None:
        raise KeyError("Media not found")
    old = [row[0] for row in conn.execute(
        "SELECT t.name FROM media_user_tag mt JOIN user_tag t USING(tag_id) "
        "WHERE mt.media_id=? ORDER BY t.name COLLATE NOCASE", (media_id,)
    )]
    if [x.casefold() for x in old] == sorted(x.casefold() for x in normalized):
        return old
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM media_user_tag WHERE media_id=?", (media_id,))
        for tag in normalized:
            conn.execute("INSERT INTO user_tag(name) VALUES (?) ON CONFLICT(name) DO NOTHING", (tag,))
            tag_id = conn.execute("SELECT tag_id FROM user_tag WHERE name=?", (tag,)).fetchone()[0]
            conn.execute("INSERT INTO media_user_tag(media_id, tag_id) VALUES (?, ?)", (media_id, tag_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return normalized


def get_media_tags(conn: sqlite3.Connection, media_id: str) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT t.name FROM media_user_tag mt JOIN user_tag t USING(tag_id) "
        "WHERE mt.media_id=? ORDER BY t.name COLLATE NOCASE", (media_id,)
    )]


def list_tags(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT name FROM user_tag ORDER BY name COLLATE NOCASE")]


def create_collection(conn: sqlite3.Connection, name: str, description: str = "") -> dict:
    name, description = name.strip(), description.strip()
    if not name or len(name) > 100 or len(description) > 1000:
        raise ValueError("Collection name must be 1-100 characters; description at most 1000")
    collection_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO media_collection(collection_id,name,description) VALUES (?,?,?)",
        (collection_id, name, description),
    )
    conn.commit()
    return get_collection(conn, collection_id)


def list_collections(conn: sqlite3.Connection, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    total = int(conn.execute("SELECT COUNT(*) FROM media_collection").fetchone()[0])
    rows = conn.execute(
        "SELECT c.collection_id,c.name,c.description,c.created_at,COUNT(i.media_id) "
        "FROM media_collection c LEFT JOIN media_collection_item i USING(collection_id) "
        "GROUP BY c.collection_id ORDER BY c.name COLLATE NOCASE LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return ([{"collection_id": r[0], "name": r[1], "description": r[2], "created_at": r[3], "media_count": r[4]} for r in rows], total)


def get_collection(conn: sqlite3.Connection, collection_id: str) -> dict:
    row = conn.execute(
        "SELECT collection_id,name,description,created_at FROM media_collection WHERE collection_id=?",
        (collection_id,),
    ).fetchone()
    if row is None:
        raise KeyError("Collection not found")
    return {"collection_id": row[0], "name": row[1], "description": row[2], "created_at": row[3]}


def collection_items(conn: sqlite3.Connection, collection_id: str, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    get_collection(conn, collection_id)
    total = int(conn.execute(
        "SELECT COUNT(*) FROM media_collection_item i JOIN media m USING(media_id) "
        "WHERE i.collection_id=? AND m.deleted=0", (collection_id,)
    ).fetchone()[0])
    rows = conn.execute(
        "SELECT m.media_id,m.mime,m.ts_utc,m.duration,i.added_at "
        "FROM media_collection_item i JOIN media m USING(media_id) "
        "WHERE i.collection_id=? AND m.deleted=0 "
        "ORDER BY i.added_at DESC,m.media_id LIMIT ? OFFSET ?",
        (collection_id, limit, offset),
    ).fetchall()
    return ([{"id": r[0], "type": r[1].split("/", 1)[0] if r[1] and "/" in r[1] else None,
              "date": r[2], "duration": r[3], "added_at": r[4]} for r in rows], total)


def add_collection_media(conn: sqlite3.Connection, collection_id: str, media_ids: Iterable[str]) -> None:
    requested = list(media_ids)
    if not requested or len(requested) > 100:
        raise ValueError("Provide between 1 and 100 media IDs")
    ids = list(dict.fromkeys(requested))
    get_collection(conn, collection_id)
    placeholders = ",".join("?" for _ in ids)
    found = {row[0] for row in conn.execute(
        f"SELECT media_id FROM media WHERE deleted=0 AND media_id IN ({placeholders})", ids
    )}
    if found != set(ids):
        raise KeyError("One or more media items were not found")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO media_collection_item(collection_id,media_id) VALUES (?,?)",
            [(collection_id, media_id) for media_id in ids],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def remove_collection_media(conn: sqlite3.Connection, collection_id: str, media_id: str) -> None:
    get_collection(conn, collection_id)
    conn.execute("DELETE FROM media_collection_item WHERE collection_id=? AND media_id=?", (collection_id, media_id))
    conn.commit()


def delete_collection(conn: sqlite3.Connection, collection_id: str) -> None:
    if conn.execute("DELETE FROM media_collection WHERE collection_id=?", (collection_id,)).rowcount == 0:
        raise KeyError("Collection not found")
    conn.commit()
