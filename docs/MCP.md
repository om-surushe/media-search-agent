# Local MCP server

The packaged Python runtime includes an official, MIT-licensed MCP Python SDK server, exposed over **stdio**. The MCP process uses the app's existing config, SQLite index, thumbnail directory, search engine, and asset-inspection handler; it opens no network listener and does not copy or modify source media.

> **Distribution status:** protocol-level stdio tests, persistent organization writes, and the shared query path pass in an isolated temporary library. A fresh-user packaged app and release artifact have not yet passed acceptance; do not assume an already-published installer contains this integration.

## macOS client configuration

Launch MediaSearchAgent once so its private runtime and config exist, then add this server entry to the MCP client's JSON configuration. Replace `<your-user>` with your macOS home-directory name. The runtime command is installed in the app-private venv; the YAML and database remain in the separate data directory.

```json
{
  "mcpServers": {
    "media-search-agent": {
      "command": "/Users/<your-user>/Library/Application Support/ai.openara.mediasearchagent/.venv/bin/msa-mcp-server",
      "args": [],
      "env": {
        "MSA_CONFIG_PATH": "/Users/<your-user>/Library/Application Support/MediaSearchAgent/config.yaml",
        "MSA_DATA_DIR": "/Users/<your-user>/Library/Application Support/MediaSearchAgent",
        "MSA_CACHE_DIR": "/Users/<your-user>/Library/Caches/MediaSearchAgent",
        "MSA_LOG_DIR": "/Users/<your-user>/Library/Logs/MediaSearchAgent",
        "MSA_SEARCH_BROWSE_READ_ONLY": "1",
        "MSA_MCP_ALLOW_WRITES": "0"
      }
    }
  }
}
```

Restart the MCP client after changing its configuration. MCP clients commonly store this JSON in a per-user settings file; use that client's documented location. The app must have been launched at least once so the private venv and `config.yaml` exist. First launch provisions the Python runtime and dependencies; model weights are a separate model-setup step. The MCP server itself does not set up models or download weights.

## Tools and safety

Read-only tools are advertised by default:

- `search_media` — caption, timestamped scene, and available visual search, with type/date/detector-tag/user-tag/people filters.
- `search_transcripts` — full-text search over stored speech segments.
- `list_media` — filtered, offset-paginated browse.
- `get_asset_intelligence` and `get_video_scenes` — indexed metadata and stored timestamped captions; no original video decoding.
- `fetch_thumbnail` — returns only an indexed JPEG thumbnail as base64, capped at 1 MiB.
- `get_media_tags`, `list_user_tags`, `list_collections`, and `get_collection_items`.

Search/Browse read-only mode keeps model setup offline. If a valid CLIP cache is absent, visual search reports unavailable and `search_media` still uses stored image and scene captions. `search_transcripts` separately searches stored speech segments without loading Whisper. MCP search pagination uses numeric offset cursors over the query engine's bounded result set; `list_media` and collection listing use database-backed pagination.

To explicitly allow organization writes, set `MSA_MCP_ALLOW_WRITES` to `1` in this server's environment and restart the MCP client. The opt-in adds `set_media_tags`, `create_collection`, `add_media_to_collection`, `remove_media_from_collection`, and `delete_collection`. These operations update only user-authored tag and virtual-collection rows in the existing SQLite index. Collections contain media IDs, not copies; deleting a collection or removing a member never deletes an asset. Keeping `MSA_SEARCH_BROWSE_READ_ONLY=1` is compatible with this explicit MCP write opt-in and prevents model-download retries/indexer setup.

The desktop UI reads the same tags and collections from the local API. In an app instance whose API is itself in Search/Browse read-only mode, UI write requests are rejected; MCP writes require the separate opt-in above.

## Development and protocol testing

Install the declared runtime dependencies, set `PYTHONPATH=src`, `MSA_CONFIG_PATH` to an isolated test config, and run:

```bash
python -m msa_apps.mcp_server
```

The server waits for an MCP stdio client and writes protocol messages to stdout. `tests/test_mcp_server.py` launches it as a subprocess using the official Python SDK `Client`, discovers tools, calls search/transcript/asset/thumbnail/organization tools, and verifies persistence after reconnecting. Its fixture uses a temporary SQLite database and thumbnail only.
