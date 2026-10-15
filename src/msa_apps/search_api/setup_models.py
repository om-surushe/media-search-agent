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
import os
import threading
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

# ── Types ─────────────────────────────────────────────────────────────────────

ModelState = Literal["pending", "downloading", "verifying", "done", "error"]

# Pinned revision for the default RT-DETR model. HuggingFace hub verifies
# per-blob SHA-256 during download, so we don't maintain a separate hash.
# Update this constant deliberately when upgrading the default model weights.
RTDETR_DEFAULT_MODEL    = "PekingU/rtdetr_r18vd"
RTDETR_DEFAULT_REVISION = "ac77a11ff0170a41b771c03264987f8ce2b0d753"
DEFAULT_SETUP_MODEL_IDS = frozenset({"clip", "rtdetr", "facenet_pytorch"})

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

    def to_dict(self) -> dict:
        return {"status": self.status, "error": self.error}


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

    # ── Presence checks ───────────────────────────────────────────────────────

    def check_all_present(self, models_dir: Path) -> dict[str, bool]:
        """Check which model weight files are already on disk."""
        clip_cache = models_dir / "clip"

        # open_clip caches the selected hub checkpoint under the local HF cache;
        # some platforms expose only its content-addressed blob filename.
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

        return {
            "clip":            clip_present,
            "rtdetr":          rtdetr_present,
            "facenet_pytorch": facenet_present,
            "captioning": caption_present,
        }

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
        return all(present[model_id] for model_id in DEFAULT_SETUP_MODEL_IDS)

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
        unknown = requested - MODEL_META.keys()
        if unknown:
            raise ValueError(f"Unknown model setup target: {', '.join(sorted(unknown))}")
        with self._lock:
            if self._running:
                if requested <= self._active_models:
                    return
                raise RuntimeError("Another model setup is already running")
            states = [self._models[model_id] for model_id in requested]
            any_error = any(state.status == "error" for state in states)
            in_progress = any(state.status in ("downloading", "verifying") for state in states)
            all_done = all(state.status == "done" for state in states)
            if self._download_started and all_done and not any_error:
                return
            if in_progress:
                return
            for model_id in requested:
                state = self._models[model_id]
                if state.status == "error":
                    state.status = "pending"
                    state.error = None
            self._download_started = True
            self._running = True
            self._active_models = requested
            self._complete = False

        thread = threading.Thread(
            target=self._download_worker,
            args=(models_dir, requested),
            daemon=True,
            name="msa-model-download",
        )
        thread.start()

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
            self._models[model].status = status
            self._models[model].error = error

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
                self._complete = True
                self._running = False
                self._active_models = frozenset()
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
                import open_clip  # type: ignore[import]
                open_clip.create_model_and_transforms(
                    CLIP_MODEL_NAME, pretrained=CLIP_PRETRAINED,
                    device="cpu", cache_dir=str(clip_cache),
                )
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

        with self._lock:
            self._complete = True
            self._running = False
            self._active_models = frozenset()
        logger.info("setup_models: requested model downloads complete")


# ── Module-level singleton ────────────────────────────────────────────────────

_manager = SetupManager()


def get_manager() -> SetupManager:
    return _manager
