from types import SimpleNamespace

from fastapi.testclient import TestClient

from msa_indexer.adapters import adapter_02_identity, adapter_03_metadata


def _source(tmp_path):
    source_root = tmp_path / "source"
    (source_root / "nested").mkdir(parents=True)
    (source_root / "first.jpg").write_bytes(b"image")
    (source_root / "nested" / "second.mp4").write_bytes(b"video")
    return source_root, SimpleNamespace(name="sample", path=str(source_root), enabled=True)


def test_identity_hashes_all_source_media_with_bounded_results(tmp_path):
    source_root, source = _source(tmp_path)

    result = adapter_02_identity.preview_source_identity(source, result_limit=1)

    assert result["scope"] == "whole_configured_source"
    assert result["files_checked"] == 2
    assert result["complete"] is True
    assert result["results_truncated"] is True
    assert len(result["results"]) == 1
    assert result["persisted"] is False
    assert str(source_root) not in repr(result)


def test_metadata_extracts_all_source_media_without_persisting(tmp_path, monkeypatch):
    source_root, source = _source(tmp_path)
    calls = []

    def image_metadata(path):
        calls.append(path.suffix)
        return {"kind": "image"}, True

    def video_metadata(path):
        calls.append(path.suffix)
        return {"kind": "video"}, True

    monkeypatch.setattr(adapter_03_metadata, "get_exif_basic_result", image_metadata)
    monkeypatch.setattr(adapter_03_metadata, "get_video_meta_result", video_metadata)

    result = adapter_03_metadata.preview_source_metadata(source)

    assert result["scope"] == "whole_configured_source"
    assert result["files_checked"] == 2
    assert result["completed"] == 2
    assert result["complete"] is True
    assert sorted(calls) == [".jpg", ".mp4"]
    assert all(item["persisted"] is False for item in result["results"])
    assert str(source_root) not in repr(result)


def test_workbench_folder_api_requires_no_file_selection(tmp_path, monkeypatch):
    from msa_apps.search_api import app as app_module

    source_root, source = _source(tmp_path)
    config = SimpleNamespace(media_sources=[source], models_dir=tmp_path)
    monkeypatch.setattr(app_module, "_get_config", lambda _request: config)
    monkeypatch.setattr(
        adapter_03_metadata, "get_exif_basic_result", lambda _path: ({"kind": "image"}, True),
    )
    monkeypatch.setattr(
        adapter_03_metadata, "get_video_meta_result", lambda _path: ({"kind": "video"}, True),
    )

    client = TestClient(app_module.app)
    identity = client.post("/adapters/identity/run", params={"source_name": "sample"})
    metadata = client.post("/adapters/metadata/run", params={"source_name": "sample"})
    selected = client.post("/adapters/identity/run", params={
        "source_name": "sample", "relative_path": "first.jpg",
    })
    client.close()

    assert identity.status_code == 200
    assert identity.json()["files_checked"] == 2
    assert metadata.status_code == 200
    assert metadata.json()["files_checked"] == 2
    assert selected.status_code == 400
    assert str(source_root) not in identity.text
    assert str(source_root) not in metadata.text
