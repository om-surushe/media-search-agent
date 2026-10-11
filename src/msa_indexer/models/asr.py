"""Local speech transcription backed by OpenAI Whisper."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import numpy as np

WHISPER_MODEL_NAME = "openai/whisper-base"
WHISPER_MODEL_SIZE = "base"
WHISPER_MODEL_REVISION = (
    "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e"
)
WHISPER_RUNTIME_VERSION = "20250625"


class TranscriptSegment(TypedDict):
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    status: str
    language: str | None = None
    segments: tuple[TranscriptSegment, ...] = ()
    error_code: str | None = None


class LocalWhisperTranscriber:
    """Lazy-load one local Whisper model and reuse it for this indexing run."""

    def __init__(self, models_dir: Path, device: str = "cpu"):
        self.models_dir = Path(models_dir) / "whisper"
        # Whisper's sparse decoder is not supported by the project's PyTorch MPS runtime.
        self.device = device if device == "cpu" or device.startswith("cuda") else "cpu"
        self._model = None
        self._load_failed = False

    def _get_model(self):
        if self._model is not None:
            return self._model
        if self._load_failed:
            raise RuntimeError("Whisper model is unavailable")
        try:
            import whisper

            self.models_dir.mkdir(parents=True, exist_ok=True)
            self._model = whisper.load_model(
                WHISPER_MODEL_SIZE,
                device=self.device,
                download_root=str(self.models_dir),
            )
            return self._model
        except Exception:
            self._load_failed = True
            raise

    @staticmethod
    def _decode_audio(path: Path) -> tuple[np.ndarray | None, float]:
        import av

        with av.open(str(path)) as container:
            if not container.streams.audio:
                return None, 0.0
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
            chunks: list[np.ndarray] = []
            offset = 0.0
            first_frame = True
            for frame in container.decode(stream):
                if first_frame:
                    first_frame = False
                    if frame.pts is not None and frame.time_base is not None:
                        media_start = (container.start_time or 0) / av.time_base
                        offset = max(0.0, float(frame.pts * frame.time_base) - media_start)
                chunks.extend(
                    out.to_ndarray().reshape(-1)
                    for out in resampler.resample(frame)
                )
            chunks.extend(
                out.to_ndarray().reshape(-1) for out in resampler.resample(None)
            )
        # ponytail: whole waveform in RAM; stream windows if multi-hour videos become a real workload.
        return (np.concatenate(chunks).astype(np.float32, copy=False), offset) if chunks else (None, offset)

    def transcribe(self, path: Path) -> TranscriptResult:
        import av

        try:
            audio, offset = self._decode_audio(Path(path))
        except av.error.FFmpegError:
            return TranscriptResult("unsupported", error_code="audio_decode_failed")
        if audio is None or audio.size == 0:
            return TranscriptResult("no_speech")

        result = self._get_model().transcribe(audio, fp16=self.device != "cpu")
        segments: list[TranscriptSegment] = []
        for segment in result.get("segments", []):
            text = " ".join(str(segment.get("text", "")).split())
            start = float(segment.get("start", 0.0)) + offset
            end = float(segment.get("end", 0.0)) + offset
            if text and np.isfinite(start) and np.isfinite(end) and 0 <= start < end:
                segments.append(TranscriptSegment(start=start, end=end, text=text))
        return TranscriptResult(
            "transcribed" if segments else "no_speech",
            language=result.get("language"),
            segments=tuple(segments),
        )
