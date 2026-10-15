# Visual-search embedding model selection

**Status:** Draft for owner review; implementation has not started.
**Scope:** First model-selection slice: visual search embeddings only. Other model tasks remain separate work.

## Decision summary

Add a purpose-first **Visual search** selector that chooses the model used for both indexed image/keyframe embeddings and text-query embeddings. Downloads continue from the provider using the catalog's pinned repository revision or artifact URL and are stored under the app-managed models directory. A selected model is not active for search until its weights are verified and a complete candidate index has been built and validated.

Keep the current default unchanged until the user explicitly selects another model. Do not expose a model as commercially cleared merely because it downloads, loads, or passes inference tests.

## Current constraints

- The production `ClipEmbedder` uses OpenCLIP and currently loads the configured `model_name`/`pretrained` pair. The settings API treats those fields as read-only.
- The catalog's OpenAI CLIP checkpoints use Hugging Face Transformers format; the existing OpenCLIP path does not load them. A Transformers-backed CLIP adapter is the proposed compatibility path. It must pass local image-and-text inference tests before its entries become selectable.
- SigLIP2 remains disabled until its checkpoint/config shape mismatch is resolved and verified. Gemini Embedding 2 is hosted-only and is outside this local/offline slice.
- The text query encoder and indexing embedder must use the same model identity and preprocessing semantics.
- SQLite is the canonical embedding store. Image and keyframe embedding rows are keyed by media/keyframe, contain a dimension and model string, and are replaced on re-embedding. An in-place model switch could therefore expose mixed identities or dimensions during a partial reindex.
- The catalog's license fields are upstream claims. Current review-required/conditional states are not legal clearance.

## User experience

In Settings, show a **Visual search** purpose label and a dropdown with human-readable model names. Do not lead with repository URLs, tensor filenames, hashes, or hardware details; keep those in optional technical/license details.

For each option, show a concise purpose/status. Clearly distinguish:

- current model (used by the active index);
- selected model (requested for the next index);
- downloaded and checksum-verified;
- compatible adapter available;
- license status (including “not commercially cleared”).

Selecting an uninstalled candidate offers its pinned provider download. It does not immediately change search behavior. Activation requires an explicit **Build index with this model** action. Disable this action during another indexing run. If upstream terms permit evaluation but commercial clearance is unreviewed, require an evaluation-only acknowledgment and keep the model marked “Not commercially cleared”; an acknowledgment does not grant rights.

### Progress

Show honest phases: **Downloading**, **Verifying**, **Loading**, **Rebuilding index**, **Activating**, and **Ready** (or a recoverable **Failed** state). During download show actual bytes/total and percent when known. During verification/loading show an indeterminate progress indicator unless a real denominator exists. During reindex show processed/total media and keyframes, with ETA only when measured throughput supports a useful estimate. Preserve progress across UI refreshes and app restarts where the underlying operation can resume; never invent percentages.

## Model and index lifecycle

1. Resolve the selection only through the pinned internal registry; do not accept arbitrary repository IDs, URLs, or local paths from the UI.
2. Download provider files to the registered app-owned model path, verify expected size and SHA-256, then load locally with network access disabled for inference.
3. Create a candidate SQLite database using SQLite's backup API so a live database/WAL is copied safely. Keep the current database and its search model active while rebuilding.
4. Re-embed every in-scope image and video keyframe using the candidate model. Use a stable identity derived from model ID, provider revision, artifact hashes, adapter/backend version, output dimension, and preprocessing version—not a display label or a manually reused constant.
5. Validate that all candidate embeddings have the expected identity and dimension, that the candidate index is complete, and that its derived vector collection (if used) has a model-specific namespace and matching dimension.
6. Only after validation, atomically switch the app's active-index/model pointer. Retain the previous index for rollback; do not delete it automatically. On failure or interruption, keep serving the old index and report the failed phase.
7. Load the text-query encoder from the active index manifest, not from a pending UI selection. If model identities do not match, disable semantic search with an actionable error instead of comparing incompatible vectors.

This requires an ADR-level decision for safe active-index switching and model identity before implementation. The implementation must reuse the existing SQLite canonical-store contract and avoid an in-place reindex that can mix dimensions.

## Initial compatibility boundary

The first implementation is limited to local visual-embedding candidates. CLIP ViT-B/32 and ViT-L/14 may be enabled only after the new Transformers adapter passes image/text inference, dimension, and local-only tests against their pinned snapshots. SigLIP2 stays visible as unsupported with a reason until its compatibility failure is resolved. Hosted-only Gemini is not offered as a local indexing model. Object detection, faces, transcription, captions, and video-understanding selectors are explicitly out of scope for this slice.

## Licensing boundary

This feature does not perform legal clearance and does not change any catalog clearance status. Maintain separate facts for artifact hash verification, adapter/inference support, upstream license claims, and reviewed commercial-use/redistribution permission. Only use an unreviewed model for development evaluation when its upstream terms allow that evaluation; require an explicit acknowledgment and keep it marked “Not commercially cleared.” The acknowledgment does not grant rights. A commercial release gate must require documented review of the exact pinned weights, runtime/dependencies, attribution, redistribution rights, and applicable restrictions. Provider-hosted downloads do not bypass commercial-use obligations.

## Validation and acceptance

- Unit-test the Transformers adapter with deterministic local test doubles/fixtures; do not download real weights in routine tests.
- Verify image and text vectors have equal expected dimensions and finite values, and that the same selected identity is recorded for images and keyframes.
- Test candidate-index construction and activation with temporary SQLite databases: success switches active identity; load, verification, incomplete-run, or activation failure leaves the old active index intact.
- Test API/UI selection, evaluation acknowledgment, unsupported-model states, provider download phases, checksum failure, restart-visible progress, and accessible progress indicators.
- Manual acceptance on macOS: use a disposable profile and copied media fixture; select CLIP ViT-B/32 or ViT-L/14; observe provider download, verification, local model load, and index rebuild; confirm semantic search works with the same active identity; interrupt/fail a second candidate build and verify the existing index still searches; confirm the UI never labels the model commercially cleared.
- No live index or source media may be used for tests or acceptance runs.

## Non-goals

- Changing the current default or silently switching an existing index.
- Enabling every catalog entry or adding selectors for unrelated model tasks.
- Hosting model inference remotely, bundling weights, changing user media, or making legal determinations.
- Enabling SigLIP2 before its shape/load issue is independently resolved.
