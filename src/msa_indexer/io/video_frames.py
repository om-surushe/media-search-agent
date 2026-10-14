"""Stable identities and bounded, reusable renditions for selected video frames."""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterator, Protocol

from PIL import Image

FRAME_RENDITION_PROFILE = "rgb-jpeg-q90-orient-v1"
FRAME_ID_VERSION = 1


class VideoFrameExtractionCancelled(RuntimeError):
    """Raised when an indexing stop is requested during frame extraction."""


class _FrameStore(Protocol):
    def is_valid_media_id(self, media_id: str) -> bool: ...
    def get_video_frame(self, frame_id: str) -> dict[str, Any] | None: ...
    def get_video_frames_by_pts(
        self, source_revision: str, stream_index: int, pts: int,
        time_base_num: int, time_base_den: int,
    ) -> list[dict[str, Any]]: ...
    def upsert_video_frame(self, frame: dict[str, Any]) -> None: ...
    def get_video_frame_rendition(
        self, frame_id: str, profile: str,
    ) -> dict[str, Any] | None: ...
    def upsert_video_frame_rendition(self, rendition: dict[str, Any]) -> None: ...
    def touch_video_frame_rendition(self, rendition_id: str) -> None: ...
    def video_frame_cache_size(self) -> int: ...
    def oldest_video_frame_rendition(self) -> dict[str, Any] | None: ...
    def delete_video_frame_rendition(self, rendition_id: str) -> None: ...


@dataclass(frozen=True)
class FrameRequest:
    shot_index: int
    keyframe_index: int
    requested_timestamp: float
    existing_frame_id: str | None = None

    def __post_init__(self) -> None:
        if self.shot_index < 0 or self.keyframe_index < 0:
            raise ValueError("shot and keyframe indices must be non-negative")
        if not math.isfinite(self.requested_timestamp) or self.requested_timestamp < 0:
            raise ValueError("requested timestamp must be finite and non-negative")


@dataclass(frozen=True)
class FrameReference:
    frame_id: str
    rendition_id: str
    source_revision: str
    stream_index: int
    pts: int | None
    time_base_num: int | None
    time_base_den: int | None
    frame_ordinal: int | None
    requested_timestamp: float
    actual_timestamp: float
    width: int
    height: int
    rotation_degrees: int
    cache_path: Path
    checksum_sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ExtractedFrame:
    request: FrameRequest
    reference: FrameReference | None
    error: str | None = None


@dataclass(frozen=True)
class _DecodedFrame:
    image: Image.Image
    stream_index: int
    pts: int | None
    time_base: Fraction | None
    frame_ordinal: int | None
    actual_timestamp: float
    rotation_degrees: int


def _apply_rotation(image: Image.Image, rotation_degrees: int) -> Image.Image:
    rotation = int(rotation_degrees) % 360
    return image.rotate(-rotation, expand=True) if rotation else image


def make_frame_id(
    source_revision: str,
    stream_index: int,
    pts: int | None,
    time_base_num: int | None,
    time_base_den: int | None,
    frame_ordinal: int | None,
) -> str:
    """Derive identity from source time, never shot numbering or cache profile."""
    identity = {
        "version": FRAME_ID_VERSION,
        "source_revision": source_revision,
        "stream_index": stream_index,
        "pts": pts,
        "time_base_num": time_base_num,
        "time_base_den": time_base_den,
        "frame_ordinal": frame_ordinal,
    }
    if pts is None and frame_ordinal is None:
        raise ValueError("a frame without PTS needs its stream ordinal")
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def keyframe_timestamps_for_shot(
    shot: tuple[float, float], keyframes_per_shot: int = 1,
) -> list[float]:
    """Return the existing midpoint/start-end timestamp policy without decoding."""
    start, end = shot
    if keyframes_per_shot <= 1:
        return [(start + end) / 2.0]
    if keyframes_per_shot == 2:
        return [start, end]
    return [start, (start + end) / 2.0, end]


