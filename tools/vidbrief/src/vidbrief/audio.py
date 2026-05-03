from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .utils import ensure_dir, safe_stem


class AudioError(RuntimeError):
    pass


def extract_audio(media_file: Path, output_dir: Path, *, stem: str | None = None, bitrate: str = "48k") -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioError("ffmpeg is required to extract audio from media files")

    output_dir = ensure_dir(output_dir)
    output_path = output_dir / f"{safe_stem(stem or media_file.stem)}.audio.mp3"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(media_file),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        bitrate,
        str(output_path),
    ]
    _run_ffmpeg(command, "extract audio")
    return output_path


def split_audio(
    audio_file: Path,
    output_dir: Path,
    *,
    max_bytes: int = 24 * 1024 * 1024,
    segment_seconds: int = 600,
) -> list[Path]:
    if audio_file.stat().st_size <= max_bytes:
        return [audio_file]

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioError("ffmpeg is required to split large audio files")

    chunk_dir = ensure_dir(output_dir / f"{audio_file.stem}.chunks")
    for old_chunk in chunk_dir.glob("*.mp3"):
        old_chunk.unlink()

    pattern = chunk_dir / "%03d.mp3"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(audio_file),
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-reset_timestamps",
        "1",
        "-c",
        "copy",
        str(pattern),
    ]
    _run_ffmpeg(command, "split audio")
    chunks = sorted(chunk_dir.glob("*.mp3"))
    if not chunks:
        raise AudioError("ffmpeg did not create any audio chunks")
    oversized = [path for path in chunks if path.stat().st_size > max_bytes]
    if oversized:
        names = ", ".join(path.name for path in oversized[:3])
        raise AudioError(f"audio chunks are still too large for transcription: {names}")
    return chunks


def _run_ffmpeg(command: list[str], label: str) -> None:
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise AudioError(f"ffmpeg failed to {label}: {detail}")
