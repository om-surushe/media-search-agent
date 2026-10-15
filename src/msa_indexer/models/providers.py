"""Typed adapter seams for model integrations used by the indexer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import numpy as np
from PIL import Image

from .asr import LocalWhisperTranscriber, TranscriptResult
from .embeddings import ClipEmbedder


class ClipEmbedderLike(Protocol):
    @property
    def dim(self) -> int: ...

    def image_embed(self, pil_images: list[Image.Image]) -> np.ndarray: ...

    def text_embed(self, texts: str | list[str]) -> np.ndarray: ...


class WhisperTranscriberLike(Protocol):
    def transcribe(self, path: Path) -> TranscriptResult: ...


class ClipEmbeddingAdapter(Protocol):
    def create(
        self, model_name: str, pretrained: str, device: str, cache_dir: Path | None
    ) -> ClipEmbedderLike: ...


class SpeechTranscriptionAdapter(Protocol):
    def create(self, models_dir: Path, device: str) -> WhisperTranscriberLike: ...


@dataclass(frozen=True)
class ModelAdapterBundle:
    clip: ClipEmbeddingAdapter
    whisper: SpeechTranscriptionAdapter


class OpenClipAdapter:
    """Construct the existing OpenCLIP embedder with the indexing configuration."""

    def __init__(self, constructor: Callable[..., ClipEmbedderLike] = ClipEmbedder):
        self._constructor = constructor

    def create(
        self, model_name: str, pretrained: str, device: str, cache_dir: Path | None
    ) -> ClipEmbedderLike:
        return self._constructor(model_name, pretrained, device, cache_dir=cache_dir)


class WhisperAdapter:
    """Construct the existing local Whisper transcriber on demand."""

    def __init__(
        self, constructor: Callable[..., WhisperTranscriberLike] = LocalWhisperTranscriber
    ):
        self._constructor = constructor

    def create(self, models_dir: Path, device: str) -> WhisperTranscriberLike:
        return self._constructor(models_dir, device)


def default_model_adapters(
    clip_constructor: Callable[..., ClipEmbedderLike],
    whisper_constructor: Callable[..., WhisperTranscriberLike],
) -> ModelAdapterBundle:
    """Compose defaults from the pipeline's constructor references."""
    return ModelAdapterBundle(
        clip=OpenClipAdapter(clip_constructor),
        whisper=WhisperAdapter(whisper_constructor),
    )
