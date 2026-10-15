# Adapter Workbench

The workbench operates on one enabled configured source. Stage 01 returns a
read-only sample of at most 25 media names. Stages 02 and 03 process every
supported media file recursively under the configured source; they return
bounded result details and never persist to SQLite. Stage 04 transcribes all
videos in the configured source only when Whisper and its verified base
checkpoint are already available; it never downloads or persists transcripts.
Stage 05 processes every image in the configured source when the required local
runtimes and verified model weights are available; it uses disposable storage,
returns bounded details, and persists nothing. The page lists model presence and offers a button to start the app-managed
verified downloads; live model states and errors appear in the setup log. The
preview itself remains offline. Settings links to the configured model and
detector options. Stage 09 remains disabled pending review. The API confines file operations
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
| 05 Image visual | Conditional; every image in configured source | Requires cached, verifiable CLIP and RT-DETR weights/runtimes; object detection is forced on for this stage without changing the app-wide setting. Optional face recognition follows Settings. Copies supported images into disposable storage, processes them in one pipeline run, and returns at most 25 bounded embedding, object-tag, face, and detector-status details without persistence. |
| 06 Complete video keyframe processing | Conditional; every video in configured source | Runs shot selection, decode/cache, frame embeddings, and forced RT-DETR object plus FaceNet face detection on extracted keyframes, returning normalized face bounding boxes, in one isolated pipeline run. Copies videos and verified model weights to disposable storage, returns at most 25 video details with bounded shot/keyframe lists, and persists nothing. Requires cached CLIP, RT-DETR, and FaceNet weights/runtimes; shot detection is checked when enabled. |
| 07 Finalization | Conditional; one selected sample | Runs local SQLite scan completion and index-version commit in disposable state; the live index is unchanged. Requires the same cached local models as indexing. |
| 08 Qdrant export | Conditional; every supported image and video in configured source | Runs the pipeline on disposable copies of the complete source and exports image, video-frame, and face vectors into embedded Qdrant storage under the temporary workspace. Requires local indexing models and qdrant-client; when model weights are missing, an explicit prepare-and-run button starts verified setup (up to ~1.9 GB) before the full-source preview. It never connects to or changes the configured/live Qdrant store. |
| 09 Optional captions | Disabled pending review | Not available in this checkpoint. |

Stage 09 remains disabled pending review. Whole-source stages return at most
25 detail rows; Stage 04 returns at most 10 video summaries and 20 bounded
segments per video, with relative names only. Stage 06 returns at most 25 video
summaries and 100 shots/keyframes per video; videos over 2 GiB are rejected.
