"""Compatibility imports for model adapters now implemented in msa_indexer.adapters."""
from msa_indexer.adapters.model_adapters import (
    ClipEmbedderLike,
    ClipEmbeddingAdapter,
    ModelAdapterBundle,
    OpenClipAdapter,
    SpeechTranscriptionAdapter,
    WhisperAdapter,
    WhisperTranscriberLike,
    default_model_adapters,
)

__all__ = [
    "ClipEmbedderLike",
    "ClipEmbeddingAdapter",
    "ModelAdapterBundle",
    "OpenClipAdapter",
    "SpeechTranscriptionAdapter",
    "WhisperAdapter",
    "WhisperTranscriberLike",
    "default_model_adapters",
]
