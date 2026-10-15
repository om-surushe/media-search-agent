from __future__ import annotations

import hashlib

from msa_indexer.models.commercial_registry import (
    MODELS,
    MODEL_BY_ID,
    CommercialModel,
    ModelArtifact,
    model_catalog,
    model_is_installed,
    mark_model_verified,
    verify_model,
)


def test_catalog_contains_local_and_non_local_candidates_without_claiming_clearance(tmp_path):
    catalog = model_catalog(tmp_path, {})
    entries = {model["id"]: model for model in catalog["models"]}

    assert set(entries) == set(MODEL_BY_ID)
    assert entries["clip-vit-b32"]["path"].endswith("commercial/clip-vit-b32/snapshot")
    assert entries["indicconformer-600m"]["downloadable"] is False
    assert entries["gemini-embedding-2"]["downloadable"] is False
    assert all(entry["clearance"] != "cleared" for entry in entries.values())
    assert catalog["hardware"]["hardware_recommendations_are_advisory"] is True


def test_installed_check_requires_a_verified_marker_and_expected_hash(tmp_path):
    data = b"verified test weight"
    artifact = ModelArtifact("weights.bin", hashlib.sha256(data).hexdigest(), len(data), "https://example.test/weights")
    spec = CommercialModel(
        "tiny-test", "test", "Test model", "Test publisher", "rev123", "test/model",
        (artifact,), "huggingface", "MIT claim", "https://example.test/license",
    )
    weight = spec.model_dir(tmp_path) / artifact.filename
    weight.parent.mkdir(parents=True)
    weight.write_bytes(data)

    assert verify_model(spec, tmp_path)
    assert not model_is_installed(spec, tmp_path)
    mark_model_verified(spec, tmp_path)
    assert model_is_installed(spec, tmp_path)


def test_registry_model_ids_are_unique_and_local_downloads_have_pins():
    ids = [model.model_id for model in MODELS]
    assert len(ids) == len(set(ids))
    for model in MODELS:
        if model.download_kind == "unavailable":
            continue
        assert model.revision
        assert model.artifacts
        assert all(len(artifact.sha256) == 64 for artifact in model.artifacts)
        assert all(artifact.size_bytes > 0 for artifact in model.artifacts)
