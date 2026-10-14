# MVP delivery status

**Status: NOT TESTER-READY**

## Checkpoint

- Branch: `fix/video-indexing-and-mime`
- Earlier search-only checkpoint: `a82324c` (`feat(search): enable model-free caption scene retrieval`)
- Organization/MCP source changes are on this feature branch; app artifacts are local ignored build outputs, not release assets.
- Accepted base: `84a5da69a73bcd6e40339f587caf8b53bb3aea30`
- No original media, installed personal app, or protected app data was used or modified.

## Verified in this worktree

- Search/Browse stays model-free in read-only mode. Stored image captions, timestamped video scenes, and transcript segments have lexical retrieval paths when CLIP is unavailable; semantic availability is reported honestly.
- User-authored tags and virtual collections are persisted additively in the SQLite index and reference existing media IDs; storage does not copy, move, rename, or delete source media.
- API, UI, and MCP organization flows are implemented. MCP uses the official Python SDK over stdio; reads are available by default and organization write tools require `MSA_MCP_ALLOW_WRITES=1`.
- Backend tests: **68 passed, 2 warnings** across organization storage/API, MCP stdio-client discovery/calls/restart persistence, packaged dependency guards, search/browse, and caption/video-scene retrieval.
- UI tests: **218 passed**. Vite/TypeScript production build passed.
- Tauri built an aarch64 macOS `MediaSearchAgent.app` (64 MiB). Its ad-hoc code signature and `Info.plist` validate; the staged app resources include the MCP server source, `pyproject.toml`, `requirements-api.txt`, and `uv`. A 25 MiB `.dmg` was generated, mounted read-only, and checksum-verified by `hdiutil`. The default DMG Finder-decoration step failed in this environment, so the image was generated with `--skip-jenkins` and has no custom Finder layout/background.
- Notarization was skipped because Apple signing/notarization credentials are unavailable.
- Local, ignored build artifacts: `src-tauri/target/release/bundle/macos/MediaSearchAgent.app` and `src-tauri/target/release/bundle/dmg/MediaSearchAgent_0.5.0_aarch64.dmg`.

## Release gates still open

- **Packaged fresh-user BVT attempted and failed at startup.** Ran `tests/real_media/scripts/validate-installed-desktop-macos.sh` against the DMG in a disposable `/tmp` HOME under a sandbox denying access to the installed app/data and denying repository writes. The GUI opened, but the sidecar exited before health readiness: `cannot resolve bundled bin/uv: unknown path`; the UI reported “Could not reach the Media Search Agent backend.” No model weights were downloaded and indexing/restart checks were not reached. Logs: `/tmp/lmi-final-sprint-acceptance.aYjTUZ/desktop-bvt.log` and `.../msa-desktop-home/Library/Logs/MediaSearchAgent/app-stdout.log`. The test process and app are stopped.
- Manual browser verification of result interaction, timestamp seeking within the same video, and collection/tag workflows remains outstanding.
- No end-to-end offline acceptance or before/after original-file integrity run was performed against a fresh packaged library.
- The local `.app`/`.dmg` are not notarized; distribution/Gatekeeper acceptance is unverified. The built `.dmg` has no Finder layout embellishments.
- No public release has passed acceptance with these changes; do not assume a published installer contains them.

## Decision

Do not describe this build as tester-ready or distribute it as a release candidate until the remaining fresh-user, manual UI, offline/integrity, and signing/notarization gates have evidence. Respect the no-weight-download and protected-data constraints; if completing those gates requires model downloads or touching installed app data, obtain explicit authorization first.
