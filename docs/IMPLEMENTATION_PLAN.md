# Implementation plan

This plan is gated. Complete approved work, report actual results, and stop for user review at the stated acceptance boundary. Stages 0 and 1 are complete. Stage 2A acceptance is pending. The user has explicitly authorized the standalone Stage 2C preview and the separate video-frame modernization A–D below; this does not accept Stage 2A or authorize Stage 2B or MCP work.

## Stage 0 — Audit and architecture (complete)

Inspect the checked-out fork, project docs, API, indexing/storage pipeline, schemas/migrations, tests, packaging, and license notices. Record existing capabilities, gaps, risks, minimal integration points, and an isolated development/test workflow in the three Stage 0 documents. Do not run indexing, install dependencies, download models, or alter application files or installed-app data. Stop for approval.

## Stage 1 — Foundation validation (complete)

Validated the existing checkout with isolated temporary databases and copied public media fixtures. Configuration, indexing, metadata, search, previews, people filtering, and timestamped video shots passed; Stage 1.5 regression baseline: 1,037 passed, 70 skipped, 23 deselected, 2 xpassed. The installed application database and media were not used.

## Stage 2A — Local speech transcription (implementation complete; acceptance pending)

Added opt-in local Whisper transcription for videos: timestamped segments and model/runtime/status metadata persist in SQLite; FTS5 is derived in SQLite; current transcripts skip incrementally; `POST /transcripts/search` is additive. Visual `/search`, media IDs, and Qdrant behavior remain unchanged. OCR, MCP, UI, and Stage 2B were not implemented.

Validation on Apple Silicon/macOS 26.6.2/Python 3.13.5: the pinned OpenAI Whisper base checkpoint downloaded once (145,262,807 bytes; SHA-256 `ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e`). A generated spoken-dialogue video transcribed to the expected phrase in 1.91 s on CPU with 716.3 MB peak process RSS; a second run was network-denied and searched SQLite successfully. Initial model setup (download + load) took 31.19 s. The source fixture's size, mtime, and SHA-256 were unchanged. A silent video produced `no_speech` without loading the model. Whisper's decoder cannot use this PyTorch MPS build, so macOS transcription deliberately uses CPU.

Focused/regression command: `pytest -q tests/test_transcription.py tests/test_packaged_runtime_requirements.py tests/test_sqlite_store_embeddings.py tests/test_search_browse_api.py tests/test_query_engine.py tests/test_fingerprint_fastpath.py tests/test_config_roundtrip.py tests/test_settings_indexer_api.py tests/test_video_metadata_runtime.py tests/test_indexer_summary.py tests/test_pipeline_batch_commit.py` — 253 passed, 1 skipped, 1 warning. Broader `pytest -q` and `pytest -q -m 'not slow'` attempts timed out; they are not reported as passing. Await user acceptance before starting Stage 2B or MCP work.

## Stage 2C — Interactive video change-frame preview (implementation complete; user acceptance pending)

Build a local web page where a user uploads one video and inspects a chronological set of changing frames. Decode sequentially and compare every low-resolution grayscale frame with both its predecessor and the last selected frame. Select on a configurable changed-pixel threshold (default 8%), with a 0.25-second minimum spacing. A one-second coverage attempt is allowed only when the candidate is still visually novel; near-duplicates are skipped, so static scenes stay sparse. Cap previews at 2,000 frames and disclose omissions. This is a visual-change storyboard, not a semantic understanding model. Uploads are temporary, loopback-only, capped at 512 MiB, and deleted after analysis. An optional shared-frame-cache check uses a disposable SQLite database and bounded cache inside the upload's temporary directory, then deletes both; it does not touch the app's index/cache. Do not index the upload, persist its frames beyond the request, invoke AI models, or transmit media remotely.