class VideoFrameCache:
    """Decode selected timestamps in one reusable PyAV session and cache JPEG renditions."""

    def __init__(self, store: _FrameStore, cache_dir: Path | str, budget_mb: int = 1024):
        if budget_mb < 1:
            raise ValueError("video frame cache budget must be at least 1 MiB")
        self.store = store
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        self.max_bytes = int(budget_mb) * 1024 * 1024

    def extract_batch(
        self,
        video_id: str,
        video_path: Path | str,
        requests: list[FrameRequest],
        stop_event: threading.Event | None = None,
    ) -> Iterator[ExtractedFrame]:
        """Yield cached or newly decoded frames in request order, retaining one image at a time."""
        if not requests:
            return
        if not self.store.is_valid_media_id(video_id):
            raise ValueError("Invalid source video ID")
        if any(
            (left.requested_timestamp, left.shot_index, left.keyframe_index)
            > (right.requested_timestamp, right.shot_index, right.keyframe_index)
            for left, right in zip(requests, requests[1:])
        ):
            raise ValueError("frame requests must be in chronological order")

        source = Path(video_path).expanduser().resolve(strict=True)
        container = None
        try:
            for request in requests:
                self._check_cancelled(stop_event)
                if request.existing_frame_id:
                    reference = self._cached_reference(
                        request.existing_frame_id, request.requested_timestamp
                    )
                    if reference is not None:
                        yield ExtractedFrame(request, reference)
                        continue

                if container is None:
                    import av
                    container = av.open(str(source), mode="r")
                streams = container.streams.video
                if not streams:
                    yield ExtractedFrame(request, None, "NoVideoStream")
                    continue
                stream = streams[0]
                decoded = self._decode_nearest(
                    container, stream, request.requested_timestamp, stop_event
                )
                if decoded is None:
                    yield ExtractedFrame(request, None, "NoFrameAtTimestamp")
                    continue
                canonical_frame_id = None
                collision_rows = []
                if decoded.pts is not None and decoded.time_base is not None:
                    collision_rows = self.store.get_video_frames_by_pts(
                        video_id,
                        decoded.stream_index,
                        decoded.pts,
                        decoded.time_base.numerator,
                        decoded.time_base.denominator,
                    )
                if request.existing_frame_id and any(
                    row["frame_id"] == request.existing_frame_id for row in collision_rows
                ):
                    canonical_frame_id = request.existing_frame_id
                elif collision_rows:
                    pixel_match = False
                    pixel_mismatch = False
                    for row in collision_rows:
                        cached_reference = self._cached_reference(
                            row["frame_id"], request.requested_timestamp
                        )
                        if cached_reference is None:
                            continue
                        try:
                            pixel_match = (
                                self.load_image(cached_reference).tobytes()
                                == decoded.image.tobytes()
                            )
                        except (OSError, ValueError):
                            continue
                        if pixel_match:
                            canonical_frame_id = row["frame_id"]
                            break
                        pixel_mismatch = True
                    if canonical_frame_id is None and (
                        len(collision_rows) > 1 or pixel_mismatch
                    ):
                        decoded = self._add_collision_ordinal(
                            container, stream, decoded, stop_event
                        )
                    elif canonical_frame_id is None and len(collision_rows) == 1:
                        # If the old rendition was evicted, the timecode is the
                        # only evidence available; retaining its identity is safer
                        # than inventing a different frame ID during cache recovery.
                        canonical_frame_id = collision_rows[0]["frame_id"]
                frame_id = canonical_frame_id or make_frame_id(
                    video_id,
                    decoded.stream_index,
                    decoded.pts,
                    decoded.time_base.numerator if decoded.time_base else None,
                    decoded.time_base.denominator if decoded.time_base else None,
                    decoded.frame_ordinal,
                )
                if request.existing_frame_id and frame_id != request.existing_frame_id:
                    yield ExtractedFrame(request, None, "FrameIdentityMismatch")
                    continue
                reference = self._store_frame(
                    video_id, frame_id, decoded, request.requested_timestamp, stop_event
                )
                yield ExtractedFrame(request, reference)
                # The caller has consumed this reference before the generator resumes.
                self._evict_to_budget()
        finally:
            if container is not None:
                container.close()

    def load_image(self, reference: FrameReference) -> Image.Image:
        """Read and checksum-verify a cache entry, returning an independent RGB image."""
        path = self._safe_cache_path(reference.cache_path.relative_to(self.cache_dir).as_posix())
        with path.open("rb") as image_file:
            digest = hashlib.file_digest(image_file, "sha256").hexdigest()
        if digest != reference.checksum_sha256:
            raise ValueError("Cached frame checksum mismatch")
        with Image.open(path) as image:
            image.load()
            return image.convert("RGB").copy()

    def get_cached_image(self, frame_id: str) -> tuple[Path, str] | None:
        """Return a verified rendition path and checksum for a downstream worker."""
        rendition = self.store.get_video_frame_rendition(frame_id, FRAME_RENDITION_PROFILE)
        if rendition is None:
            return None
        path = self._safe_cache_path(rendition["cache_relpath"])
        try:
            with path.open("rb") as image_file:
                digest = hashlib.file_digest(image_file, "sha256").hexdigest()
            if digest != rendition["checksum_sha256"]:
                raise ValueError("checksum mismatch")
            with Image.open(path) as image:
                image.verify()
        except (OSError, ValueError):
            self._remove_rendition(rendition)
            return None
        self.store.touch_video_frame_rendition(rendition["rendition_id"])
        return path, digest

    def _cached_reference(self, frame_id: str, requested_timestamp: float) -> FrameReference | None:
        cached = self.get_cached_image(frame_id)
        identity = self.store.get_video_frame(frame_id)
        rendition = self.store.get_video_frame_rendition(frame_id, FRAME_RENDITION_PROFILE)
        if cached is None or identity is None or rendition is None:
            return None
        path, checksum = cached
        return FrameReference(
            frame_id=frame_id,
            rendition_id=rendition["rendition_id"],
            source_revision=identity["source_revision"],
            stream_index=identity["stream_index"],
            pts=identity["pts"],
            time_base_num=identity["time_base_num"],
            time_base_den=identity["time_base_den"],
            frame_ordinal=identity["frame_ordinal"],
            requested_timestamp=requested_timestamp,
            actual_timestamp=identity["actual_timestamp"],
            width=rendition["width"],
            height=rendition["height"],
            rotation_degrees=rendition["rotation_degrees"],
            cache_path=path,
            checksum_sha256=checksum,
            size_bytes=rendition["size_bytes"],
        )

    def _decode_nearest(self, container, stream, timestamp: float, stop_event) -> _DecodedFrame | None:
        time_base = stream.time_base
        if time_base is None:
            raise ValueError("Video stream has no time base")
        target_pts = int(round(timestamp / float(time_base)))
        container.seek(target_pts, stream=stream, backward=True)
        previous = None
        chosen = None
        missing_timestamp = False
        for frame in container.decode(stream):
            self._check_cancelled(stop_event)
            frame_time_base = frame.time_base or time_base
            if frame.pts is None or frame_time_base is None:
                missing_timestamp = True
                break
            frame_time = float(frame.pts * frame_time_base)
            if frame_time >= timestamp:
                choices = [candidate for candidate in (previous, frame) if candidate is not None]
                chosen = min(
                    choices,
                    key=lambda candidate: abs(float(candidate.pts * (candidate.time_base or time_base)) - timestamp),
                )
                break
            previous = frame
        if missing_timestamp:
            return self._decode_by_ordinal(container, stream, timestamp, stop_event)
        if chosen is None:
            chosen = previous
        if chosen is None:
            return None
        frame_time_base = chosen.time_base or time_base
        rotation = self._rotation_degrees(stream)
        image = _apply_rotation(chosen.to_image().convert("RGB"), rotation)
        return _DecodedFrame(
            image=image,
            stream_index=int(stream.index),
            pts=int(chosen.pts),
            time_base=Fraction(frame_time_base),
            frame_ordinal=None,
            actual_timestamp=float(chosen.pts * frame_time_base),
            rotation_degrees=rotation,
        )

    def _decode_by_ordinal(self, container, stream, timestamp: float, stop_event) -> _DecodedFrame | None:
        rate = stream.average_rate
        fps = float(rate) if rate else 30.0
        target_ordinal = max(0, int(timestamp * fps))
        container.seek(0, stream=stream, backward=True)
        chosen = None
        ordinal = None
        for index, frame in enumerate(container.decode(stream)):
            self._check_cancelled(stop_event)
            if index >= target_ordinal:
                chosen, ordinal = frame, index
                break
        if chosen is None or ordinal is None:
            return None
        time_base = Fraction(rate.denominator, rate.numerator) if rate else None
        actual_timestamp = float(chosen.pts * (chosen.time_base or time_base)) if chosen.pts is not None else ordinal / fps
        rotation = self._rotation_degrees(stream)
        image = _apply_rotation(chosen.to_image().convert("RGB"), rotation)
        return _DecodedFrame(
            image=image,
            stream_index=int(stream.index),
            pts=int(chosen.pts) if chosen.pts is not None else None,
            time_base=Fraction(chosen.time_base) if chosen.time_base else time_base,
            frame_ordinal=ordinal,
            actual_timestamp=actual_timestamp,
            rotation_degrees=rotation,
        )

    def _add_collision_ordinal(self, container, stream, decoded: _DecodedFrame, stop_event) -> _DecodedFrame:
        """Disambiguate repeated presentation timestamps using source order."""
        container.seek(0, stream=stream, backward=True)
        for ordinal, frame in enumerate(container.decode(stream)):
            self._check_cancelled(stop_event)
            if frame.pts != decoded.pts:
                continue
            frame_time_base = frame.time_base or stream.time_base
            if frame_time_base != decoded.time_base:
                continue
            image = _apply_rotation(frame.to_image().convert("RGB"), decoded.rotation_degrees)
            if image.tobytes() == decoded.image.tobytes():
                return replace(decoded, frame_ordinal=ordinal)
        raise ValueError("Could not disambiguate duplicate video frame timestamp")

    @staticmethod
    def _rotation_degrees(stream) -> int:
        try:
            return int(round(float(stream.metadata.get("rotate", 0)))) % 360
        except (AttributeError, TypeError, ValueError):
            return 0

    def _store_frame(
        self,
        video_id: str,
        frame_id: str,
        decoded: _DecodedFrame,
        requested_timestamp: float,
        stop_event,
    ) -> FrameReference:
        self._check_cancelled(stop_event)
        rendition_id = hashlib.sha256(
            f"{frame_id}\0{FRAME_RENDITION_PROFILE}".encode()
        ).hexdigest()
        relative_path = f"{frame_id[:2]}/{rendition_id}.jpg"
        target = self._safe_cache_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".frame-", suffix=".tmp", dir=target.parent, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
            decoded.image.save(temporary_path, format="JPEG", quality=90)
            with temporary_path.open("rb") as image_file:
                checksum = hashlib.file_digest(image_file, "sha256").hexdigest()
                size_bytes = image_file.tell()
            self._evict_for(size_bytes)
            self._check_cancelled(stop_event)
            os.replace(temporary_path, target)
            temporary_path = None
            self.store.upsert_video_frame({
                "frame_id": frame_id,
                "video_id": video_id,
                "source_revision": video_id,
                "stream_index": decoded.stream_index,
                "pts": decoded.pts,
                "time_base_num": decoded.time_base.numerator if decoded.time_base else None,
                "time_base_den": decoded.time_base.denominator if decoded.time_base else None,
                "frame_ordinal": decoded.frame_ordinal,
                "actual_timestamp": decoded.actual_timestamp,
                "frame_id_version": FRAME_ID_VERSION,
            })
            self.store.upsert_video_frame_rendition({
                "rendition_id": rendition_id,
                "frame_id": frame_id,
                "profile": FRAME_RENDITION_PROFILE,
                "cache_relpath": relative_path,
                "checksum_sha256": checksum,
                "size_bytes": size_bytes,
                "width": decoded.image.width,
                "height": decoded.image.height,
                "rotation_degrees": decoded.rotation_degrees,
            })
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if target.exists() and self.store.get_video_frame_rendition(frame_id, FRAME_RENDITION_PROFILE) is None:
                target.unlink(missing_ok=True)
            raise
        return FrameReference(
            frame_id=frame_id,
            rendition_id=rendition_id,
            source_revision=video_id,
            stream_index=decoded.stream_index,
            pts=decoded.pts,
            time_base_num=decoded.time_base.numerator if decoded.time_base else None,
            time_base_den=decoded.time_base.denominator if decoded.time_base else None,
            frame_ordinal=decoded.frame_ordinal,
            requested_timestamp=requested_timestamp,
            actual_timestamp=decoded.actual_timestamp,
            width=decoded.image.width,
            height=decoded.image.height,
            rotation_degrees=decoded.rotation_degrees,
            cache_path=target,
            checksum_sha256=checksum,
            size_bytes=size_bytes,
        )

    def _evict_for(self, new_size: int) -> None:
        while self.store.video_frame_cache_size() + new_size > self.max_bytes:
            rendition = self.store.oldest_video_frame_rendition()
            if rendition is None:
                return
            self._remove_rendition(rendition)

    def _evict_to_budget(self) -> None:
        while self.store.video_frame_cache_size() > self.max_bytes:
            rendition = self.store.oldest_video_frame_rendition()
            if rendition is None:
                return
            self._remove_rendition(rendition)

    def _remove_rendition(self, rendition: dict[str, Any]) -> None:
        path = self._safe_cache_path(rendition["cache_relpath"])
        path.unlink(missing_ok=True)
        self.store.delete_video_frame_rendition(rendition["rendition_id"])

    def _safe_cache_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("Invalid frame cache path")
        root = self.cache_dir.resolve()
        path = (root / candidate).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Frame cache path escapes its root") from exc
        return path

    @staticmethod
    def _check_cancelled(stop_event) -> None:
        if stop_event is not None and stop_event.is_set():
            raise VideoFrameExtractionCancelled("Video frame extraction cancelled")
