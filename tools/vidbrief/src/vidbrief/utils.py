from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


def default_output_dir() -> Path:
    localized_downloads = Path.home() / "下载"
    if localized_downloads.exists():
        return localized_downloads

    downloads = Path.home() / "Downloads"
    if downloads.exists():
        return downloads

    return localized_downloads


DEFAULT_OUTPUT_DIR = default_output_dir()

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_WHITESPACE = re.compile(r"\s+")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def safe_stem(title: object | None, video_id: object | None = None, fallback: str = "video") -> str:
    raw_title = str(title or "").strip() or fallback
    cleaned = _INVALID_FILENAME_CHARS.sub(" ", raw_title)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > 160:
        cleaned = cleaned[:160].rstrip(" .")

    raw_id = str(video_id or "").strip()
    if raw_id and raw_id not in cleaned:
        return f"{cleaned} [{raw_id}]"
    return cleaned


def format_seconds(seconds: object | None) -> str:
    if seconds is None:
        return ""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return str(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="replace")
