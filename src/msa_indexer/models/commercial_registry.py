"""Pinned local-model catalog used by the app's on-demand setup flow.

License fields are upstream claims, not legal clearance. Model weights live in
``models_dir/commercial/<model-id>/snapshot`` and are never bundled in Git.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Clearance = Literal["review_required", "conditional", "gated", "hosted_only"]
DownloadKind = Literal["huggingface", "http", "unavailable"]


@dataclass(frozen=True)
class ModelArtifact:
    filename: str
    sha256: str
    size_bytes: int
    url: str


@dataclass(frozen=True)
class CommercialModel:
    model_id: str
    task: str
    label: str
    publisher: str
    revision: str | None
    repo_id: str | None
    artifacts: tuple[ModelArtifact, ...]
    download_kind: DownloadKind
    license_claim: str
    license_evidence: str
    clearance: Clearance = "review_required"
    access_note: str | None = None
    min_ram_gb: int = 8

    def model_dir(self, models_dir: Path) -> Path:
        return Path(models_dir) / "commercial" / self.model_id / "snapshot"


# Exact file pins and hashes were checked against the upstream Git LFS object ID,
# OpenAI's checkpoint URL hash, or OpenCV Zoo's Git LFS pointer. A hash check
# establishes artifact identity only; it does not establish redistribution rights.
MODELS: tuple[CommercialModel, ...] = (
    CommercialModel(
        "clip-vit-b32", "visual_embedding", "CLIP ViT-B/32", "OpenAI", "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268",
        "openai/clip-vit-base-patch32",
        (ModelArtifact("pytorch_model.bin", "a63082132ba4f97a80bea76823f544493bffa8082296d62d71581a4feff1576f", 605247071,
                       "https://huggingface.co/openai/clip-vit-base-patch32/resolve/3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268/pytorch_model.bin"),),
        "huggingface", "MIT (code repository)", "https://github.com/openai/CLIP/blob/main/LICENSE", min_ram_gb=4,
    ),
    CommercialModel(
        "clip-vit-l14", "visual_embedding", "CLIP ViT-L/14", "OpenAI", "32bd64288804d66eefd0ccbe215aa642df71cc41",
        "openai/clip-vit-large-patch14",
        (ModelArtifact("model.safetensors", "a2bf730a0c7debf160f7a6b50b3aaf3703e7e88ac73de7a314903141db026dcb", 1710540580,
                       "https://huggingface.co/openai/clip-vit-large-patch14/resolve/32bd64288804d66eefd0ccbe215aa642df71cc41/model.safetensors"),),
        "huggingface", "MIT (code repository)", "https://github.com/openai/CLIP/blob/main/LICENSE", min_ram_gb=8,
    ),
    CommercialModel(
        "siglip2-base", "visual_embedding", "SigLIP2 Base", "Google", "3f9f96cb90da5dbc758b01813f2f6f1aee24c1ab",
        "google/siglip2-base-patch16-256",
        (ModelArtifact("model.safetensors", "6125cacc01fa93bdc98a0c5101cefcd69b2ed1f8ab4f38d86f4ad5984f5dc863", 1500985224,
                       "https://huggingface.co/google/siglip2-base-patch16-256/resolve/3f9f96cb90da5dbc758b01813f2f6f1aee24c1ab/model.safetensors"),),
        "huggingface", "Apache-2.0 (model listing)", "https://huggingface.co/google/siglip2-base-patch16-256/tree/main", min_ram_gb=8,
    ),
    CommercialModel(
        "rtdetr-r18", "object_detection", "RT-DETR R18", "Peking University", "ac77a11ff0170a41b771c03264987f8ce2b0d753",
        "PekingU/rtdetr_r18vd",
        (ModelArtifact("model.safetensors", "fe87a5a30f5daf298d10794c7682a63b6107986f97d6a770ba948d89e4340093", 80904152,
                       "https://huggingface.co/PekingU/rtdetr_r18vd/resolve/ac77a11ff0170a41b771c03264987f8ce2b0d753/model.safetensors"),),
        "huggingface", "Apache-2.0 (model listing)", "https://huggingface.co/PekingU/rtdetr_r18vd/tree/main", min_ram_gb=4,
    ),
    CommercialModel(
        "florence2-base", "captioning", "Florence-2 Base", "Microsoft", "5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac",
        "microsoft/Florence-2-base",
        (ModelArtifact("model.safetensors", "03075d2d2d2bbd3e180b9ba0afae4aa8563226e2d32911656966e05b2f2ee060", 463221266,
                       "https://huggingface.co/microsoft/Florence-2-base/resolve/5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac/model.safetensors"),),
        "huggingface", "MIT (checkpoint repository)", "https://huggingface.co/microsoft/Florence-2-base/blob/main/LICENSE", min_ram_gb=8,
    ),
    CommercialModel(
        "smolvlm2-256m", "video_understanding", "SmolVLM2 256M", "Hugging Face", "067788b187b95ebe7b2e040b3e4299e342e5b8fd",
        "HuggingFaceTB/SmolVLM2-256M-Video-Instruct",
        (ModelArtifact("model.safetensors", "dcc8f4c00d30d70bb3028a1bfc373e1b1972e25919f8788183cae4ae72431ce2", 1025998224,
                       "https://huggingface.co/HuggingFaceTB/SmolVLM2-256M-Video-Instruct/resolve/067788b187b95ebe7b2e040b3e4299e342e5b8fd/model.safetensors"),),
        "huggingface", "Apache-2.0 (checkpoint statement)", "https://huggingface.co/HuggingFaceTB/SmolVLM2-256M-Video-Instruct", min_ram_gb=8,
    ),
    CommercialModel(
        "blip-base", "captioning", "BLIP Base", "Salesforce", "82a37760796d32b1411fe092ab5d4e227313294b",
        "Salesforce/blip-image-captioning-base",
        (ModelArtifact("pytorch_model.bin", "d6638651a5526cc2ede56f2b5104d6851b0755816d220e5e046870430180c767", 989820849,
                       "https://huggingface.co/Salesforce/blip-image-captioning-base/resolve/82a37760796d32b1411fe092ab5d4e227313294b/pytorch_model.bin"),),
        "huggingface", "BSD-3-Clause (model listing)", "https://huggingface.co/Salesforce/blip-image-captioning-base", min_ram_gb=6,
    ),
    CommercialModel(
        "yunet", "face_detection", "OpenCV YuNet", "OpenCV", "47534e27c9851bb1128ccc0102f1145e27f23f98", None,
        (ModelArtifact("face_detection_yunet_2023mar.onnx", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", 232589,
                       "https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"),),
        "http", "MIT (model-directory notice)", "https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/README.md", min_ram_gb=2,
    ),
    CommercialModel(
        "sface", "face_recognition", "OpenCV SFace", "OpenCV", "47534e27c9851bb1128ccc0102f1145e27f23f98", None,
        (ModelArtifact("face_recognition_sface_2021dec.onnx", "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79", 38696353,
                       "https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"),),
        "http", "Apache-2.0 (model-directory notice)", "https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface/README.md", "conditional", "Training-data and commercial-weight provenance needs upstream confirmation.", min_ram_gb=2,
    ),
    CommercialModel(
        "auraface-v1", "face_recognition", "AuraFace v1", "fal", "af6d057c9b0ec4071d4c49c80e3539258798b609",
        "fal/AuraFace-v1",
        (
            ModelArtifact("glintr100.onnx", "a7933ea5330113b01c9b60351d8f4c33003f145d8470ac5f0e52ee2effe25c60", 260694151,
                         "https://huggingface.co/fal/AuraFace-v1/resolve/af6d057c9b0ec4071d4c49c80e3539258798b609/glintr100.onnx"),
            ModelArtifact("scrfd_10g_bnkps.onnx", "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91", 16923827,
                         "https://huggingface.co/fal/AuraFace-v1/resolve/af6d057c9b0ec4071d4c49c80e3539258798b609/scrfd_10g_bnkps.onnx"),
        ),
        "huggingface", "Apache-2.0 (checkpoint listing)", "https://huggingface.co/fal/AuraFace-v1/blob/main/LICENSE.md", "conditional", "Verify rights and provenance for each ONNX file.", min_ram_gb=8,
    ),
    CommercialModel(
        "whisper-tiny", "transcription", "Whisper Tiny", "OpenAI", "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9",
        None, (ModelArtifact("tiny.pt", "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9", 75572083,
                            "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt"),),
        "http", "MIT (Whisper repository)", "https://github.com/openai/whisper/blob/main/LICENSE", min_ram_gb=2,
    ),
    CommercialModel(
        "whisper-base", "transcription", "Whisper Base", "OpenAI", "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e",
        None, (ModelArtifact("base.pt", "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e", 145262807,
                            "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt"),),
        "http", "MIT (Whisper repository)", "https://github.com/openai/whisper/blob/main/LICENSE", min_ram_gb=4,
    ),
    CommercialModel(
        "whisper-small", "transcription", "Whisper Small", "OpenAI", "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794",
        None, (ModelArtifact("small.pt", "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794", 483617219,
                            "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt"),),
        "http", "MIT (Whisper repository)", "https://github.com/openai/whisper/blob/main/LICENSE", min_ram_gb=6,
    ),
    CommercialModel(
        "faster-whisper-small", "transcription", "faster-whisper Small", "SYSTRAN", "536b0662742c02347bc0e980a01041f333bce120",
        "Systran/faster-whisper-small",
        (ModelArtifact("model.bin", "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671", 483546902,
                       "https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/model.bin"),),
        "huggingface", "MIT (runtime and model listing)", "https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE", "conditional", "Optional CTranslate2 runtime is not installed by default.", min_ram_gb=4,
    ),
    CommercialModel(
        "indicconformer-600m", "transcription", "IndicConformer 600M", "AI4Bharat", None,
        "ai4bharat/indic-conformer-600m-multilingual", (), "unavailable", "MIT (listing; access gated)",
        "https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual", "gated", "Requires authorized upstream access.", min_ram_gb=16,
    ),
    CommercialModel(
        "gemini-embedding-2", "visual_embedding", "Gemini Embedding 2", "Google", None, None, (),
        "unavailable", "Google API terms", "https://ai.google.dev/gemini-api/terms", "hosted_only",
        "Hosted API only; media and derived data would leave the device.", min_ram_gb=0,
    ),
)

MODEL_BY_ID = {model.model_id: model for model in MODELS}
MODEL_ADAPTER_STATUS = {
    "clip-vit-b32": "not wired to the production embedding setting",
    "clip-vit-l14": "production uses a different OpenCLIP checkpoint format and cache path",
    "siglip2-base": "not wired; Transformers checkpoint shape needs compatibility work",
    "rtdetr-r18": "current object-detection adapter",
    "florence2-base": "not wired; processor/runtime integration needed",
    "smolvlm2-256m": "not wired; optional num2words dependency missing",
    "blip-base": "optional BLIP adapter uses its existing cache, not this catalog snapshot",
    "yunet": "not wired to the face pipeline",
    "sface": "not wired; 128-D vectors require a separate index identity",
    "auraface-v1": "not wired; ONNX inference adapter needed",
    "whisper-tiny": "Whisper runtime supports this checkpoint size; catalog path is not wired",
    "whisper-base": "production transcription uses a separate cache path",
    "whisper-small": "Whisper runtime supports this checkpoint size; catalog path is not wired",
    "faster-whisper-small": "optional CTranslate2 runtime is not installed",
    "indicconformer-600m": "gated model; authorized checkpoint required",
    "gemini-embedding-2": "hosted API only; not a local adapter",
}


def hardware_profile() -> dict[str, str | int | bool | None]:
    """Return conservative machine facts for recommendations, never automatic swaps."""
    import os
    import platform
    import subprocess

    system = platform.system().lower()
    machine = platform.machine().lower()
    memory_gb: int | None = None
    try:
        if system == "linux":
            memory_gb = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3))
        elif system == "darwin":
            output = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=2)
            memory_gb = int(output.strip()) // (1024 ** 3)
        elif system == "windows":
            import ctypes
            from ctypes import wintypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", wintypes.DWORD), ("memory_load", wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong) for name in (
                        "total_phys", "avail_phys", "total_page", "avail_page",
                        "total_virtual", "avail_virtual", "avail_extended",
                    )
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                memory_gb = int(status.total_phys // (1024 ** 3))
    except (OSError, ValueError, subprocess.SubprocessError):
        memory_gb = None

    cuda = False
    mps = False
    try:
        import torch

        cuda = bool(torch.cuda.is_available())
        mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    except ImportError:
        pass
    accelerator = "cuda" if cuda else "mps" if mps else "cpu"
    return {
        "os": system,
        "architecture": machine,
        "ram_gb": memory_gb,
        "cpu_count": os.cpu_count() or 1,
        "accelerator": accelerator,
        "hardware_recommendations_are_advisory": True,
    }


def model_catalog(models_dir: Path, states: dict[str, dict]) -> dict:
    """Build an app-facing catalog without claiming legal clearance or autoselecting."""
    hardware = hardware_profile()
    ram_gb = hardware["ram_gb"]
    recommendations: dict[str, str] = {}
    for task in {model.task for model in MODELS}:
        fitting = [
            model for model in MODELS
            if model.task == task and model.download_kind != "unavailable"
            and (ram_gb is None or model.min_ram_gb <= ram_gb)
        ]
        if fitting:
            recommendations[task] = min(
                fitting,
                key=lambda candidate: sum(item.size_bytes for item in candidate.artifacts),
            ).model_id

    entries = []
    for model in MODELS:
        installed = model_is_installed(model, models_dir)
        state = states.get(model.model_id, {"status": "done" if installed else "pending"})
        entries.append({
            "id": model.model_id,
            "task": model.task,
            "label": model.label,
            "publisher": model.publisher,
            "source": model.repo_id or model.artifacts[0].url if model.artifacts else model.license_evidence,
            "revision": model.revision,
            "license_claim": model.license_claim,
            "license_evidence": model.license_evidence,
            "clearance": model.clearance,
            "access_note": model.access_note,
            "downloadable": model.download_kind != "unavailable",
            "installed": installed,
            "path": str(model.model_dir(models_dir)),
            "size_bytes": sum(item.size_bytes for item in model.artifacts),
            "min_ram_gb": model.min_ram_gb,
            "hardware_fit": ram_gb is None or model.min_ram_gb <= ram_gb,
            "recommended_for_task": recommendations.get(model.task) == model.model_id,
            "adapter_status": MODEL_ADAPTER_STATUS[model.model_id],
            "state": state,
        })
    return {"hardware": hardware, "models": entries}


def model_weight_paths(model: CommercialModel, models_dir: Path) -> tuple[Path, ...]:
    return tuple(model.model_dir(models_dir) / item.filename for item in model.artifacts)


def model_is_installed(model: CommercialModel, models_dir: Path) -> bool:
    """Check the install marker and expected file sizes without rehashing GBs on every UI poll."""
    paths = model_weight_paths(model, models_dir)
    marker = model.model_dir(models_dir) / ".msa-verified.json"
    try:
        import json

        recorded = json.loads(marker.read_text())
        expected = {
            "model_id": model.model_id,
            "revision": model.revision,
            "artifacts": {item.filename: item.sha256 for item in model.artifacts},
        }
        return recorded == expected and bool(paths) and all(
            path.is_file() and path.stat().st_size == artifact.size_bytes
            for path, artifact in zip(paths, model.artifacts)
        )
    except (OSError, ValueError, TypeError):
        return False


def mark_model_verified(model: CommercialModel, models_dir: Path) -> None:
    import json

    marker = model.model_dir(models_dir) / ".msa-verified.json"
    marker.write_text(json.dumps({
        "model_id": model.model_id,
        "revision": model.revision,
        "artifacts": {item.filename: item.sha256 for item in model.artifacts},
    }, sort_keys=True))


def verify_model(model: CommercialModel, models_dir: Path) -> bool:
    paths = model_weight_paths(model, models_dir)
    try:
        return bool(paths) and all(
            path.is_file()
            and path.stat().st_size == artifact.size_bytes
            and _sha256(path) == artifact.sha256
            for path, artifact in zip(paths, model.artifacts)
        )
    except OSError:
        return False


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
