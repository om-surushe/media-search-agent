import asyncio
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from msa_indexer.db.sqlite_store import SQLiteStore


REPO_ROOT = Path(__file__).resolve().parents[1]
MEDIA_ID = "a" * 64


def _fixture_library(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "index" / "media.sqlite"
    db_path.parent.mkdir(parents=True)
    with SQLiteStore(db_path) as store:
        store.init_schema_no_migrations(REPO_ROOT / "src/msa_indexer/db/schema.sql")
        conn = store.conn
        conn.execute(
            "INSERT INTO media(media_id,path,mime,duration) VALUES (?,?,?,?)",
            (MEDIA_ID, str(tmp_path / "original.mp4"), "video/mp4", 30.0),
        )
        cur = conn.execute(
            "INSERT INTO video_keyframes(video_id,shot_index,kf_index,timestamp,shot_start,shot_end) "
            "VALUES (?,?,?,?,?,?)", (MEDIA_ID, 0, 0, 12.5, 0.0, 30.0),
        )
        keyframe_id = cur.lastrowid
        conn.execute(
            "INSERT INTO video_scene_caption(video_id,keyframe_id,timestamp,caption,model_id,prompt_version,generated_at_utc,status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (MEDIA_ID, keyframe_id, 12.5, "A street corner with a crosswalk", "test", "v1", "2026-01-01T00:00:00Z", "completed"),
        )
        conn.execute(
            "INSERT INTO transcription_state(media_id,model_name,model_revision,runtime_version,status,segment_count) "
            "VALUES (?,?,?,?,?,1)", (MEDIA_ID, "test", "v1", "test", "transcribed"),
        )
        conn.execute(
            "INSERT INTO transcript_segment(media_id,segment_index,t_start,t_end,text) VALUES (?,?,?,?,?)",
            (MEDIA_ID, 0, 4.0, 6.0, "We are walking on the beach"),
        )
        store.commit()

    thumb_dir = tmp_path / "thumbnails"
    thumb_dir.mkdir()
    (thumb_dir / f"{MEDIA_ID}.jpg").write_bytes(b"test-thumbnail")
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join([
            f"sqlite_path: {db_path}", f"index_dir: {db_path.parent}",
            f"qdrant_path: {tmp_path / 'qdrant'}", f"thumb_dir: {thumb_dir}",
            f"face_thumb_dir: {tmp_path / 'face-thumbnails'}", f"models_dir: {tmp_path / 'models'}",
            "media_sources: []", "enable_face_recognition: false", "enable_object_detection: false",
        ]) + "\n",
        encoding="utf-8",
    )
    return config, thumb_dir


def _client_env(tmp_path: Path, config: Path, *, allow_writes: bool) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
        "PYTHONPATH": str(REPO_ROOT / "src"), "MSA_CONFIG_PATH": str(config),
        "MSA_DATA_DIR": str(tmp_path), "MSA_CACHE_DIR": str(tmp_path / "cache"),
        "MSA_LOG_DIR": str(tmp_path / "logs"),
        "MSA_SEARCH_BROWSE_READ_ONLY": "1",
        "MSA_MCP_ALLOW_WRITES": "1" if allow_writes else "0",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
    }
    return env


def _parameters(tmp_path: Path, config: Path, *, allow_writes: bool) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "msa_apps.mcp_server"],
        env=_client_env(tmp_path, config, allow_writes=allow_writes), cwd=REPO_ROOT,
    )


def test_real_stdio_mcp_client_discovery_tools_and_persistence(tmp_path):
    config, thumb_dir = _fixture_library(tmp_path)

    async def verify_read_only():
        async with Client(_parameters(tmp_path, config, allow_writes=False)) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert {"search_media", "search_transcripts", "list_media", "get_asset_intelligence", "get_video_scenes", "fetch_thumbnail", "list_collections"} <= tools
            assert "create_collection" not in tools
            search = await client.call_tool("search_media", {"query": "street corner"})
            assert not search.is_error and search.structured_content is not None
            assert search.structured_content["items"][0]["scene_timestamp"] == 12.5
            transcript = await client.call_tool("search_transcripts", {"query": "walking beach"})
            assert not transcript.is_error and transcript.structured_content["items"][0]["media_id"] == MEDIA_ID
            asset = await client.call_tool("get_asset_intelligence", {"media_id": MEDIA_ID})
            assert not asset.is_error and asset.structured_content is not None
            assert asset.structured_content["descriptions"]["video_scene_captions"][0]["timestamp"] == 12.5
            thumb = await client.call_tool("fetch_thumbnail", {"media_id": MEDIA_ID})
            assert not thumb.is_error and thumb.structured_content["mime_type"] == "image/jpeg"
            thumbnail_path = thumb_dir / f"{MEDIA_ID}.jpg"
            original = thumbnail_path.read_bytes()
            outside = tmp_path / "outside.jpg"
            outside.write_bytes(b"must not be exposed")
            thumbnail_path.unlink()
            thumbnail_path.symlink_to(outside)
            rejected = await client.call_tool("fetch_thumbnail", {"media_id": MEDIA_ID})
            assert rejected.is_error
            thumbnail_path.unlink()
            thumbnail_path.write_bytes(original)

    asyncio.run(verify_read_only())

    async def write_and_restart():
        params = _parameters(tmp_path, config, allow_writes=True)
        async with Client(params) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert {"create_collection", "add_media_to_collection", "set_media_tags"} <= tools
            created = await client.call_tool("create_collection", {"name": "Trip", "description": "Local test"})
            assert not created.is_error and created.structured_content is not None
            collection_id = created.structured_content["collection_id"]
            added = await client.call_tool("add_media_to_collection", {"collection_id": collection_id, "media_ids": [MEDIA_ID]})
            assert not added.is_error and added.structured_content["added"] == 1
            tagged = await client.call_tool("set_media_tags", {"media_id": MEDIA_ID, "tags": ["Family", "Trip"]})
            assert not tagged.is_error and tagged.structured_content["tags"] == ["Family", "Trip"]
            filtered = await client.call_tool("search_media", {"query": "street corner", "user_tags": ["Family"]})
            assert not filtered.is_error and filtered.structured_content["items"][0]["user_tags"] == ["Family", "Trip"]
        async with Client(params) as client:
            listed = await client.call_tool("list_collections", {})
            assert listed.structured_content["items"][0]["media_count"] == 1
            search = await client.call_tool("search_media", {"query": "street corner"})
            assert search.structured_content["items"][0]["user_tags"] == ["Family", "Trip"]
            tags = await client.call_tool("get_media_tags", {"media_id": MEDIA_ID})
            assert tags.structured_content["tags"] == ["Family", "Trip"]

    asyncio.run(write_and_restart())


def test_mcp_requires_explicit_write_opt_in_even_in_model_free_mode(tmp_path):
    config, _ = _fixture_library(tmp_path)

    async def verify():
        params = _parameters(tmp_path, config, allow_writes=False)
        env = dict(params.env or {})
        env["MSA_MCP_ALLOW_WRITES"] = "1"
        params = StdioServerParameters(command=params.command, args=params.args, env=env, cwd=params.cwd)
        async with Client(params) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert "create_collection" in names

    asyncio.run(verify())
