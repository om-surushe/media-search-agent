"""Detector failures must remain errors rather than successful empty results."""
from unittest.mock import Mock

import pytest
from PIL import Image

from msa_indexer.models._detection_backends._rtdetr import RtDetrBackend
from msa_indexer.models.objects import ObjectDetector


def test_rtdetr_get_labels_reraises_and_restores_threshold():
    backend = object.__new__(RtDetrBackend)
    backend.conf_threshold = 0.35
    backend.detect = Mock(side_effect=RuntimeError("inference failed"))

    with pytest.raises(RuntimeError, match="inference failed"):
        backend.get_labels(Image.new("RGB", (2, 2)), min_confidence=0.9)

    assert backend.conf_threshold == 0.35


def test_object_detector_does_not_convert_backend_error_to_empty_labels():
    detector = object.__new__(ObjectDetector)
    detector._impl = Mock()
    detector._impl.get_labels.side_effect = RuntimeError("inference failed")

    with pytest.raises(RuntimeError, match="inference failed"):
        detector.get_labels(Image.new("RGB", (2, 2)))
