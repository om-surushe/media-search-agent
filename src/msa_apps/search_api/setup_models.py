"""
setup_models.py — First-launch model download manager.

Tracks per-model download state in a thread-safe singleton. FastAPI endpoints
read this state; a background thread does the actual downloading so the async
event loop is never blocked.

Core models downloaded automatically (optional BLIP caption weights are opt-in):
  - CLIP ViT-L-14/openai             (~1.71 GB) via open_clip / huggingface_hub
  - RT-DETR PekingU/rtdetr_r18vd       (~81 MB)  via HuggingFace transformers
  - facenet-pytorch VGGFace2           (~108 MB)  via torch hub (TORCH_HOME redirect)

Integrity: RT-DETR weights are verified by HuggingFace hub's built-in
blob-level SHA-256 during download. We pin a known-good revision for
the default model (see RTDETR_DEFAULT_REVISION) and rely on HF's
content-addressed cache rather than maintaining our own hash table.
CLIP weights are verified by a stored SHA-256. facenet-pytorch weights
are verified by torch hub's own integrity check on download.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

from msa_indexer.captioning import (
    MODEL_ID as CAPTION_MODEL_ID,
    MODEL_REVISION as CAPTION_MODEL_REVISION,
    MODEL_SHA256 as CAPTION_MODEL_SHA256,
    MODEL_WEIGHT_FILE as CAPTION_MODEL_WEIGHT_FILE,
    MODEL_WEIGHT_BYTES as CAPTION_MODEL_WEIGHT_BYTES,
    MODEL_REQUIRED_FILES as CAPTION_MODEL_REQUIRED_FILES,
    caption_model_cache_dir,
)
from msa_indexer.models.clip_artifacts import (
    CLIP_CHECKPOINT_SHA256,
    CLIP_HF_REPO,
    CLIP_MODEL_NAME,
    CLIP_PRETRAINED,
    clip_checkpoint_candidates,
)
from msa_indexer.models.commercial_registry import (
    MODELS as COMMERCIAL_MODELS,
    MODEL_BY_ID as COMMERCIAL_MODEL_BY_ID,
    model_is_installed,
    mark_model_verified,
    verify_model,
)

# ── Types ─────────────────────────────────────────────────────────────────────

ModelState = Literal["pending", "downloading", "verifying", "done", "error"]
JobState = Literal["pending", "running", "retrying", "completed", "failed"]
JOB_FILENAME = "setup-job.json"
JOB_VERSION = 1

# Pinned revision for the default RT-DETR model. HuggingFace hub verifies
# per-blob SHA-256 during download, so we don't maintain a separate hash.
# Update this constant deliberately when upgrading the default model weights.
RTDETR_DEFAULT_MODEL    = "PekingU/rtdetr_r18vd"
RTDETR_DEFAULT_REVISION = "ac77a11ff0170a41b771c03264987f8ce2b0d753"
DEFAULT_SETUP_MODEL_IDS = frozenset({"clip", "rtdetr", "facenet_pytorch", "captioning"})

MODEL_META = {
    "clip": {
        # User-facing label: lead with the purpose ("Semantic search"), keep
        # the technical name in parens for diagnosis. Same pattern for the
        # other two below. Bare technical names like "CLIP ViT-L-14" were
        # opaque to non-ML users seeing the first-launch download page.
        "label":   "Semantic search model (CLIP ViT-L-14)",
        "size_mb": 1711,
        # open_clip prefers the pinned HF safetensors artifact when available.
        "sha256": CLIP_CHECKPOINT_SHA256["open_clip_model.safetensors"],
        "filename": "open_clip_model.safetensors",
        # Download origin surfaced to the UI as a trust signal. Format is
        # "<host>/<org>/<repo>" with no scheme — short enough to fit a row,
        # specific enough to verify against the actual network traffic.
        "source":  f"huggingface.co/{CLIP_HF_REPO}",
    },
    "rtdetr": {
        "label":    "Object detection model (RT-DETR r18vd)",
        "size_mb":  81,
        # No sha256 — integrity guaranteed by HuggingFace hub blob-level verification.
        # Revision pinned via RTDETR_DEFAULT_REVISION for reproducible installs.
        "revision": RTDETR_DEFAULT_REVISION,
        "source":   "huggingface.co/PekingU/rtdetr_r18vd",
    },
    "captioning": {
        "label": "Image and video captioning model (BLIP base, CPU)",
        "size_mb": 990,
        "sha256": CAPTION_MODEL_SHA256,
        "filename": CAPTION_MODEL_WEIGHT_FILE,
        "revision": CAPTION_MODEL_REVISION,
        "source": f"huggingface.co/{CAPTION_MODEL_ID}",
    },
    "facenet_pytorch": {
        "label":   "Face detection model (facenet-pytorch)",
        "size_mb": 108,
        # Weights downloaded by torch hub; no separate hash maintained here.
        # MTCNN weights (~1 MB) are bundled in the facenet-pytorch package itself.
        # InceptionResnetV1 VGGFace2 weights (~107 MB) are fetched from the
        # timesler/facenet-pytorch GitHub release assets by torch hub on first use.
        "source":  "github.com/timesler/facenet-pytorch",
    },
}

MODEL_META.update({
    model.model_id: {
        "label": model.label,
        "size_mb": max(1, (sum(item.size_bytes for item in model.artifacts) + 999_999) // 1_000_000),
        "revision": model.revision,
        "sha256": model.artifacts[0].sha256 if len(model.artifacts) == 1 else {
            item.filename: item.sha256 for item in model.artifacts
        },
        "source": model.repo_id or model.publisher,
    }
    for model in COMMERCIAL_MODELS
})


# ── Hash verification ─────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    """Return lowercase hex SHA-256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_file(path: Path, expected: str) -> bool:
    """Return True if file exists and its SHA-256 matches expected."""
    if not path.exists():
        return False
    actual = _sha256(path)
    if actual != expected:
        logger.warning(
            "setup_models: hash mismatch for {} — expected {} got {}",
            path.name, expected[:12] + "…", actual[:12] + "…",
        )
        return False
    return True


