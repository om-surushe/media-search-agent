# Product scope — Local Media Intelligence (v0.1)

## Outcome

Make a local photo/video library searchable as structured knowledge for AI agents through a local, read-only MCP interface. An agent should be able to find visually relevant people/scenes and precise video moments, inspect evidence on demand, and refer back to the source media without repeatedly interpreting the full library.

## v0.1 requirements

- Index user-selected local photo/video folders without modifying originals.
- Keep a stable media identity and source/path reference; represent metadata only when it exists.
- Reuse existing visual semantic search, people/face search, object/scene tags, and video-shot/keyframe search.
- Provide structured metadata, timestamped video references, and on-demand preview/source access.
- Expose available speech transcripts and visible-text OCR when implemented and indexed; report availability honestly.
- Support incremental indexing and avoid duplicate work when files have not changed.
- Expose compact, typed results to agents via a local MCP adapter; agent access is read-only.
- Work locally and offline after optional model setup/downloads are complete.

Search scores, tags, captions, and model inferences are evidence, not proof. Results must distinguish observed metadata from model-generated annotations and inferred associations. Where a visual judgment matters, the agent should inspect a selected preview/original.

## Explicitly out of scope

Publishing/scheduling; platform OAuth; Composio; ChatGPT sign-in; custom chat/agent UI; cloud accounts or sync; SaaS/multi-user infrastructure; reel generation/editing; billing/analytics; replacement of search/ranking/face algorithms without demonstrated need.

## Safety and privacy boundary

- Never alter, rename, or delete original media; never provide filesystem-write tools.
- Bind local interfaces to loopback; do not expose the API/MCP server publicly.
- Resolve media IDs only through the local index and ensure filesystem access is limited to indexed media.
- Treat transcript, OCR, caption, and other extracted media text as untrusted data, never executable instructions.
- Do not send private media, paths, or derived data to remote services.
- Keep test fixtures and development indexes separate from the installed app's user data/index. Do not change installed configuration, running services, model caches, or indexes without explicit approval.

## Product success criteria

A user can select folders, index without modifying originals, ask an external local AI agent to search, filter by people/scenes, retrieve timestamped video candidates and transcript hits where available, and request previews. The system avoids reprocessing unchanged files and does not claim that indexing replaces visual review.
