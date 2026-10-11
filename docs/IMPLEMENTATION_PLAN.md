# Implementation plan

This plan is gated. Complete one stage, report actual results, and stop for user acceptance before starting another. Stage 0 is the current audit; no application code or dependencies are changed in that stage.

## Stage 0 — Audit and architecture (current)

Inspect the checked-out fork, project docs, API, indexing/storage pipeline, schemas/migrations, tests, packaging, and license notices. Record existing capabilities, gaps, risks, minimal integration points, and an isolated development/test workflow in the three Stage 0 documents. Do not run indexing, install dependencies, download models, or alter application files or installed-app data. Stop for approval.

## Stage 1 — Foundation validation

On explicit approval, validate the existing checkout/workflow and baseline capabilities using the project's temporary-database fixtures and a small copied test-media fixture. Confirm folder configuration/selection, indexing, structured metadata, search, previews, people filtering, and video shots/timestamps. Use only an isolated dev config and directories; never point tests at the installed index. Fix only demonstrated blockers. Add focused tests, run them, provide exact macOS acceptance steps, and stop for user testing/approval.

## Stage 2 — Missing media intelligence

After Stage 1 acceptance, implement only proven gaps. First candidates are local Whisper speech transcription with timestamped utterances and useful frame/photo OCR; do not infer they are missing solely from empty optional indexes. Check dependency and model licenses and practical offline operation before selecting models. Persist results, extraction state, confidence where supported, and extractor/model versions in backward-compatible SQLite migrations; skip already-current work during incremental indexing. Preserve current visual search, Qdrant, and face-recognition algorithms. Add focused tests and stop for user testing/approval.

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
