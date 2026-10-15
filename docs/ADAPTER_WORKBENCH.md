# Adapter Workbench

The workbench operates on one enabled configured source. Stage 01 returns a
read-only sample of at most 25 media names. Stages 02 and 03 process every
supported media file recursively under the configured source; they return
bounded result details and never persist to SQLite. Stages 04–09 are disabled
in this checkpoint and will be enabled one at a time. The API confines file operations
to the configured root, rejects traversal/escaping symlinks, and never returns
absolute paths. Whole-source identity hashing can take time, so the UI confirms
before starting it.

## Current stage boundaries

| Stage | Workbench behavior | Boundary |
|---|---|---|
| 01 Discovery | Runnable; bounded, read-only sample | Enumerates supported media only. |
| 02 Identity | Runnable; hashes the whole configured source | Uses SHA-256 and file stats for every media file; returns at most 25 result details and intentionally does not read or modify live SQLite fingerprints. |
| 03 Metadata | Runnable; extracts metadata from the whole configured source | Read-only extraction for every media file; returns at most 25 result details and performs no SQLite, thumbnail, or cache persistence. |
| 04 Transcription | Disabled pending review | Will be enabled after stage 04 is tested and approved. |
| 05 Image visual | Disabled pending review | Not available in this checkpoint. |
| 06 Complete video keyframe processing | Disabled pending review | Not available in this checkpoint; full coupled keyframe processing remains one stage. |
| 07 Finalization | Disabled pending review | Not available in this checkpoint. |
| 08 Qdrant export | Disabled pending review | Not available in this checkpoint. |
| 09 Optional captions | Disabled pending review | Not available in this checkpoint. |

Stages 04–09 will be enabled one at a time after review. Whole-source stages
return at most 25 detail rows; file-based stages will return bounded structured
output with relative source names and no private absolute paths.
