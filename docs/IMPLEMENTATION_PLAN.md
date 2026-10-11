# Implementation plan

This plan is gated. Complete one stage, report actual results, and stop for user acceptance before starting another. Stages 0 and 1 are complete. The current authorized scope is Stage 2A only; stop for acceptance before Stage 2B or MCP work.

## Stage 0 — Audit and architecture (complete)

Inspect the checked-out fork, project docs, API, indexing/storage pipeline, schemas/migrations, tests, packaging, and license notices. Record existing capabilities, gaps, risks, minimal integration points, and an isolated development/test workflow in the three Stage 0 documents. Do not run indexing, install dependencies, download models, or alter application files or installed-app data. Stop for approval.

## Stage 1 — Foundation validation (complete)

Validated the existing checkout with isolated temporary databases and copied public media fixtures. Configuration, indexing, metadata, search, previews, people filtering, and timestamped video shots passed; Stage 1.5 regression baseline: 1,037 passed, 70 skipped, 23 deselected, 2 xpassed. The installed application database and media were not used.

## Stage 2A — Local speech transcription (implementation complete; acceptance pending)

Added opt-in local Whisper transcription for videos: timestamped segments and model/runtime/status metadata persist in SQLite; FTS5 is derived in SQLite; current transcripts skip incrementally; `POST /transcripts/search` is additive. Visual `/search`, media IDs, and Qdrant behavior remain unchanged. OCR, MCP, UI, and Stage 2B were not implemented.

Validation on Apple Silicon/macOS 26.6.2/Python 3.13.5: the pinned OpenAI Whisper base checkpoint downloaded once (145,262,807 bytes; SHA-256 `ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e`). A generated spoken-dialogue video transcribed to the expected phrase in 1.91 s on CPU with 716.3 MB peak process RSS; a second run was network-denied and searched SQLite successfully. Initial model setup (download + load) took 31.19 s. The source fixture's size, mtime, and SHA-256 were unchanged. A silent video produced `no_speech` without loading the model. Whisper's decoder cannot use this PyTorch MPS build, so macOS transcription deliberately uses CPU.

Focused/regression command: `pytest -q tests/test_transcription.py tests/test_packaged_runtime_requirements.py tests/test_sqlite_store_embeddings.py tests/test_search_browse_api.py tests/test_query_engine.py tests/test_fingerprint_fastpath.py tests/test_config_roundtrip.py tests/test_settings_indexer_api.py tests/test_video_metadata_runtime.py tests/test_indexer_summary.py tests/test_pipeline_batch_commit.py` — 253 passed, 1 skipped, 1 warning. Broader `pytest -q` and `pytest -q -m 'not slow'` attempts timed out; they are not reported as passing. Await user acceptance before starting Stage 2B or MCP work.

## Stage 2B — OCR (not started; requires approval)

Potentially add local frame/photo OCR only after Stage 2A acceptance and explicit authorization. Check model/dependency licensing, local operation, privacy, and incremental persistence before implementation.

## Stage 3 — MCP integration

After Stage 2 acceptance (or explicit approval of that gate), implement the smallest local, read-only adapter around existing service/query/storage functions using the standard MCP SDK. Publish typed tools for the useful existing capabilities, with structured responses and compact text/IDs/timestamps/path references. Return previews only on request. Validate IDs and indexed paths; bind to loopback; do not expose mutating UI/API functions, filesystem browsing, or unrestricted file access. Keep transcript/OCR content explicitly untrusted. Test tool schemas and service behavior, then verify against a real external coding agent and stop for user acceptance.

## Stage 4 — End-to-end retrieval

After MCP acceptance, validate search → metadata → filters → selected previews/original references for representative photo and timestamped-video tasks, including person and transcript searches where supported. Check ranking/evidence wording and ensure no unsupported claim of visual verification. Add only tests/fixes driven by observed failures; stop for user testing/approval.

## Stage 5 — Packaging and external validation

After workflow acceptance, validate reproducible local install/config/index persistence/upgrade/cleanup on a separate machine or clean environment, package locally where practical, then recruit a small editor/creator group to assess real retrieval tasks. Do not add payment or hosted infrastructure. Report findings and stop for product direction.

## Development and testing approach

- Python package is in `src/`; FastAPI is `src/msa_apps/search_api`; indexer and SQLite implementation are `src/msa_indexer`; query and Qdrant access are `src/msa_query`; React/Tauri UI is under `src/msa_apps/ui` and `src-tauri`.
- Existing Python tests are in `tests/` and use pytest. `tests/conftest.py` provides `tmp_path`-backed SQLite/config fixtures; `test_media_subset` copies a small set of checked-in sample media to a temporary directory. API tests inject test config and a mock query engine. UI tests use Vitest.
- Existing repo test entrypoint: `./scripts/run-tests.sh`; focused Python tests can run through pytest and focused UI tests through the UI package's Vitest script. Stage 0 has not run tests. Do not use `--install` without separate approval. Avoid the large real-media tests unless specifically approved and use only copied fixtures.
- The test harness's conftest may create/remove a UI `dist` stub; inspect generated/untracked file effects when running it. The repository-root development config uses local `index/`, `qdrant/`, model, thumbnail, and log paths. Never substitute installed-app paths.

## Minimal change points (pending approved implementation)

1. Reuse FastAPI's current search, media-info, image/video, people, and video-shot routes/services; add an MCP adapter rather than replacing the app or search engine.
2. Reuse `SQLiteStore`, current schema and its guarded/additive migration path; add tables/columns only where Stage 1 proves needed for transcript/OCR persistence.
3. Extend the indexer at its per-media/per-video-frame processing seams only for approved extraction. Reuse existing source IDs, content identity, fingerprints, and incremental status patterns.
4. Reuse Qdrant collections/retriever integration only if transcript/OCR search is demonstrably required; don't create new vector stores or redundant metadata stores.

## Stage gates

No stage begins from a passing test alone. At each stage report implemented/reused/files/tests/manual macOS acceptance/risks, then stop and wait for explicit user approval.
