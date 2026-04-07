from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_HOME_DIR_NAME = ".tokkit"
LEGACY_HOME_DIR_NAME = ".tokstat"
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _first_env_path(*names: str) -> Path | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    return None


def resolve_app_home() -> Path:
    explicit = _first_env_path("TOKKIT_HOME", "TOKSTAT_HOME")
    if explicit is not None:
        return explicit

    modern = Path.home() / DEFAULT_HOME_DIR_NAME
    legacy = Path.home() / LEGACY_HOME_DIR_NAME
    if modern.exists() or not legacy.exists():
        return modern
    return legacy


def default_db_path() -> Path:
    explicit = _first_env_path("TOKKIT_DB_PATH", "TOKSTAT_DB_PATH")
    if explicit is not None:
        return explicit
    return resolve_app_home() / "usage.sqlite"


def default_report_dir() -> Path:
    explicit = _first_env_path("TOKKIT_REPORT_DIR", "TOKSTAT_REPORT_DIR")
    if explicit is not None:
        return explicit
    return resolve_app_home() / "reports"


def default_log_dir() -> Path:
    explicit = _first_env_path("TOKKIT_LOG_DIR", "TOKSTAT_LOG_DIR")
    if explicit is not None:
        return explicit
    return resolve_app_home() / "logs"


def default_augment_capture_path() -> Path:
    explicit = _first_env_path("TOKKIT_AUGMENT_CAPTURE_PATH", "TOKSTAT_AUGMENT_CAPTURE_PATH")
    if explicit is not None:
        return explicit
    return resolve_app_home() / "augment-usage.ndjson"


DEFAULT_DB_PATH = default_db_path()


def get_timezone(name: str | None = None) -> ZoneInfo:
    if name:
        return ZoneInfo(name)
    local_tz = datetime.now().astimezone().tzinfo
    if isinstance(local_tz, ZoneInfo):
        return local_tz
    local_name = getattr(local_tz, "key", None) or datetime.now().astimezone().tzname()
    if not local_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(local_name)
    except Exception:
        return ZoneInfo("UTC")


def parse_timestamp(value: str, *, naive_tz: ZoneInfo | None = None) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            raise
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_tz or timezone.utc)
    return parsed


def local_date_for(value: str, tz: ZoneInfo, *, naive_tz: ZoneInfo | None = None) -> str:
    return parse_timestamp(value, naive_tz=naive_tz).astimezone(tz).date().isoformat()


def normalize_timestamp(value: str, *, naive_tz: ZoneInfo | None = None) -> str:
    return parse_timestamp(value, naive_tz=naive_tz).isoformat()


def today_string(tz: ZoneInfo) -> str:
    return datetime.now(tz).date().isoformat()


def format_int(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def format_float(value: float | None, precision: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{precision}f}"


def estimate_text_tokens(text: str) -> int:
    normalized = text.strip()
    if not normalized:
        return 0

    cjk_chars = len(_CJK_RE.findall(normalized))
    non_cjk_chars = len(_CJK_RE.sub("", normalized))
    return cjk_chars + max(1, math.ceil(non_cjk_chars / 4))
