"""Validate rebuilding the installed app's derived Qdrant store from SQLite."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from qdrant_client import QdrantClient
from msa_settings import load_config


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _sqlite_counts(path: Path) -> tuple[str, dict[str, int]]:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        counts = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in ("media", "image_embedding", "keyframe_embedding", "face_embedding")
            if table in tables
        }
    return integrity, counts


def _qdrant_counts(path: Path, collections: list[str]) -> dict[str, int]:
    client = QdrantClient(path=str(path))
    try:
        available = {item.name for item in client.get_collections().collections}
        return {
            name: client.count(name, exact=True).count if name in available else 0
            for name in collections
        }
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msa", required=True, help="Installed msa executable")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path,
                        help="Isolated app data root; only its Qdrant directory may be removed")
    args = parser.parse_args()

    root = args.data_root.resolve(strict=True)
    os.environ["MSA_DATA_DIR"] = str(root)
    config = load_config(str(args.config))
    sqlite_path = Path(config.sqlite_path).resolve(strict=True)
    qdrant_path = Path(config.qdrant_path).resolve()
    if not _inside(sqlite_path, root) or not _inside(qdrant_path, root):
        parser.error("resolved SQLite/Qdrant paths must both be inside the isolated data root")
    if qdrant_path == root or _inside(sqlite_path, qdrant_path):
        parser.error("Qdrant must be a child store that does not contain SQLite")
    if not qdrant_path.exists():
        parser.error("expected an existing Qdrant store")

    integrity_before, sqlite_before = _sqlite_counts(sqlite_path)
    if integrity_before != "ok" or sqlite_before.get("image_embedding", 0) == 0:
        raise RuntimeError(f"SQLite integrity/data check failed: {integrity_before}, {sqlite_before}")
    collections = [
        config.collections.image,
        config.collections.video,
        config.collections.face,
    ]
    counts_before = _qdrant_counts(qdrant_path, collections)
    if not any(counts_before.values()):
        raise RuntimeError(f"existing Qdrant store has no exported points: {counts_before}")

    print(f"SQLite integrity before rebuild: {integrity_before}; rows: {sqlite_before}")
    print(f"Qdrant point counts before rebuild: {counts_before}")
    shutil.rmtree(qdrant_path)
    env = os.environ.copy()
    result = subprocess.run(
        [str(args.msa), "index", "export", "--config", str(args.config), "--recreate"],
        env=env, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"`msa index export --recreate` failed with exit code {result.returncode}")

    integrity_after, sqlite_after = _sqlite_counts(sqlite_path)
    if integrity_after != "ok" or sqlite_after != sqlite_before:
        raise RuntimeError(f"SQLite changed or failed integrity check: {integrity_after}, {sqlite_after}")
    counts_after = _qdrant_counts(qdrant_path, collections)
    if counts_after != counts_before:
        raise RuntimeError(f"Qdrant rebuild point counts differ: before={counts_before}, after={counts_after}")

    print(f"SQLite preserved and valid after rebuild: {integrity_after}; rows: {sqlite_after}")
    print(f"Qdrant rebuilt point counts: {counts_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
