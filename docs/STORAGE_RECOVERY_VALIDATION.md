# Storage recovery release validation

SQLite is canonical for metadata and embeddings; embedded Qdrant is a derived search index and can be recreated with `msa index export --recreate`. Recovery is not release-validated until the end-to-end test below passes on each supported release target.

## Automated end-to-end test

Run from the repository root in an installed development environment with the checked-in real-media fixtures and CLIP model available:

```bash
pytest -q -m slow tests/test_cmd_index_stop.py::test_noncooperative_kill_recovers_on_restart
```

The test uses a temporary workspace and copied fixtures. It hard-kills an indexing subprocess, confirms a later indexing run recovers and exports, removes only the temporary Qdrant store while preserving SQLite, then invokes the CLI's full-rebuild path and verifies the rebuilt image collection is non-empty. Never point it at a user's index or source media.

The packaged-app release BVTs run `tests/real_media/scripts/storage_recovery.py` on each target after fixture indexing and before app startup. It guards that the configured SQLite and Qdrant paths are inside the isolated app data root, checks `PRAGMA integrity_check` and canonical row counts, deletes only that test Qdrant directory, invokes the installed `msa index export --recreate`, and requires exact pre/post image, video, and face collection point counts and unchanged SQLite rows. The existing runtime suite then checks search against the restarted app.

## Release matrix

Run against the release candidate, not only the developer checkout. Attach the command output and OS/architecture to the release record; any skipped or unavailable run remains **Release test needed**.

| Target | Required environment | Status |
|---|---|---|
| macOS | Apple Silicon, macOS 12+ | Release test needed |
| Windows | Windows 11 x86-64; CPU, and NVIDIA CUDA where available | Release test needed |
| Linux | x86-64 headless/browser install | Release test needed |

For each target, confirm the test's second export repopulates vectors after Qdrant loss and that the app can search after restart. Keep all generated SQLite/Qdrant data inside the test's temporary workspace. Do not infer platform coverage from a passing test on another OS or from a general installer BVT that does not exercise storage recovery.
