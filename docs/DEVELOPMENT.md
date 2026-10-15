# Local development

## One-time setup

From the repository root:

```bash
bash scripts/dev-setup.sh
```

This provisions the pinned project Python and Node major versions, creates the
`.venv`, installs the API/test requirements, installs the UI dependencies, and
opens the project development shell. On Apple Silicon macOS, setup syncs the
version-locked API/dev set; other platforms still use their existing manifests.
Do not use the installed app's Python environment for normal repository work.
Use `MSA_DEV_VENV_DIR` only as a deliberate override. For a fresh branch clone,
exact model download commands, public test fixtures, and cloud setup limits, see
[Portable development resources](DEVELOPMENT_RESOURCES.md).

## Caption worker environment

On macOS Apple Silicon 14+, provision the separate MLX environment once:

```bash
./scripts/setup-caption-env.sh
```

The API runner automatically uses `.venv-caption/bin/python` when present and
defaults its model cache to the ignored `models/caption-hub/`. Model weights
are separate from Python packages; this setup does not download SmolVLM2.

Regenerate the checked-in Apple Silicon locks after changing requirement
inputs with `./scripts/lock-macos-arm64.sh`. The caption lock is generated on
the current Mac because MLX wheel availability depends on the host macOS ABI.

## Run the app

For a single-command, user-like local launch, run `./scripts/start.sh`. It serves
the built UI from FastAPI and opens the browser; `--no-prewarm` skips model
pre-warming and `--no-browser` is useful on headless hosts.

For hot-reload development, use separate terminals so logs for each process
remain visible:

**Terminal 1 — API/backend** (FastAPI and embedded Qdrant):

```bash
./scripts/dev-api.sh
```

The API reads the repository `config.yaml` and binds to its configured local
host/port (8500 in the checked-in development config). Uvicorn watches Python
and YAML files under the backend source packages. Restart the API after editing
root `config.yaml`; source-only watches avoid scanning local environments and
model caches. Logs are printed here and under `logs/`.

**Terminal 2 — client/UI** (Vite):

```bash
./scripts/dev-ui.sh
```

Open <http://127.0.0.1:5173>. Use this explicit IPv4 URL to avoid another
local app bound to IPv6 `localhost`. Vite hot-reloads UI edits and proxies
API/WebSocket requests to the development backend. Override the proxy target with
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
