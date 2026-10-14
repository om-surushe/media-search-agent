from msa_indexer.io import video


def test_get_video_meta_result_distinguishes_reader_failure_from_empty_metadata(monkeypatch):
    class ClosedCapture:
        def isOpened(self):
            return False

    class OpenCapture:
        def isOpened(self):
            return True

        def get(self, _property):
            return 0

        def release(self):
            pass

    monkeypatch.setattr(video, "MediaInfo", None)
    monkeypatch.setattr(video, "_extract_gps_with_exiftool", lambda _path: None)
    monkeypatch.setattr(video.cv2, "VideoCapture", lambda _path: ClosedCapture())
    failed_meta, failed_ok = video.get_video_meta_result("bad.mp4")
    assert failed_meta == {"duration": None, "width": None, "height": None}
    assert failed_ok is False

    monkeypatch.setattr(video.cv2, "VideoCapture", lambda _path: OpenCapture())
    empty_meta, empty_ok = video.get_video_meta_result("valid-no-tags.mp4")
    assert empty_meta == {"duration": None, "width": None, "height": None}
    assert empty_ok is True


def test_get_video_meta_tolerates_missing_pymediainfo(monkeypatch):
    monkeypatch.setattr(video, "MediaInfo", None)
    monkeypatch.setattr(video, "_extract_gps_with_exiftool", lambda path: None)

    meta = video.get_video_meta("/tmp/example.mov")

    assert meta == {"duration": None, "width": None, "height": None}
