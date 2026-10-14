# Local development

## One-time setup

From the repository root:

```bash
bash scripts/dev-setup.sh
```

This provisions the pinned project Python and Node major versions, creates the
`.venv`, installs the API/test requirements, installs the UI dependencies, and
opens the project development shell. It is safe to re-run. Do not use the
system-installed app's Python environment for repository development.

## Run the app with live reload

Use separate terminals so logs for each process remain visible.

**Terminal 1 — API/backend** (FastAPI and embedded Qdrant):

```bash
./scripts/dev-api.sh
```

The API reads the repository `config.yaml` and binds to its configured local
host/port (8500 in the checked-in development config). Uvicorn watches Python
and YAML files and restarts the backend when they change. Logs are printed here
and under `logs/`.

**Terminal 2 — client/UI** (Vite):

```bash
./scripts/dev-ui.sh
```

Open <http://localhost:5173>. Vite hot-reloads UI edits and proxies API/WebSocket
requests to the development backend. Override the proxy target with
`VITE_API_ORIGIN` if the backend port differs.

**Terminal 3 — one indexing run** (optional):

```bash
./scripts/dev-indexer.sh
./scripts/dev-indexer.sh --media-source-override /path/to/media
```

This runs the indexer in the foreground; its output stays in that terminal.
You can also start indexing from the Indexer page in the UI. Indexing is a job,
not a persistent service.

## What is and is not a separate service

The app does not run one daemon per metadata or AI feature. The long-running
processes are the API/backend and (during development) the Vite client. Qdrant
is embedded in the API process. The indexer is invoked as a job by the API or
CLI. EXIF, video metadata, timestamps, GPS, thumbnails, shot/keyframe extraction,
object labels, faces, transcripts, and captions are processing stages inside
that job; they are not independent servers. Captioning starts its isolated MLX
worker only when requested. Run the API and indexer commands above to see their
logs rather than starting fictitious per-stage daemons.

## Model files

Model weights are runtime assets, not source code. They are excluded by the
root `.gitignore` rule `/models/` and must not be committed. With `MSA_DEV=1`,
the checked-in development config resolves `models_dir: models` to the ignored
repository `models/` folder. Core model setup downloads CLIP, RT-DETR, and
facenet-pytorch weights there when the backend starts. Whisper base is fetched
there on first transcription. SmolVLM2 is separate: its offline worker needs
`MSA_CAPTION_PYTHON` and `MSA_CAPTION_CACHE_DIR`; point the latter at
`$PWD/models/caption-hub` when using the repository-local cache.

Each developer must provision weights locally; Git only carries the model IDs,
versions/revisions, and setup code. For this checkout the ignored `models/`
folder contains CLIP, RT-DETR, FaceNet, Whisper base, and the cached SmolVLM2
snapshot. New checkouts should first run the backend online to provision core
weights; run transcription once to fetch Whisper. Caption weights need to be
provided to the local Hugging Face cache before using the offline caption task.

## Logs and stop

Stop a foreground process with Ctrl+C in its own terminal. Backend/API and
indexer output is visible in the terminal that started each. Application log
files are under the repository `logs/` directory in development mode. There is
no separate Qdrant process to stop.
