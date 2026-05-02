from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ai import DEFAULT_TRANSCRIBE_MODEL, build_report_prompt, choose_report_provider, generate_report, transcribe_audio_openai
from .audio import extract_audio, split_audio
from .downloader import DEFAULT_VIDEO_FORMAT, DownloadResult, download_url
from .subtitles import choose_subtitle_file, read_subtitle_text
from .utils import ensure_dir, safe_stem


@dataclass
class TranscriptResult:
    transcript_path: Path
    transcript_text: str
    source: str
    audio_file: Path | None = None


@dataclass
class WorkflowResult:
    download: DownloadResult
    transcript: TranscriptResult
    report_path: Path
    report_provider: str


def run_video_report(
    url: str,
    output_dir: Path,
    *,
    video_format: str = DEFAULT_VIDEO_FORMAT,
    cookies_from_browser: str | None = None,
    cookie_file: Path | None = None,
    playlist: bool = False,
    sub_langs: list[str] | None = None,
    transcribe_provider: str = "auto",
    transcribe_model: str = DEFAULT_TRANSCRIBE_MODEL,
    report_provider: str = "auto",
    report_model: str | None = None,
    output_language: str = "zh-CN",
    keep_audio: bool = False,
    quiet: bool = False,
) -> WorkflowResult:
    output_dir = ensure_dir(output_dir)
    download = download_url(
        url,
        output_dir,
        video_format=video_format,
        write_subs=True,
        sub_langs=sub_langs,
        cookies_from_browser=cookies_from_browser,
        cookie_file=cookie_file,
        playlist=playlist,
        quiet=quiet,
        download=True,
    )
    transcript = transcript_from_download(
        download,
        output_dir,
        provider=transcribe_provider,
        model=transcribe_model,
        output_language=output_language,
        keep_audio=keep_audio,
    )
    prompt = build_report_prompt(download.metadata(), transcript.transcript_text, language=output_language)
    resolved_report_provider = choose_report_provider(report_provider)
    report = generate_report(prompt, provider=resolved_report_provider, output_dir=output_dir, model=report_model)
    report_path = _artifact_path(output_dir, download, "report.md")
    report_path.write_text(report.rstrip() + "\n", encoding="utf-8")
    return WorkflowResult(
        download=download,
        transcript=transcript,
        report_path=report_path,
        report_provider=resolved_report_provider,
    )


def transcript_from_download(
    download: DownloadResult,
    output_dir: Path,
    *,
    provider: str = "auto",
    model: str = DEFAULT_TRANSCRIBE_MODEL,
    output_language: str = "zh-CN",
    keep_audio: bool = False,
) -> TranscriptResult:
    subtitle_file = choose_subtitle_file(download.subtitle_files)
    if subtitle_file:
        text = read_subtitle_text(subtitle_file)
        if text:
            transcript_path = _artifact_path(output_dir, download, "transcript.md")
            _write_transcript(transcript_path, text, source=str(subtitle_file))
            return TranscriptResult(transcript_path=transcript_path, transcript_text=text, source=str(subtitle_file))

    if provider == "none":
        raise RuntimeError("no subtitle transcript found and transcription provider is disabled")
    if provider not in {"auto", "openai"}:
        raise RuntimeError(f"unsupported transcription provider: {provider}")
    if not download.media_file:
        raise RuntimeError("no downloaded media file is available for transcription")

    audio_path = extract_audio(download.media_file, output_dir, stem=download.title)
    chunks = split_audio(audio_path, output_dir)
    text = transcribe_audio_openai(chunks, model=model, language=_openai_language(output_language))
    if not text:
        raise RuntimeError("transcription returned empty text")

    transcript_path = _artifact_path(output_dir, download, "transcript.md")
    _write_transcript(transcript_path, text, source=str(audio_path))
    if not keep_audio:
        _cleanup_audio_files(audio_path, chunks)
    return TranscriptResult(transcript_path=transcript_path, transcript_text=text, source=str(audio_path), audio_file=audio_path)


def transcribe_media_file(
    media_file: Path,
    output_dir: Path,
    *,
    provider: str = "openai",
    model: str = DEFAULT_TRANSCRIBE_MODEL,
    output_language: str = "zh-CN",
    keep_audio: bool = True,
) -> TranscriptResult:
    if provider not in {"auto", "openai"}:
        raise RuntimeError(f"unsupported transcription provider: {provider}")
    output_dir = ensure_dir(output_dir)
    audio_path = extract_audio(media_file, output_dir, stem=media_file.stem)
    chunks = split_audio(audio_path, output_dir)
    text = transcribe_audio_openai(chunks, model=model, language=_openai_language(output_language))
    transcript_path = output_dir / f"{safe_stem(media_file.stem)}.transcript.md"
    _write_transcript(transcript_path, text, source=str(audio_path))
    if not keep_audio:
        _cleanup_audio_files(audio_path, chunks)
    return TranscriptResult(transcript_path=transcript_path, transcript_text=text, source=str(audio_path), audio_file=audio_path)


def report_from_transcript_file(
    transcript_file: Path,
    output_dir: Path,
    *,
    provider: str = "auto",
    model: str | None = None,
    output_language: str = "zh-CN",
) -> Path:
    output_dir = ensure_dir(output_dir)
    transcript = transcript_file.read_text(encoding="utf-8", errors="replace")
    metadata = {"title": transcript_file.stem}
    prompt = build_report_prompt(metadata, transcript, language=output_language)
    report = generate_report(prompt, provider=provider, output_dir=output_dir, model=model)
    report_path = output_dir / f"{safe_stem(transcript_file.stem)}.report.md"
    report_path.write_text(report.rstrip() + "\n", encoding="utf-8")
    return report_path


def _artifact_path(output_dir: Path, download: DownloadResult, suffix: str) -> Path:
    return output_dir / f"{safe_stem(download.title, download.video_id)}.{suffix}"


def _write_transcript(path: Path, text: str, *, source: str) -> None:
    body = f"# Transcript\n\nSource: {source}\n\n{text.strip()}\n"
    path.write_text(body, encoding="utf-8")


def _openai_language(language: str) -> str | None:
    normalized = language.lower()
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return None


def _cleanup_audio_files(audio_path: Path, chunks: list[Path]) -> None:
    for chunk in chunks:
        chunk.unlink(missing_ok=True)
    audio_path.unlink(missing_ok=True)
    for parent in {chunk.parent for chunk in chunks if chunk.parent != audio_path.parent}:
        try:
            parent.rmdir()
        except OSError:
            pass
