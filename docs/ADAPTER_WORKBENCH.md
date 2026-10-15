# Adapter Workbench

The workbench operates on one enabled configured source. Stage 01 returns a
read-only sample of at most 25 media names. Stages 02 and 03 process every
supported media file recursively under the configured source; they return
bounded result details and never persist to SQLite. Stage 04 transcribes all
videos in the configured source only when Whisper and its verified base
checkpoint are already available; it never downloads or persists transcripts.
Stages 05–09 remain disabled pending review. The API confines file operations
to the configured root, rejects traversal/escaping symlinks, and never returns
absolute paths. Whole-source identity hashing can take time, so the UI confirms
before starting it.

## Current stage boundaries

| Stage | Workbench behavior | Boundary |
|---|---|---|
| 01 Discovery | Runnable; bounded, read-only sample | Enumerates supported media only. |
| 02 Identity | Runnable; hashes the whole configured source | Uses SHA-256 and file stats for every media file; returns at most 25 result details and intentionally does not read or modify live SQLite fingerprints. |
| 03 Metadata | Runnable; extracts metadata from the whole configured source | Read-only extraction for every media file; returns at most 25 result details and performs no SQLite, thumbnail, or cache persistence. |
| 04 Transcription | Conditional | Requires cached Whisper base weights; verifies and copies them to a temporary cache, transcribes all videos from disposable copies, and returns bounded details without persistence. |
| 05 Image visual | Disabled pending review | Not available in this checkpoint. |
| 06 Complete video keyframe processing | Disabled pending review | Not available in this checkpoint; full coupled keyframe processing remains one stage. |
| 07 Finalization | Disabled pending review | Not available in this checkpoint. |
| 08 Qdrant export | Disabled pending review | Not available in this checkpoint. |
| 09 Optional captions | Disabled pending review | Not available in this checkpoint. |

Stages 05–09 will be enabled one at a time after review. Whole-source stages
return at most 25 detail rows; Stage 04 returns at most 10 video summaries and
20 bounded segments per video, with relative names only.
