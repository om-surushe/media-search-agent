from pathlib import Path

import pytest
from PIL import Image

from msa_indexer.io.exif import get_exif_basic, get_exif_basic_result


def test_get_exif_basic_result_distinguishes_no_tags_from_unreadable_file(tmp_path):
    readable = tmp_path / "no-exif.png"
    Image.new("RGB", (8, 8)).save(readable)
    unreadable = tmp_path / "bad.jpg"
    unreadable.write_bytes(b"not an image")

    _, readable_ok = get_exif_basic_result(readable)
    _, unreadable_ok = get_exif_basic_result(unreadable)

    assert readable_ok is True
    assert unreadable_ok is False


def test_get_exif_basic_extracts_gps_from_jpeg_ifd():
    path = Path("tests/real_media/fixtures/derived/exif_gps_face_01.jpg")

    meta = get_exif_basic(path)

    assert meta["width"] == 3043
    assert meta["height"] == 2022
    assert meta["gps_lat"] == pytest.approx(37.7749, abs=1e-4)
    assert meta["gps_lon"] == pytest.approx(-122.4194, abs=1e-4)


def test_get_exif_basic_extracts_gps_from_heic_fixture():
    path = Path("tests/real_media/fixtures/derived/exif_gps_face_01.heic")

    meta = get_exif_basic(path)

    assert meta["width"] == 3043
    assert meta["height"] == 2022
    assert meta["gps_lat"] == pytest.approx(37.7749, abs=1e-4)
    assert meta["gps_lon"] == pytest.approx(-122.4194, abs=1e-4)
