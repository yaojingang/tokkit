from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .subtitles import discover_subtitle_files
from .utils import ensure_dir


MEDIA_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".mkv",
    ".webm",
    ".mp3",
    ".m4a",
    ".opus",
    ".wav",
    ".aac",
    ".flac",
}

DEFAULT_SUBTITLE_LANGS = ["zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "zh", "en-US", "en-GB", "en"]
DEFAULT_VIDEO_FORMAT = "bv*[height<=720]+ba/best[height<=720]/best"


@dataclass
class DownloadResult:
    url: str
    output_dir: Path
    info: dict[str, Any]
    media_file: Path | None = None
    info_json: Path | None = None
    subtitle_files: list[Path] = field(default_factory=list)

    @property
    def title(self) -> str:
        return str(self.info.get("title") or self.info.get("fulltitle") or "video")

    @property
    def video_id(self) -> str:
        return str(self.info.get("id") or "")

    def metadata(self) -> dict[str, Any]:
        keys = (
            "id",
            "title",
            "fulltitle",
            "uploader",
            "channel",
            "duration",
            "upload_date",
            "webpage_url",
            "original_url",
            "description",
        )
        return {key: self.info.get(key) for key in keys if self.info.get(key) is not None}


def parse_cookies_from_browser(value: str) -> tuple[str, str | None, str | None, str | None]:
    raw = value.strip()
    if not raw:
        raise ValueError("--cookies-from-browser cannot be empty")

    container = None
    if "::" in raw:
        raw, container = raw.split("::", 1)
        container = container or None

    profile = None
    if ":" in raw:
        raw, profile = raw.split(":", 1)
        profile = profile or None

    keyring = None
    if "+" in raw:
        browser, keyring = raw.split("+", 1)
        keyring = keyring or None
    else:
        browser = raw

    browser = browser.strip().lower()
    if not browser:
        raise ValueError("--cookies-from-browser must include a browser name")
    return (browser, profile, keyring, container)


def download_url(
    url: str,
    output_dir: Path,
    *,
    video_format: str = DEFAULT_VIDEO_FORMAT,
    audio_only: bool = False,
    write_subs: bool = True,
    sub_langs: list[str] | None = None,
    cookies_from_browser: str | None = None,
    cookie_file: Path | None = None,
    playlist: bool = False,
    quiet: bool = False,
    download: bool = True,
) -> DownloadResult:
    yt_dlp = _load_yt_dlp()
    output_dir = ensure_dir(output_dir)
    completed_files: list[Path] = []

    def progress_hook(status: dict[str, Any]) -> None:
        filename = status.get("filename")
        if status.get("status") == "finished" and filename:
            completed_files.append(Path(filename))

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best" if audio_only else video_format,
        "outtmpl": "%(title).200B [%(id)s].%(ext)s",
        "paths": {"home": str(output_dir)},
        "noplaylist": not playlist,
        "writeinfojson": download,
        "writesubtitles": write_subs,
        "writeautomaticsub": write_subs,
        "subtitlesformat": "vtt/srt/best",
        "subtitleslangs": sub_langs or DEFAULT_SUBTITLE_LANGS,
        "ignoreerrors": True,
        "merge_output_format": "mp4",
        "quiet": quiet,
        "no_warnings": quiet,
        "noprogress": quiet,
        "progress_hooks": [progress_hook],
    }

    if audio_only:
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    if not download:
        ydl_opts["skip_download"] = True
        ydl_opts["writeinfojson"] = False
    if cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = parse_cookies_from_browser(cookies_from_browser)
    if cookie_file:
        ydl_opts["cookiefile"] = str(cookie_file)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        raw_info = ydl.extract_info(url, download=download)
        if raw_info is None:
            raise RuntimeError(f"yt-dlp did not return video metadata for: {url}")
        info = ydl.sanitize_info(raw_info)

    video_id = str(info.get("id") or "")
    result = DownloadResult(
        url=url,
        output_dir=output_dir,
        info=info,
        media_file=_discover_media_file(output_dir, info, completed_files),
        info_json=_discover_info_json(output_dir, video_id),
        subtitle_files=discover_subtitle_files(output_dir, video_id or None),
    )
    return result


def _load_yt_dlp() -> Any:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is required. Install this tool with: python3 -m pip install -e .") from exc
    return yt_dlp


def _discover_info_json(output_dir: Path, video_id: str) -> Path | None:
    candidates = []
    for path in output_dir.iterdir():
        if not path.is_file() or not path.name.endswith(".info.json"):
            continue
        if video_id and video_id not in path.name:
            continue
        candidates.append(path)
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _discover_media_file(output_dir: Path, info: dict[str, Any], completed_files: list[Path]) -> Path | None:
    for path in reversed(completed_files):
        if path.exists() and path.suffix.lower() in MEDIA_EXTENSIONS:
            return path

    for item in info.get("requested_downloads") or []:
        filepath = item.get("filepath") or item.get("filename")
        if filepath:
            path = Path(filepath)
            if path.exists() and path.suffix.lower() in MEDIA_EXTENSIONS:
                return path

    video_id = str(info.get("id") or "")
    candidates: list[Path] = []
    for path in output_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        if video_id and video_id not in path.name:
            continue
        candidates.append(path)
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
