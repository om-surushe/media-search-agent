"""Pinned CLIP ViT-L-14/openai checkpoint artifacts used by setup and workbench."""

from pathlib import Path

CLIP_MODEL_NAME = "ViT-L-14"
CLIP_PRETRAINED = "openai"
CLIP_HF_REPO = "timm/vit_large_patch14_clip_224.openai"

# open_clip prefers the HF safetensors file when huggingface_hub and
# safetensors are installed, otherwise it falls back to these equivalent files.
CLIP_CHECKPOINT_SHA256 = {
    "open_clip_model.safetensors": "9ce2e8a8ebfff3793d7d375ad6d3c35cb9aebf3de7ace0fc7308accab7cd207e",
    "open_clip_pytorch_model.bin": "c4e2d8e8f1a5bc97c76b9c9385d2fc2a1acd38846db5468f579fda12306a218b",
    "ViT-L-14.pt": "b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836",
}


def clip_checkpoint_candidates(models_dir: Path) -> list[Path]:
    """Return named CLIP checkpoints and large HF cache blobs under the app cache."""
    cache = Path(models_dir) / "clip"
    if not cache.exists():
        return []
    candidates = [path for name in CLIP_CHECKPOINT_SHA256 for path in cache.rglob(name)]
    candidates.extend(
        path
        for blob_dir in cache.rglob("blobs") if blob_dir.is_dir()
        for path in blob_dir.iterdir()
        if path.is_file() and path.stat().st_size > 100_000_000
    )
    return list(dict.fromkeys(candidates))
