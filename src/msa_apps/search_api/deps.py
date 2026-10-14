from msa_query.storage.qdrant_client import QdrantStore
from msa_query.embeddings.text_encoder import TextEncoder
from msa_query.query_engine.engine import QueryEngine
from msa_settings import load_config
from loguru import logger
import os
_qe: QueryEngine | None = None


def get_query_engine() -> QueryEngine:
    global _qe
    if _qe is None:
        cfg = load_config()
        read_only = os.environ.get("MSA_SEARCH_BROWSE_READ_ONLY", "").strip().lower() in {"1", "true", "yes"}
        if read_only:
            # Prevent any cache miss from initiating a model download in this runtime.
            for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
                os.environ[key] = "1"
            from msa_apps.search_api.setup_models import get_manager
            models_dir = getattr(cfg, "models_dir", None)
            clip_present = bool(models_dir and get_manager().has_valid_clip(models_dir))
            encoder = None
            if clip_present:
                try:
                    encoder = TextEncoder()
                except Exception as exc:
                    logger.warning("Cached CLIP could not be loaded; using lexical search: {}", exc)
        else:
            encoder = TextEncoder()
        _qe = QueryEngine(
            retriever=QdrantStore(),
            text_encoder=encoder,
            sqlite_path=cfg.sqlite_path,
            search_score_trace=bool(getattr(getattr(cfg, "retrieval", None), "search_score_trace", False)),
            semantic_fallback_on_error=read_only,
        )
    return _qe


def reset_query_engine() -> None:
    """Discard the cached QueryEngine so the next search creates a fresh one.

    Call this after the indexer export completes — the embedded Qdrant client
    opened before the export won't see collections written by the indexer's
    own embedded client unless we reinitialise it.
    """
    global _qe
    _qe = None