@dataclass
class ModelDownloadState:
    status: ModelState = "pending"
    error: str | None = None
    downloaded_bytes: int = 0
    total_bytes: int = 0
    filename: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "error": self.error,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "filename": self.filename,
        }


# ── Manager ───────────────────────────────────────────────────────────────────

class SetupManager:
    """Thread-safe singleton managing first-launch model downloads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._models: dict[str, ModelDownloadState] = {
            k: ModelDownloadState() for k in MODEL_META
        }
        self._download_started = False
        self._running = False
        self._active_models: frozenset[str] = frozenset()
        self._complete = False
        self._models_dir: Path | None = None
        self._job_id: str | None = None
        self._job_models: frozenset[str] = frozenset()
        self._job_status: JobState | None = None
        self._job_created_at: float | None = None
        self._job_updated_at: float | None = None
        self._job_attempt = 0
        self._speed_bps: float | None = None
        self._last_sample_at: float | None = None
        self._last_sample_bytes: int | None = None
        self._last_persist_at = 0.0
        self._persist_lock = threading.Lock()
        self._persistent_run = False

    # ── Presence checks ───────────────────────────────────────────────────────

    def check_all_present(self, models_dir: Path) -> dict[str, bool]:
        """Check which model weight files are already on disk."""
        clip_cache = models_dir / "clip"

        # Exclude partial/lock files; readiness and the worker additionally verify the pinned hash.
        clip_present = bool(clip_checkpoint_candidates(models_dir))

        # RT-DETR: look for model.safetensors under any snapshot of the default model.
        # HuggingFace hub layout: <cache>/models--<org>--<name>/snapshots/<commit>/model.safetensors
        rtdetr_cache = models_dir / "rtdetr"
        rtdetr_slug  = "models--" + RTDETR_DEFAULT_MODEL.replace("/", "--")
        rtdetr_snapshots = rtdetr_cache / rtdetr_slug / "snapshots"
        # Require the exact pinned revision snapshot to contain both the model
        # weights and the processor config — a partial copy (weights only) would
        # cause local_files_only=True to fail when the processor tries to load
        # its config at indexer startup.
        rtdetr_snap = rtdetr_snapshots / RTDETR_DEFAULT_REVISION
        rtdetr_present = (
            rtdetr_snap.exists()
            and (rtdetr_snap / "model.safetensors").exists()
            and (rtdetr_snap / "preprocessor_config.json").exists()
        )

        caption_slug = "models--" + CAPTION_MODEL_ID.replace("/", "--")
        caption_snapshot = (
            caption_model_cache_dir(models_dir) / caption_slug / "snapshots" / CAPTION_MODEL_REVISION
        )
        caption_present = (
            caption_snapshot.is_dir()
            and all((caption_snapshot / name).is_file() for name in CAPTION_MODEL_REQUIRED_FILES)
            and (caption_snapshot / CAPTION_MODEL_WEIGHT_FILE).stat().st_size == CAPTION_MODEL_WEIGHT_BYTES
        )

        # facenet-pytorch reads TORCH_HOME directly (not torch.hub.get_dir()) and
        # writes to ${TORCH_HOME}/checkpoints — see facenet_pytorch.models.inception_resnet_v1
        # `model_dir = os.path.join(get_torch_home(), 'checkpoints')`. The download worker
        # sets TORCH_HOME=models_dir/facenet_pytorch, so weights land at
        # models_dir/facenet_pytorch/checkpoints (no /hub segment). The actual filename
        # from the release asset is 20180402-114759-vggface2.pt — "vggface2" is a
        # substring, not a prefix.
        facenet_hub = models_dir / "facenet_pytorch" / "checkpoints"
        facenet_present = facenet_hub.is_dir() and any(
            "vggface2" in f.name and f.suffix == ".pt"
            for f in facenet_hub.iterdir()
        )

        present = {
            "clip":            clip_present,
            "rtdetr":          rtdetr_present,
            "facenet_pytorch": facenet_present,
            "captioning": caption_present,
        }
        present.update({
            model.model_id: model_is_installed(model, models_dir)
            for model in COMMERCIAL_MODELS
        })
        return present

    def has_valid_clip(self, models_dir: Path) -> bool:
        """Return True only for a complete CLIP blob matching the pinned SHA-256."""
        clip_cache = models_dir / "clip"
        try:
            for path in clip_checkpoint_candidates(models_dir):
                expected = CLIP_CHECKPOINT_SHA256.get(path.name)
                if expected and _verify_file(path, expected):
                    return True
                if not expected and _sha256(path) in CLIP_CHECKPOINT_SHA256.values():
                    return True
            return False
        except OSError:
            return False

    def has_valid_captioning(self, models_dir: Path) -> bool:
        slug = "models--" + CAPTION_MODEL_ID.replace("/", "--")
        snapshot = caption_model_cache_dir(models_dir) / slug / "snapshots" / CAPTION_MODEL_REVISION
        weights = snapshot / CAPTION_MODEL_WEIGHT_FILE
        try:
            return (
                all((snapshot / name).is_file() for name in CAPTION_MODEL_REQUIRED_FILES)
                and weights.stat().st_size == CAPTION_MODEL_WEIGHT_BYTES
                and _verify_file(weights, CAPTION_MODEL_SHA256)
            )
        except OSError:
            return False

    def is_ready(self, models_dir: Path) -> bool:
        present = self.check_all_present(models_dir)
        present["clip"] = self.has_valid_clip(models_dir)
        return all(present[model_id] for model_id in DEFAULT_SETUP_MODEL_IDS)

    # ── Persistent job ────────────────────────────────────────────────────────

    @staticmethod
    def _job_path(models_dir: Path) -> Path:
        return models_dir / JOB_FILENAME

    def _progress_locked(self) -> tuple[int, int, float, float | None]:
        active = self._job_models or DEFAULT_SETUP_MODEL_IDS
        total = sum(MODEL_META[model_id]["size_mb"] * 1024 * 1024 for model_id in active)
        downloaded = 0
        for model_id in active:
            state = self._models[model_id]
            expected = MODEL_META[model_id]["size_mb"] * 1024 * 1024
            if state.status == "done":
                downloaded += expected
            elif state.status in ("pending", "downloading", "verifying"):
                downloaded += min(state.downloaded_bytes, expected)
        progress = min(downloaded / total, 1.0) if total else 1.0
        remaining = max(total - downloaded, 0)
        eta = remaining / self._speed_bps if self._speed_bps else None
        return downloaded, total, progress, eta

    def _record_sample_locked(self) -> None:
        downloaded, _, _, _ = self._progress_locked()
        now = time.monotonic()
        if self._last_sample_at is not None and self._last_sample_bytes is not None:
            elapsed = now - self._last_sample_at
            delta = downloaded - self._last_sample_bytes
            if elapsed > 0 and delta > 0:
                sample = delta / elapsed
                self._speed_bps = sample if self._speed_bps is None else self._speed_bps * 0.75 + sample * 0.25
        self._last_sample_at = now
        self._last_sample_bytes = downloaded

    def _job_snapshot_locked(self) -> dict[str, Any]:
        downloaded, total, progress, eta = self._progress_locked()
        active = self._job_models or DEFAULT_SETUP_MODEL_IDS
        return {
            "version": JOB_VERSION,
            "id": self._job_id,
            "status": self._job_status,
            "attempt": self._job_attempt,
            "created_at": self._job_created_at,
            "updated_at": self._job_updated_at,
            "downloaded_bytes": downloaded,
            "total_bytes": total,
            "progress_percent": round(progress * 100, 1),
            "bytes_per_second": round(self._speed_bps, 1) if self._speed_bps else None,
            "eta_seconds": round(eta) if eta is not None else None,
            "models": {model_id: self._models[model_id].to_dict() for model_id in sorted(active)},
        }

    def _persist_job(self, *, force: bool = False) -> None:
        with self._persist_lock:
            now = time.monotonic()
            if not force and now - self._last_persist_at < 1:
                return
            with self._lock:
                if self._models_dir is None or self._job_id is None:
                    return
                self._job_updated_at = time.time()
                snapshot = self._job_snapshot_locked()
                job_path = self._job_path(self._models_dir)
            job_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = job_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, job_path)
            self._last_persist_at = now

    def _load_job(self, models_dir: Path) -> bool:
        job_path = self._job_path(models_dir)
        if not job_path.is_file():
            return False
        try:
            data = json.loads(job_path.read_text(encoding="utf-8"))
            if data.get("version") != JOB_VERSION or not data.get("id"):
                raise ValueError("unsupported setup job")
            if data.get("status") not in {"pending", "running", "retrying", "completed", "failed"}:
                raise ValueError("invalid setup job status")
            models_data = data.get("models")
            if not isinstance(models_data, dict):
                raise ValueError("invalid setup job model state")
            active = frozenset(models_data.keys())
            if not active or not active <= set(MODEL_META):
                raise ValueError("invalid setup job models")
            with self._lock:
                self._models_dir = models_dir
                self._job_id = str(data["id"])
                self._job_status = data.get("status", "pending")
                self._job_attempt = int(data.get("attempt", 0))
                self._job_created_at = float(data.get("created_at") or time.time())
                self._job_updated_at = float(data.get("updated_at") or self._job_created_at)
                self._speed_bps = data.get("bytes_per_second")
                self._job_models = active
                self._active_models = active
                for model_id, model_data in models_data.items():
                    if not isinstance(model_data, dict):
                        raise ValueError("invalid setup job model state")
                    state = self._models[model_id]
                    loaded_status = model_data.get("status", "pending")
                    if loaded_status not in {"pending", "downloading", "verifying", "done", "error"}:
                        raise ValueError("invalid setup model status")
                    state.status = "pending" if (
                        self._job_status in ("pending", "running", "retrying")
                        and loaded_status in ("downloading", "verifying")
                    ) else loaded_status
                    state.error = model_data.get("error")
                    state.downloaded_bytes = int(model_data.get("downloaded_bytes", 0))
                    state.total_bytes = int(model_data.get("total_bytes", 0))
                    state.filename = model_data.get("filename")
                self._download_started = False
                self._running = False
                self._complete = self._job_status in ("completed", "failed")
                self._last_sample_at = None
                self._last_sample_bytes = None
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.error("Could not load setup job: {}", type(exc).__name__)
            return False

    def get_job(self, models_dir: Path) -> dict[str, Any] | None:
        with self._lock:
            loaded = self._job_id is not None and self._models_dir == models_dir
        if not loaded and not self._load_job(models_dir):
            return None
        with self._lock:
            return self._job_snapshot_locked()

    def resume_if_needed(self, models_dir: Path) -> None:
        if not self._load_job(models_dir):
            return
        with self._lock:
            job_status = self._job_status
            model_ids = self._job_models

        if job_status in ("pending", "running", "retrying"):
            # Include newly required setup artifacts when resuming an older job.
            model_ids = frozenset(model_ids | DEFAULT_SETUP_MODEL_IDS)
            with self._lock:
                self._job_models = model_ids
                for model_id in model_ids:
                    self._models.setdefault(model_id, ModelDownloadState())
            logger.info("Resuming persistent setup job {}", self._job_id)
            self.start_if_needed(models_dir, model_ids=set(model_ids))
        elif job_status == "completed" and not self.is_ready(models_dir):
            present = self.check_all_present(models_dir)
            present["clip"] = self.has_valid_clip(models_dir)
            present["captioning"] = self.has_valid_captioning(models_dir)
            with self._lock:
                self._job_models = DEFAULT_SETUP_MODEL_IDS
                self._job_status = "retrying"
                self._complete = False
                self._download_started = False
                for model_id in DEFAULT_SETUP_MODEL_IDS:
                    if not present.get(model_id, False):
                        self._models[model_id].status = "pending"
                        self._models[model_id].error = None
            logger.info("Persistent setup job {} needs newly required artifacts; resuming", self._job_id)
            self.start_if_needed(models_dir, model_ids=set(DEFAULT_SETUP_MODEL_IDS))

    # ── State access ──────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, dict]:
        with self._lock:
            return {k: v.to_dict() for k, v in self._models.items()}

    def is_complete(self) -> bool:
        with self._lock:
            return self._complete

    # ── Download control ──────────────────────────────────────────────────────

    def start_if_needed(
        self, models_dir: Path, model_ids: set[str] | None = None,
    ) -> None:
        """Start downloads for the requested models; optional caption weights are opt-in."""
        requested = frozenset(model_ids or DEFAULT_SETUP_MODEL_IDS)
        persistent_run = requested == DEFAULT_SETUP_MODEL_IDS
        unknown = requested - MODEL_META.keys()
        if unknown:
            raise ValueError(f"Unknown model setup target: {', '.join(sorted(unknown))}")
        with self._lock:
            job_loaded = self._job_id is not None and self._models_dir == models_dir
        if persistent_run and not job_loaded:
            self._load_job(models_dir)
        with self._lock:
            if persistent_run and self._job_id is not None and self._job_status != "completed" and self._job_models:
                requested = self._job_models
            if self._running:
                if requested <= self._active_models:
                    return
                raise RuntimeError("Another model setup is already running")
            states = [self._models[model_id] for model_id in requested]
            any_error = any(state.status == "error" for state in states)
            in_progress = any(state.status in ("downloading", "verifying") for state in states)
            all_done = all(state.status == "done" for state in states)
            if in_progress:
                return
            if self._job_status == "completed" and all_done and not any_error:
                return
            if self._download_started and all_done and not any_error:
                return
            for model_id in requested:
                state = self._models[model_id]
                if state.status in ("error", "downloading", "verifying"):
                    state.status = "pending"
                    state.error = None
            if persistent_run:
                now = time.time()
                if self._job_id is None:
                    self._job_id = str(uuid.uuid4())
                    self._job_created_at = now
                    self._job_attempt = 0
                self._models_dir = models_dir
                self._job_models = requested
                self._job_attempt += 1
                self._job_status = "retrying" if self._job_attempt > 1 else "running"
                self._job_updated_at = now
                self._last_sample_at = None
                self._last_sample_bytes = None
            self._persistent_run = persistent_run
            self._download_started = True
            self._running = True
            self._active_models = requested
            self._complete = False
        if persistent_run:
            self._persist_job(force=True)

        thread = threading.Thread(
            target=self._download_worker,
            args=(models_dir, requested),
            daemon=True,
            name="msa-model-download",
        )
        thread.start()

    def _progress_tqdm_class(self, model_id: str):
        from huggingface_hub.utils import tqdm as hub_tqdm

        manager = self

        class ProgressTqdm(hub_tqdm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                manager._set_progress(model_id, int(self.n), int(self.total or 0), self.desc)

            def update(self, n=1):
                updated = super().update(n)
                manager._set_progress(model_id, int(self.n), int(self.total or 0), self.desc)
                return updated

        return ProgressTqdm

    def _download_commercial_model(self, model_id: str, models_dir: Path) -> None:
        spec = COMMERCIAL_MODEL_BY_ID[model_id]
        if spec.download_kind == "unavailable":
            self._set(model_id, "error", spec.access_note or "This model cannot be downloaded locally.")
            return
        if model_is_installed(spec, models_dir):
            self._set(model_id, "done")
            return
        self._set(model_id, "downloading")
        target = spec.model_dir(models_dir)
        try:
            if spec.download_kind == "huggingface":
                from huggingface_hub import snapshot_download

                target.mkdir(parents=True, exist_ok=True)
                patterns = ["*.json", "*.txt", "*.model", "*.vocab", "*.merges"]
                patterns.extend(artifact.filename for artifact in spec.artifacts)
                snapshot_download(
                    repo_id=spec.repo_id,
                    revision=spec.revision,
                    local_dir=str(target),
                    allow_patterns=patterns,
                    max_workers=1,
                    tqdm_class=self._progress_tqdm_class(model_id),
                )
            else:
                import requests

                target.mkdir(parents=True, exist_ok=True)
                for artifact in spec.artifacts:
                    final_path = target / artifact.filename
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    partial_path = final_path.with_suffix(final_path.suffix + ".part")
                    digest = hashlib.sha256()
                    downloaded = 0
                    with requests.get(artifact.url, stream=True, timeout=(15, 60)) as response:
                        response.raise_for_status()
                        total = int(response.headers.get("Content-Length") or artifact.size_bytes)
                        self._set_progress(model_id, 0, total, artifact.filename)
                        with partial_path.open("wb") as stream:
                            for chunk in response.iter_content(chunk_size=1024 * 1024):
                                if not chunk:
                                    continue
                                stream.write(chunk)
                                digest.update(chunk)
                                downloaded += len(chunk)
                                self._set_progress(model_id, downloaded, total, artifact.filename)
                    if downloaded != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
                        partial_path.unlink(missing_ok=True)
                        raise ValueError(f"Size or SHA-256 verification failed for {artifact.filename}")
                    os.replace(partial_path, final_path)

            self._set(model_id, "verifying")
            if not verify_model(spec, models_dir):
                raise ValueError("Downloaded model failed size or SHA-256 verification")
            mark_model_verified(spec, models_dir)
            self._set(model_id, "done")
            logger.info("setup_models: commercial model {} downloaded and verified", model_id)
        except Exception as exc:
            logger.error("setup_models: commercial model {} setup failed ({})", model_id, type(exc).__name__)
            self._set(model_id, "error", f"Download or verification failed ({type(exc).__name__})")

    def _download_caption_model(self, models_dir: Path, force_download: bool = False) -> None:
        self._set("captioning", "downloading")
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(
                CAPTION_MODEL_ID,
                revision=CAPTION_MODEL_REVISION,
                cache_dir=str(caption_model_cache_dir(models_dir)),
                allow_patterns=list(CAPTION_MODEL_REQUIRED_FILES),
                force_download=force_download,
                max_workers=1,
                tqdm_class=self._progress_tqdm_class("captioning"),
            )
            self._set("captioning", "verifying")
            if not self.has_valid_captioning(models_dir):
                raise ValueError("BLIP checkpoint failed SHA-256 verification")
            self._set("captioning", "done")
            logger.info(
                "setup_models: BLIP caption model downloaded and verified (revision {})",
                CAPTION_MODEL_REVISION[:12],
            )
        except Exception as exc:
            logger.error("setup_models: BLIP caption model setup failed ({})", type(exc).__name__)
            self._set(
                "captioning", "error",
                f"BLIP download or verification failed ({type(exc).__name__})",
            )

    def _set(self, model: str, status: ModelState, error: str | None = None) -> None:
        with self._lock:
            state = self._models[model]
            state.status = status
            state.error = error
            if status == "done":
                state.downloaded_bytes = 0
                state.total_bytes = 0
                state.filename = None
            persistent_run = self._persistent_run
        logger.info("Model setup: {} -> {}", model, status)
        if persistent_run:
            self._persist_job(force=True)

    def _set_progress(
        self, model: str, downloaded_bytes: int, total_bytes: int, filename: str | None,
    ) -> None:
        with self._lock:
            state = self._models[model]
            state.downloaded_bytes = max(0, downloaded_bytes)
            state.total_bytes = max(0, total_bytes)
            state.filename = Path(filename).name if filename else None
            self._record_sample_locked()
            persistent_run = self._persistent_run
        if persistent_run:
            self._persist_job()

    # ── Download worker (runs in background thread) ───────────────────────────

    def _download_worker(
        self, models_dir: Path, model_ids: frozenset[str] | None = None,
    ) -> None:
        model_ids = model_ids or DEFAULT_SETUP_MODEL_IDS
        try:
            models_dir.mkdir(parents=True, exist_ok=True)
            present = self.check_all_present(models_dir)
            present["clip"] = self.has_valid_clip(models_dir)
            if not present["clip"]:
                for stale in clip_checkpoint_candidates(models_dir):
                    stale.unlink(missing_ok=True)
        except Exception as exc:
            # Bootstrap failure (e.g. unwritable models_dir) — mark every still-pending
            # model as error and set complete so the WS loop terminates and the UI can
            # show the error rather than polling forever.
            logger.error("setup_models: worker bootstrap failed ({})", type(exc).__name__)
            with self._lock:
                for model_id in model_ids:
                    state = self._models[model_id]
                    if state.status == "pending":
                        state.status = "error"
                        state.error = f"Setup failed to start ({type(exc).__name__})"
                persistent_run = self._persistent_run
                if persistent_run:
                    self._job_status = "failed"
                self._complete = True
                self._running = False
                if not persistent_run:
                    self._active_models = frozenset()
            if persistent_run:
                self._persist_job(force=True)
            return

        # ── CLIP ViT-L-14/openai ──────────────────────────────────────────
        if "clip" not in model_ids:
            pass
        elif present["clip"]:
            self._set("clip", "done")
            logger.info("setup_models: CLIP already present, skipping download")
        else:
            self._set("clip", "downloading")
            try:
                clip_cache = models_dir / "clip"
                clip_cache.mkdir(parents=True, exist_ok=True)
                os.environ["HF_HUB_DISABLE_XET"] = "1"
                from huggingface_hub import constants as hf_constants  # type: ignore[import]

                hf_constants.HF_HUB_DISABLE_XET = True
                import open_clip  # type: ignore[import]

                stop_progress = threading.Event()
                expected_bytes = MODEL_META["clip"]["size_mb"] * 1024 * 1024

                def report_clip_progress() -> None:
                    while not stop_progress.wait(0.5):
                        partials = list(clip_cache.rglob("*.incomplete"))
                        if partials:
                            partial = max(partials, key=lambda path: path.stat().st_size)
                            self._set_progress("clip", partial.stat().st_size, expected_bytes, partial.name)

                progress_thread = threading.Thread(target=report_clip_progress, daemon=True)
                progress_thread.start()
                try:
                    for attempt in range(1, 4):
                        try:
                            open_clip.create_model_and_transforms(
                                CLIP_MODEL_NAME, pretrained=CLIP_PRETRAINED,
                                device="cpu", cache_dir=str(clip_cache),
                            )
                            break
                        except Exception as exc:
                            if attempt == 3:
                                raise
                            delay = 2 ** attempt
                            logger.warning(
                                "CLIP download interrupted ({}); retrying in {}s",
                                type(exc).__name__, delay,
                            )
                            stop_progress.wait(delay)
                finally:
                    stop_progress.set()
                    progress_thread.join(timeout=1)
                # Verify the exact approved artifact selected by open_clip.
                self._set("clip", "verifying")
                if not self.has_valid_clip(models_dir):
                    raise ValueError("No approved, checksum-valid CLIP checkpoint found after download")
                self._set("clip", "done")
                logger.info("setup_models: CLIP ViT-L-14 downloaded and verified")
            except Exception as exc:
                logger.error("setup_models: CLIP download failed — {}", exc)
                self._set("clip", "error", str(exc))

        # ── RT-DETR PekingU/rtdetr_r18vd ─────────────────────────────────
        if "rtdetr" not in model_ids:
            pass
        elif present["rtdetr"]:
            self._set("rtdetr", "done")
            logger.info("setup_models: RT-DETR already present, skipping download")
        else:
            self._set("rtdetr", "downloading")
            try:
                from transformers import (  # type: ignore[import]
                    RTDetrForObjectDetection,
                    RTDetrImageProcessor,
                )
                rtdetr_cache = str(models_dir / "rtdetr")
                # Processor (~2 MB config files) downloads first, then model weights.
                RTDetrImageProcessor.from_pretrained(
                    RTDETR_DEFAULT_MODEL,
                    revision=RTDETR_DEFAULT_REVISION,
                    cache_dir=rtdetr_cache,
                )
                RTDetrForObjectDetection.from_pretrained(
                    RTDETR_DEFAULT_MODEL,
                    revision=RTDETR_DEFAULT_REVISION,
                    cache_dir=rtdetr_cache,
                )
                # Integrity guaranteed by HuggingFace hub blob-level SHA-256;
                # no additional file verification needed.
                self._set("rtdetr", "done")
                logger.info(
                    "setup_models: RT-DETR {} downloaded (revision {})",
                    RTDETR_DEFAULT_MODEL, RTDETR_DEFAULT_REVISION[:12],
                )
            except Exception as exc:
                logger.error("setup_models: RT-DETR download failed — {}", exc)
                self._set("rtdetr", "error", str(exc))

        # ── facenet-pytorch VGGFace2 ──────────────────────────────────────
        if "facenet_pytorch" not in model_ids:
            pass
        elif present["facenet_pytorch"]:
            self._set("facenet_pytorch", "done")
            logger.info("setup_models: facenet-pytorch VGGFace2 already present, skipping download")
        else:
            self._set("facenet_pytorch", "downloading")
            try:
                # facenet-pytorch downloads VGGFace2 weights through torch.hub,
                # which calls urllib.request.urlopen() directly. urllib on Windows
                # doesn't read the Windows certificate store and doesn't load
                # certifi unless SSL_CERT_FILE is set, so fresh VMs fail with
                # "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer
                # certificate". truststore bridges Python's stdlib SSL to the OS
                # trust store (Schannel on Windows, Security framework on macOS,
                # OpenSSL defaults on Linux). The other two model downloads
                # (CLIP, RT-DETR) go through huggingface_hub/requests/certifi and
                # aren't affected.
                try:
                    import truststore  # type: ignore[import]
                    truststore.inject_into_ssl()
                except Exception as ts_exc:
                    logger.warning(
                        "setup_models: truststore.inject_into_ssl() failed — {}; "
                        "torch.hub may fail with SSL errors on Windows VMs", ts_exc,
                    )
                import torch  # type: ignore[import]
                # Redirect torch hub to models_dir so weights stay under the
                # application data directory rather than ~/.cache/torch/hub/.
                hub_dir = str(models_dir / "facenet_pytorch")
                os.makedirs(hub_dir, exist_ok=True)
                os.environ["TORCH_HOME"] = hub_dir
                torch.hub.set_dir(hub_dir)

                from facenet_pytorch import InceptionResnetV1, MTCNN  # type: ignore[import]
                # MTCNN weights (~1 MB) are bundled in the package; instantiating
                # it on CPU just registers the model and verifies package integrity.
                MTCNN(keep_all=False, device=torch.device("cpu"))
                # InceptionResnetV1 downloads ~107 MB from GitHub release assets.
                InceptionResnetV1(pretrained="vggface2").eval()

                self._set("facenet_pytorch", "done")
                logger.info("setup_models: facenet-pytorch VGGFace2 downloaded")
            except Exception as exc:
                logger.error("setup_models: facenet-pytorch download failed — {}", exc)
                self._set("facenet_pytorch", "error", str(exc))

        if "captioning" in model_ids:
            if present["captioning"] and self.has_valid_captioning(models_dir):
                self._set("captioning", "done")
                logger.info("setup_models: BLIP caption model already verified, skipping download")
            else:
                self._download_caption_model(models_dir, force_download=present["captioning"])

        for model_id in sorted(model_ids & COMMERCIAL_MODEL_BY_ID.keys()):
            self._download_commercial_model(model_id, models_dir)

        with self._lock:
            failed = any(self._models[model_id].status == "error" for model_id in model_ids)
            persistent_run = self._persistent_run
            if persistent_run:
                self._job_status = "failed" if failed else "completed"
            else:
                self._active_models = frozenset()
            self._complete = True
            self._running = False
            self._persistent_run = False
        if persistent_run:
            self._persist_job(force=True)
            logger.info("Setup job {} finished with status {}", self._job_id, self._job_status)
        else:
            logger.info("Requested model downloads complete")


# ── Module-level singleton ────────────────────────────────────────────────────

_manager = SetupManager()


def get_manager() -> SetupManager:
    return _manager
