# Architecture decisions — Stage 0 audit

These are audit conclusions and constraints, not authorization to implement later stages.

## A1. Extend the existing local application; do not replace its search stack

The repository is a Python 3.11+ project with FastAPI backend, React/Vite UI, and a Tauri desktop shell (not a React-only web app). Existing semantic retrieval, people search, object tags, and video-shot indexing are substantial and tested. Keep those components as the baseline; an agent adapter should call existing services rather than duplicating retrieval logic or building a new media-search engine.

## A2. Keep SQLite canonical and Qdrant derived

`src/msa_indexer/db/schema.sql` and `SQLiteStore` define the current metadata model. SQLite stores `media.media_id`, paths/source-relative paths, type/MIME, size, timestamps, dimensions/duration, GPS, tags, people/faces, shots/keyframes, and embeddings. Qdrant is an embedded/runtime vector index derived from SQLite; embeddings are also persisted in SQLite. Do not create another canonical metadata store or change index formats without evidence.

Current media identity is SHA-256 of file bytes on the normal path; the `file_fingerprint` mapping supports multi-source paths and a size+mtime fast path that reuses the known ID without hashing. Media can be present under multiple source paths. This is an effective incremental baseline but makes the file fingerprint a stat-based shortcut, not a guarantee against same-size/same-mtime content replacement. Preserve existing semantics unless a validation test shows a product-critical collision/staleness problem.

Current video data is represented through `shots` and `video_keyframes`, with `shot_index`, `t_start`, `t_end`, and keyframe timestamps; search results carry a matching timestamp and shot index. `model_version`, embeddings version, and per-feature completion flags already provide examples for durable processing status. A Stage 2 schema addition should be additive/backward-compatible and should record extractor/model version and processing state, without recasting the whole schema.

## A3. Treat speech/OCR as verified gaps, not presumed infrastructure

Video documentation explicitly says audio/transcripts are not indexed. There is no transcription or OCR implementation/dependency located in source or the main requirements. Search code tolerates optional `caption` and `asr` Qdrant collections, and config names those collections, but the indexer/schema do not provide durable transcript/caption/OCR records or an extraction pipeline. Thus these are seams/placeholders, not implemented capabilities. Stage 1 should reconfirm runtime behavior before Stage 2 work.

The existing feature docs also state CLIP does not OCR text. Rich natural-language scene captions are not produced by the current indexer; current visual semantic embeddings, object labels and video keyframes are not equivalent to verified captions or speech.

## A4. MCP should be a thin, read-only local boundary

No MCP SDK, server, or MCP routes are present. Candidate operations map to existing capabilities: semantic search; indexed metadata; people listing/filtering and face search; video shot/keyframe metadata; image/video serving; index status. Keep tools consolidated and typed around these services. Do not expose indexer start/stop, configuration mutations, people-label changes, directory browsing, search-open tracking, or other write operations as V0.1 MCP tools. Use local-only transport/binding and authorize every source reference through indexed media IDs. Do not send previews by default.

The current HTTP API has both read and write endpoints and has local file-serving/browse functionality. Its desktop shell uses loopback/ephemeral ports; headless defaults are loopback, with an explicit CLI option to bind more broadly. Do not expose the existing broad API as-is as an agent tool boundary.

## A5. Preserve path and privacy boundaries

SQLite stores source paths and metadata in plaintext. Existing media serving resolves a requested media ID through a non-deleted indexed row; it intentionally serves indexed files even when a configured source root later changes. That behavior supports moved/renamed source configuration but means the index database is the effective access boundary. MCP should use the same indexed-ID check and should avoid arbitrary path input. Agent responses should include paths only as needed and warn that local source paths may disclose personal information.

Existing local inference is on-device. First-run provisioning downloads runtime/model weights from upstreams, so “offline” means after dependencies and models have already been installed. Stage 0 did not launch the app or touch installed configuration, services, models, or user index.

## A6. Reuse licenses cautiously

The repository source is MIT-licensed, with third-party notices in `NOTICE`. Existing default CLIP/OpenCLIP, RT-DETR, facenet-pytorch, FastAPI, Qdrant, React, and Tauri components are listed under permissive licenses in the repository notices. InsightFace weights are explicitly non-commercial-use-only and must not enter a commercial product path. Before choosing speech/OCR dependencies or model weights, check the exact code, model-weight, and dataset licenses independently; a permissive library license does not establish that every downloaded weight is commercially compatible. Do not copy SCM/Omni source wholesale.

## A7. Keep verification isolated and opt-in

Use the repository test fixtures that create temporary SQLite/config paths and copied sample fixtures. The checked-in development `config.yaml` targets checkout-local `index/`, `qdrant/`, `models/`, thumbnails, and logs; the installed macOS app uses separate Application Support locations. Never run an indexer against installed app paths. `tests/conftest.py` can create a temporary UI distribution stub in the checkout during test runs; clean up only test-generated artifacts. Stage 0 did not install packages, download models, run tests, or index files.

## Open questions for Stage 1

- Verify on this machine that folder selection/configuration, indexing, search, image/video previews, people filtering, and shot/timestamp retrieval work without touching the installed application.
- Confirm behavior of supported video seeking/range delivery and whether preview APIs can return only the requested media rather than arbitrary filesystem paths.
- Establish which existing index schema versions are found in actual user data only through an explicitly approved, read-only compatibility inspection; do not open/migrate the installed database during Stage 0.
- Decide exact transcript/OCR scope and commercially usable model/dependency choices only after baseline validation and licensing review.
