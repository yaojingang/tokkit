from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .utils import read_text_file


SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".json3", ".srv1", ".srv2", ".srv3"}
LANGUAGE_PRIORITY = (
    "zh-Hans",
    "zh-Hant",
    "zh-CN",
    "zh-TW",
    "zh",
    "en",
    "en-US",
    "en-GB",
)

_TIMING_LINE = re.compile(
    r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s+-->\s+\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}"
)
_TAG = re.compile(r"<[^>]+>")
_JSON3_NEWLINE = re.compile(r"\s*\n\s*")


def discover_subtitle_files(directory: Path, video_id: str | None = None) -> list[Path]:
    files: list[Path] = []
    if not directory.exists():
        return files
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if path.suffix not in SUBTITLE_EXTENSIONS:
            continue
        if "live_chat" in path.name:
            continue
        if video_id and video_id not in path.name:
            continue
        files.append(path)
    return sorted(files, key=subtitle_sort_key)


def choose_subtitle_file(files: list[Path]) -> Path | None:
    return sorted(files, key=subtitle_sort_key)[0] if files else None


def subtitle_sort_key(path: Path) -> tuple[int, int, str]:
    name = path.name.lower()
    language_score = len(LANGUAGE_PRIORITY)
    for index, language in enumerate(LANGUAGE_PRIORITY):
        token = language.lower()
        if f".{token}." in name or name.endswith(f".{token}{path.suffix.lower()}"):
            language_score = index
            break
    extension_score = {".vtt": 0, ".srt": 1, ".json3": 2}.get(path.suffix, 3)
    return (language_score, extension_score, path.name)


def read_subtitle_text(path: Path) -> str:
    if path.suffix == ".json3":
        return _read_json3(path)
    return _read_plain_subtitle(path)


def _read_json3(path: Path) -> str:
    payload = json.loads(read_text_file(path))
    lines: list[str] = []
    for event in payload.get("events", []):
        parts = event.get("segs") or []
        text = "".join(str(part.get("utf8", "")) for part in parts)
        text = _JSON3_NEWLINE.sub(" ", text).strip()
        if text:
            lines.append(text)
    return _dedupe_join(lines)


def _read_plain_subtitle(path: Path) -> str:
    lines: list[str] = []
    skip_note = False

    for raw_line in read_text_file(path).splitlines():
        line = raw_line.strip()
        if not line:
            skip_note = False
            continue
        if skip_note:
            continue
        if line in {"WEBVTT", "STYLE", "REGION"}:
            skip_note = line in {"STYLE", "REGION"}
            continue
        if line.startswith(("NOTE", "Kind:", "Language:")):
            skip_note = line.startswith("NOTE")
            continue
        if line.isdigit() or _TIMING_LINE.match(line):
            continue

        cleaned = html.unescape(_TAG.sub("", line)).strip()
        if cleaned:
            lines.append(cleaned)

    return _dedupe_join(lines)


def _dedupe_join(lines: list[str]) -> str:
    result: list[str] = []
    previous = None
    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized or normalized == previous:
            continue
        result.append(normalized)
        previous = normalized
    return "\n".join(result).strip()
