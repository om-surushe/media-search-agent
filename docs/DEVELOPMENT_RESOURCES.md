# Portable development resources

This guide collects the repository, toolchains, test fixtures, model assets, and download procedures needed to continue development on another workstation or a cloud Linux runner. It describes the current photo/video product only. Research references at the end are **not** dependencies or approval to expand product scope.

No model weights, user media, application index, or local caches belong in Git. Downloads below are opt-in except for the core models, which the development API provisions on first startup. Check the model card and `NOTICE` before redistributing any weights.

## Clone this branch

The current development branch is [`feature/modular-index-stages`](https://github.com/om-surushe/media-search-agent/tree/feature/modular-index-stages):

```bash
git clone --single-branch --branch feature/modular-index-stages \
  https://github.com/om-surushe/media-search-agent.git
cd media-search-agent
git branch --show-current
```

The branch advances as work is committed. For an exact snapshot, use the commit shown in the repository's GitHub history. Git tracks the source, lockfiles, and public test fixtures; model weights, virtual environments, personal media, and local indexes are ignored. There are no Git LFS model assets to fetch.

## Supported development environments

| Environment | Support and limits |
|---|---|
| Apple Silicon macOS | Supported; `scripts/dev-setup.sh` provisions the development environment. The isolated MLX caption worker requires Apple Silicon and macOS 14+. |
| Linux x86_64 / Ubuntu / WSL2 | Supported; bootstrap expects `apt` and `sudo`. CPU tests and web development work on a Linux cloud VM. |
| Windows native | Not the source-development path; use WSL2 Ubuntu. Windows-native installer checks have separate workflows. |
| Codex Cloud / other restricted Linux | Use a Linux x86_64 image with Python 3.12, Node 20, network access to package/model hosts, and the system tools needed by tests. If the image has no `sudo`, preinstall tools or follow the CI recipe below. It cannot validate Apple Metal/MLX or macOS desktop packaging. |

Pinned tool versions are maintained in [`scripts/versions.env`](../scripts/versions.env): Python 3.12.8, uv 0.13.0, Node 20, ExifTool 13.55, and MediaInfo platform-specific versions. `scripts/dev-setup.sh` obtains and configures these tools; `scripts/lib/tools.sh` contains the pinned ExifTool install logic, while macOS obtains MediaInfo through Homebrew. PyAV wheels bundle FFmpeg libraries for normal Python video/audio processing; Linux CI additionally installs the `ffmpeg` command for its integration tests.

Tool sources and the bootstrap path:

| Tool | Download/source | Repository handling |
|---|---|---|
| uv and standalone Python | [uv releases](https://github.com/astral-sh/uv/releases), [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | `scripts/dev-setup.sh` / platform setup scripts use the pinned versions in `scripts/versions.env`. |
| Node.js | [Node.js downloads](https://nodejs.org/en/download) | Bootstrap provisions the supported Node 20 major; UI packages are then installed from the checked-in npm lockfile. |
| ExifTool | [ExifTool](https://exiftool.org/) / [pinned source tag](https://github.com/exiftool/exiftool/tree/13.55) | `scripts/lib/tools.sh` installs/checks version 13.55. |
| MediaInfo | [MediaInfo downloads](https://mediaarea.net/MediaInfo/Download) | macOS uses Homebrew; Linux bootstrap uses system packages. Versions are in `scripts/versions.env`. |
| FFmpeg | [FFmpeg](https://ffmpeg.org/download.html) | PyAV wheels bundle the libraries used by normal app code; Linux CI installs the command-line tool for integration tests. |

Dependency manifests are the source of truth—do not install every file indiscriminately:

| Resource | Manifest / lock | Use |
|---|---|---|
| Shared Python app runtime | `requirements-api.txt` | Runtime dependencies shared by platform setup paths. |
| Linux/WSL2 CPU wheels | `requirements-linux-cpu.txt` | CPU-only torch/torchvision overlay; `scripts/dev-setup.sh` installs it with the PyTorch CPU index first. |
| Windows native CUDA | `requirements-windows.txt` | Windows runtime manifest; installer selects compatible CUDA torch/torchvision first. |
| General local development | `requirements.txt` | Runtime plus notebook/developer extras; broader and less pinned than the platform lock. |
| CI/test environment | `tests/requirements-ci.txt` | Minimal CI imports/test dependencies; CI installs FaceNet separately with `--no-deps`. |
| Apple Silicon API/dev | `requirements-api-macos-arm64.lock`, `requirements-dev-macos-arm64.lock` | Generated CPython 3.12 / macOS arm64 transitive pins. Regenerate only with `scripts/lock-macos-arm64.sh`. |
| MLX caption worker | `requirements-caption-macos-arm64.in`, `requirements-caption-macos-arm64.lock` | Separate Apple Silicon/macOS 14+ environment. |
| React web UI | `src/msa_apps/ui/package.json`, `src/msa_apps/ui/package-lock.json` | `npm ci --prefix src/msa_apps/ui`. |
| Optional Tauri shell | root `package.json`/`package-lock.json`, `src-tauri/Cargo.toml`/`Cargo.lock` | Desktop shell; not required for API, web UI, or standard tests. |

Apple Silicon Python dependencies are locked in the two macOS arm64 lockfiles; the caption worker has its own lock. Generic Linux dependency manifests have broader version ranges, so use the CI workflow when you need the repository's Linux test recipe.

### Standard developer setup

Install Git and, on macOS, Xcode Command Line Tools and Homebrew. Then:

```bash
bash scripts/dev-setup.sh
```

The idempotent bootstrap installs/checks system tools, provisions the repository Python environment and UI dependencies, and enters the development shell. It needs network access. It does not copy or index media. The checked-in development `config.yaml` has `media_sources: []` and keeps generated state in ignored repository-local directories.

For hot-reload development, run the API and Vite client in separate terminals:

```bash
./scripts/dev-api.sh
./scripts/dev-ui.sh
```

Open <http://127.0.0.1:5173>. Vite proxies API calls to the backend; navigation requests remain on the SPA so direct routes work. For a single-command, user-like local run, use `./scripts/start.sh`; it serves the built UI from the API and opens the browser. Stop the dev servers first because both modes use the configured API port.

**Starting the API starts the core-model setup manager**, which downloads missing CLIP, RT-DETR, and FaceNet weights into the configured `models/` cache. If you only want tests and do not want model downloads, do not start the API; run tests directly. The `MSA_SEARCH_BROWSE_READ_ONLY=1` mode also suppresses automatic model setup.

### CI/cloud test environment

The maintained Linux quick-test job is [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). On a prepared Python 3.12 / Node 20 Linux image, its essential dependency/test steps are:

```bash
python -m pip install --upgrade pip
grep -v '^facenet-pytorch' tests/requirements-ci.txt \
  | python -m pip install -r /dev/stdin
python -m pip install 'facenet-pytorch>=2.6.0' --no-deps
python -m pip install -e .
npm ci --prefix src/msa_apps/ui
npm test --prefix src/msa_apps/ui
python -m pytest tests/ -v -m 'not slow'
```

On a fresh Ubuntu host, the CI job also installs `ffmpeg` and `mediainfo`, and stages the pinned ExifTool version from `scripts/versions.env`. The test requirements intentionally install `facenet-pytorch` separately with `--no-deps` so it cannot replace the selected PyTorch build. The repository runner `bash scripts/run-tests.sh` uses an existing `.venv` (or system Python) and **does not install packages** unless passed `--install`; avoid `--install` unless you intend to change that environment.

The UI can also be checked independently:

```bash
npm ci --prefix src/msa_apps/ui
npm test --prefix src/msa_apps/ui
npm run build --prefix src/msa_apps/ui
```

The UI lockfile is `src/msa_apps/ui/package-lock.json`. The root `package-lock.json` is for the optional Tauri desktop shell; `npm run dev` at the repository root is not the Vite web-UI command. Native desktop builds additionally need Rust/Tauri platform prerequisites; see `src-tauri/Cargo.toml` and the desktop ADRs.

## Model and runtime assets

Model files are downloaded to ignored local caches, normally under the development `models/` directory. The app's downloader verifies the CLIP checksum, uses a pinned RT-DETR revision and Hugging Face integrity checks, and relies on the respective library's integrity check for FaceNet. Approximate sizes are from project configuration/docs and can vary by cache format.

| Asset | Current use and source | How to obtain it | License / portability note |
|---|---|---|---|
| CLIP ViT-L-14, `openai` | Default image/text semantic embedding model. [Checkpoint card](https://huggingface.co/timm/vit_large_patch14_clip_224.openai); setup code records the SHA-256 and stores it under `models/clip/` (~850 MB). | Start `./scripts/dev-api.sh` with network access and normal writable development configuration. The startup model manager invokes `open_clip`; no separate manual download is required. | `NOTICE` describes the OpenCLIP software license; the checkpoint card currently labels its weights Apache-2.0. Recheck the card at download time; do not assume a code license alone covers a checkpoint. |
| RT-DETR `PekingU/rtdetr_r18vd` | Default object detector (~81 MB). [Model card](https://huggingface.co/PekingU/rtdetr_r18vd). Revision `ac77a11ff0170a41b771c03264987f8ce2b0d753` is pinned in `src/msa_apps/search_api/setup_models.py`; cache: `models/rtdetr/`. | Same API-startup setup manager; it fetches processor config and weights through Transformers/Hugging Face Hub. | Model card and `NOTICE` identify Apache-2.0. Alternatives in `config.yaml` comments are not preselected. |
| facenet-pytorch / VGGFace2 | Default face detector/recognizer (~108 MB). [Project](https://github.com/timesler/facenet-pytorch); cache: `models/facenet_pytorch/`. | Same API-startup setup manager; `TORCH_HOME` is redirected to the app-owned model directory. | `NOTICE` records the library/weights terms and VGGFace2 provenance. Review it and upstream terms before commercial redistribution. Optional InsightFace weights are marked non-commercial in `NOTICE`; do not select or download them for commercial use. |
| Whisper `base` | Optional local speech transcription; disabled by default. [OpenAI Whisper](https://github.com/openai/whisper); exact checkpoint URL/hash is in `NOTICE` and `src/msa_indexer/models/asr.py`; cache: `models/whisper/` (~145 MB). | See the explicit prefetch command below, or allow a copied test video with audio to trigger the app's lazy download. | Download is lazy; inference is local/offline afterward. Source and checkpoint terms are recorded in `NOTICE`. Do not enable it for a real media root just to test setup. |
| SmolVLM2 MLX `mlx-community/SmolVLM2-500M-Video-Instruct-mlx` | Optional offline caption worker; separate from the API environment. [Model card](https://huggingface.co/mlx-community/SmolVLM2-500M-Video-Instruct-mlx). Cache: `models/caption-hub/`. | See the Apple Silicon-only environment and prefetch commands below. | The setup script installs packages only; it does **not** fetch weights. The model card labels the checkpoint Apache-2.0. The repo currently identifies the model by ID rather than pinning a Hub revision; record the resolved revision for release-grade reproducibility. Not available on generic Linux/Codex Cloud. |

Core models are roughly 1 GB combined by the sizes above; full application packages and caches need more disk. The installation guide estimates about 5 GB free for an end-user installation. Allow extra space for Python/Node environments, wheel caches, and optional caption weights. Do not commit or sync the `models/` folder; provision each device locally from the sources above.

### Explicit optional model downloads

Run these from the repository root only when you intentionally want the asset. The Whisper command mirrors the app's model loader and stores the base checkpoint in the ignored development cache:

```bash
.venv/bin/python - <<'PY'
import whisper
whisper.load_model("base", device="cpu", download_root="models/whisper")
PY
```

The caption worker needs a separate environment and checkpoint fetch. On Apple Silicon/macOS 14+:

```bash
./scripts/setup-caption-env.sh
.venv-caption/bin/python - <<'PY'
from pathlib import Path
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="mlx-community/SmolVLM2-500M-Video-Instruct-mlx",
    cache_dir=str(Path("models/caption-hub").resolve()),
)
PY
export MSA_CAPTION_PYTHON="$PWD/.venv-caption/bin/python"
export MSA_CAPTION_CACHE_DIR="$PWD/models/caption-hub"
```

`setup-caption-env.sh` installs packages only. The explicit `snapshot_download` is required because caption inference is offline and refuses to fetch missing weights.

### Research references (not installed or integrated)

These were discussed as possible future directions, not current LMI requirements:

- **DigUp** — reference application for local semantic search: [repository](https://github.com/ARahim3/DigUp). To inspect separately: `git clone https://github.com/ARahim3/DigUp.git /tmp/DigUp-reference`. Do not clone it into this project or copy its user data.
- **EmbeddingGemma 2** — optional multimodal embedding candidate: [official model card](https://huggingface.co/google/embeddinggemma-2). The card currently labels it Apache-2.0. The checkpoint has about 744M parameters; the repository cache may be several GB. Only fetch it for an intentional isolated evaluation, not into the production model cache.
- **AirLLM** — inference framework, not an embedding model or indexer: [upstream repository](https://github.com/lyogavin/airllm). It is not a project dependency. To inspect without changing this environment, clone it separately: `git clone https://github.com/lyogavin/airllm.git /tmp/airllm-reference`. Any evaluation should use a separate environment and a separately licensed model checkpoint; its layer-streaming approach trades memory for disk I/O and latency.
- **MLX / MLX-VLM** are used only by the optional caption worker and are pinned in `requirements-caption-macos-arm64.in`; **llama.cpp** ([upstream](https://github.com/ggml-org/llama.cpp)) is not configured in this repo. The existing MCP SDK/server setup is documented in [`docs/MCP.md`](MCP.md) and is not an extra asset required for this branch's tests.

For an intentional EmbeddingGemma 2 evaluation, use the installed Hugging Face client to keep files in a separate ignored research cache:

```bash
.venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="google/embeddinggemma-2",
    cache_dir="models/research/embeddinggemma-2",
)
PY
```

This candidate is not part of LMI and is not compatible with existing CLIP indexes without a separately approved reindex/migration plan.

A library's license does not automatically settle the license for its pretrained weights or training data. Before shipping model weights, verify the exact repository revision, model card, source license, attribution/notice requirements, and any dataset or biometric restrictions. See [`NOTICE`](../NOTICE); it is project guidance, not legal advice.

## Test data and privacy boundaries

- Normal unit tests create temporary databases and copied test inputs; they do not need the installed app's index or a personal media library.
- Public integration fixtures are committed under `tests/real_media/fixtures/` with provenance in [`tests/real_media/THIRD_PARTY_MEDIA.md`](../tests/real_media/THIRD_PARTY_MEDIA.md). They are ordinary Git files, not Git LFS. Use copies or the provided isolated harness for tests that write state.
- `data/sample_photos/` is not tracked and is not required for the standard unit/UI test path. Some legacy tests skip when it is absent. Do not copy private test media into a commit or cloud workspace.
- Slow model-backed tests require the model caches above and can be expensive on CPU. The isolated public-fixture harness is available as `bash tests/real_media/run-local.sh --report-dir .artifacts/real-data`; run it intentionally, with network/cache/disk available. It uses public fixtures and an isolated workspace, not a user's indexed library.
- A cloud run can validate Linux CPU/unit/UI behavior, but not Apple MPS, MLX caption inference, native macOS packaging, or GPU-specific performance. Keep private source paths, user indexes, and model caches out of shared cloud workspaces.

## Further references

- [Local development](DEVELOPMENT.md) — service processes, config, logs, and cache layout.
- [Installation](INSTALL.md) — supported packaged platforms and troubleshooting.
- [Test README](../tests/README.md) and [CI workflow](../.github/workflows/ci.yml) — test tiers and maintained Linux commands.
- [Video indexing](VIDEO_INDEXING.md) — frame cache, preview, benchmark, and acceptance steps.
