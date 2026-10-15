# Indexer adapter stages

Numbered modules follow runtime stage order. Stages 02–08 are extracted one at a time; the pipeline coordinator and SQLite storage remain in `pipeline.py` and `db/`.

1. `adapter_01_discovery.py` — scan validated sources, collect stat snapshots, and order the worklist.
2. File identity and incremental gates — fingerprint/hash, duplicate/move handling, and per-stage skip decisions.
3. Common enrichment — EXIF/video metadata, GPS/location, and thumbnails.
4. `adapter_04_transcription.py` — optional local Whisper transcription.
5. `adapter_05_image_visual.py` — isolated image embeddings, enabled object/face enrichment, and status output.
6. `adapter_06_video_keyframes.py` — the complete shot-to-keyframe unit, including selection, decode/cache, per-frame embeddings and enabled object/face/GPS enrichment.
7. `adapter_07_finalization.py` — inspect scan completion and index-version commit in disposable SQLite.
8. `adapter_08_qdrant_export.py` — export the disposable whole-source index to a temporary Qdrant store.
9. `adapter_09_optional_captioning.py` — optional image/video captions in an isolated index/cache workspace.

Workbench folder previews 05–09 process every supported file in the configured source, copying media and required cached models into a disposable workspace before running the normal coordinator against temporary SQLite/cache paths. Single-file helpers are used only by stages with an explicit per-file preview. Stages 05–08 include their isolated prerequisites so the selected stage has real output to inspect. No live Qdrant handoff/export runs in this sandbox; stage 08 uses an explicit temporary Qdrant path.

`model_adapters.py` contains shared CLIP/Whisper constructors; it is infrastructure, not a numbered indexing stage. `models/providers.py` remains a compatibility re-export.
