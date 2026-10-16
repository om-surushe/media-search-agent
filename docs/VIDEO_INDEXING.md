# Video frame indexing

## Responsibilities

- `msa_indexer.io.video_selection` turns shot ranges into timestamp requests. Midpoint frames remain the baseline; adaptive candidates are enabled by the Maximum Detail default and versioned.
- `msa_indexer.io.video_frames` owns temporal frame IDs, PyAV decoding, normalized JPEG renditions, checksum verification, cancellation, and bounded LRU eviction.
- `SQLiteStore` owns canonical frame/rendition metadata and append-only selection status. SQLite remains authoritative; image files are disposable.
- `pipeline.run_index` coordinates shot detection, selected-frame extraction, embeddings, object/face processing, and per-policy status. Caption workers use the same cache when available and decode from the source as a fallback.
- The loopback-only `POST /video-keyframes/preview` endpoint is a disposable preview. Its cache and selector checks use temporary data and never add the upload to the library index. The preview page is no longer part of the app UI.

## Identity, timestamps, and cache

A frame ID is derived from the source revision, stream index, and decoded PTS/time base. If timestamps are absent or ambiguous, source decode order is used as a fallback. Requested selector time is stored separately as provenance. `video_keyframes.timestamp` is the actual decoded time and is the value used for search-result playback/seek.

Rendition identity is separate from frame identity: a versioned JPEG profile can be regenerated without changing the source-frame ID. SQLite records the relative cache path, checksum, dimensions, and byte size. Reads verify the checksum and image before reuse. LRU eviction removes rendition files and rows only; it does not remove frame IDs, keyframes, captions, detections, or embeddings. The cache budget is a soft ceiling for a single rendition larger than the configured budget.

## Selection and safe policy changes

The baseline remains PySceneDetect shot segmentation and midpoint-per-shot timestamps. Maximum Detail enables `adaptive_video_keyframes_enabled`, which may append at most one additional change candidate per shot. `long_shot_coverage_enabled` is also enabled by default and considers up to two additional, novelty-gated gradual-change candidates only for shots at least 30 seconds long. Static shots remain sparse. Balanced and Fast presets can disable these extra candidates.

Adaptive policy versions include a digest of the selector and its shot/configuration settings, and are recorded in keyframe rows plus `video_keyframe_selection_state`. Baseline keyframe-count variants use separate slots; if a legacy slot would represent a different timestamp, the changed selection is appended to a separate slot. A new adaptive policy appends rows instead of replacing old rows or deleting existing intelligence. A failed build is recorded as failed and can be retried; already written valid frames remain available. This is intentionally append-only: older policy rows and search points are retained for safety. `ponytail:` pruning is deferred until rollback/history UX exists, so repeated future selector versions could grow the index.

The loopback-only `POST /video-keyframes/preview` endpoint accepts raw video bytes and can compare midpoint/adaptive selection plus optional cache behavior without production reindexing. The UI preview page has been removed; the standalone benchmark below remains available for local performance comparisons.

## Benchmark

Run a local, read-only comparison using a short test or user-approved video:

```bash
API_PY="$HOME/.local/share/local-media-intelligence/api-indexer-3.12/bin/python"
PYTHONPATH=src "$API_PY" scripts/benchmark_video_frames.py /path/to/video.mp4 \
  --samples 8 --consumer-passes 3
```

The script compares per-consumer timestamp seeks, one grouped PyAV seek pass plus cache reuse, and a single sequential decode pass. It reports decoder opens, elapsed time, peak RSS per worker, cache bytes, and verifies the source file hash is unchanged. Use a copied/synthetic fixture for development; do not point tests at the installed library.

A generated 12-second, 320x180, 24-fps clip (8 timestamps, 3 consumers) measured: independent seeks 0.313 s / 24 opens / 70.6 MiB peak; grouped PyAV and cache 0.497 s total / 1 open / 16 cache hits / 24.1 KiB cache / 86.3 MiB peak; sequential decode 0.208 s / 1 open / 62.0 MiB peak. The source hash was unchanged. This synthetic run is small and model-free; grouped caching reduced repeated opens but did not win total elapsed time after SQLite/cache setup. Maximum Detail nevertheless favors coverage; use Balanced or Fast when these additions cost too much, and evaluate with copied or user-approved videos before a full library run.

## Validation

Focused tests cover PTS/time-base identity, cache reuse/corruption/eviction/cancellation, append-only selector versions, the actual decoded timestamp through Qdrant payload and timestamped-shots API, and the preview/cache comparison endpoint.