Validation: `tests/test_video_keyframe_preview_api.py tests/test_video_metadata_runtime.py tests/test_video_gps_runtime.py` — 20 passed; full UI suite — 20 files / 219 tests passed; `cd src/msa_apps/ui && npm run build` — passed. The active local API processed a generated six-second video: scanned all 90 source frames and selected 3 frames (initial plus 2 scene changes), skipping repeated static frames; the temporary upload was removed. No personal source media was used. Await user testing before further keyframe work.

This stage is a user-authorized exploratory prototype and is independent of Stage 2A acceptance. It does not authorize Stage 2B or MCP work.

## Video frame modernization — A → C → B → D (user-authorized)

This is a separate video-indexing track, not Stage 2A speech transcription. PySceneDetect/midpoint rows remain the baseline; the user-approved Maximum Detail settings enable additive adaptive and long-shot candidates. Do not reindex the installed library or delete existing intelligence.

- **A — Canonical frames/cache:** Implement stable PTS-based identities, actual decoded timestamps, normalized/checksummed renditions, bounded eviction, shared references for indexer/caption consumers, and focused isolated tests. Status: implemented; synthetic benchmark and timestamped-shot API validation completed.
- **C — Safe versioned rebuilds:** Track selector status/version per video, retain existing midpoint rows and derived data, and append new policy output in disjoint keyframe slots. Failed builds remain retryable; no destructive cleanup. Status: implemented; versioned-slot and incremental-no-op tests pass.
- **B — Adaptive representatives:** Add visual-change candidates per shot behind `adaptive_video_keyframes_enabled`; preserve midpoint rows. Status: implemented and enabled by the user-approved Maximum Detail preset; selectable in Settings and previewable through the loopback-only API.
- **D — Long-shot coverage:** Add at most two novelty-gated gradual-change samples for shots meeting the configured duration threshold, separately gated by `long_shot_coverage_enabled`. Status: implemented and enabled by Maximum Detail; selectable in Settings and previewable through the loopback-only API.

Validation: focused video/pipeline suites — 62 passed, 4 skipped; storage/caption/delta/Qdrant-client regressions — 141 passed; settings/config tests — 86 passed; UI — 219 passed and production build passed. A broad non-slow Python run excluding `tests/real_media` is not clean: it also reports unrelated stale Qdrant test setup, incremental-ETA, and model-download-feedback failures; no full-suite success is claimed. A generated 12-second clip benchmark verified source-hash integrity and cache reuse (24 independent decoder opens vs. 1 grouped open, 16 cache hits), but grouped caching did not improve total elapsed time. See [Video frame indexing](VIDEO_INDEXING.md) for exact timings, module boundaries, limits, and manual checks. This track performs no full-library reindex and adds no dependencies. Selector-version rows are intentionally append-only; older results stay searchable, and pruning is deferred until rollback/history UX exists. Before a full library run, use the loopback-only disposable preview API or a copied test video to verify representative timestamps and search results; Balanced and Fast remain available if extra coverage costs too much.

## Stage 2D — Commercial model registry and adapters (user-authorized; active)

Add an app-owned catalog for the locally downloadable candidates in the Commercial Model Selection & Licensing Guide. Pin upstream revisions and exact weight files/hashes, record upstream license claims separately from clearance status, and use `models_dir/commercial/<model-id>/` as the managed destination. Downloads remain on-demand; the startup defaults must not expand to every multi-gigabyte candidate. Expose catalog/path/readiness and hardware recommendations to the app, and report live download progress. Add task-specific adapter paths only where the installed runtime and verified artifacts support them; never reshape incompatible embeddings or silently change an index's model identity. Conditional models remain explicitly experimental; gated IndicConformer and cloud-only Gemini are cataloged as unavailable through local weight downloads. Do not make a legal-clearance claim or enable a conditional model as a paid-release default. Add focused isolated tests and stop for user acceptance before packaging or platform-release claims.

This stage was explicitly requested independently of pending Stage 2A acceptance. No default model changes, new remote media processing, or full-library reindex are authorized by this stage.

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
