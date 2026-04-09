from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from .db import UsageRecord, get_app_scan_state, upsert_app_scan_state, upsert_usage_record
from .utils import estimate_text_tokens, local_date_for


@dataclass(slots=True)
class CodeBuddyScanStats:
    tasks_seen: int = 0
    records_emitted: int = 0


def scan_codebuddy(
    conn: sqlite3.Connection,
    *,
    tasks_root: Path,
    tz: ZoneInfo,
) -> CodeBuddyScanStats:
    stats = CodeBuddyScanStats()
    if not tasks_root.exists():
        return stats

    for task_dir in sorted(path for path in tasks_root.iterdir() if path.is_dir()):
        context_path = task_dir / "context_history.json"
        if not context_path.exists():
            continue
        stats.tasks_seen += 1
        _scan_task_dir(conn, task_dir, context_path, tz, stats)

    conn.commit()
    return stats


def _scan_task_dir(
    conn: sqlite3.Connection,
    task_dir: Path,
    context_path: Path,
    tz: ZoneInfo,
    stats: CodeBuddyScanStats,
) -> None:
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception:
        return

    text_fragments: list[str] = []
    timestamps_ms: list[int] = []
    _collect_text_and_timestamps(payload, text_fragments, timestamps_ms)
    if not text_fragments:
        return

    estimated_total = sum(estimate_text_tokens(fragment) for fragment in text_fragments)
    latest_seen_at = _resolve_latest_seen_at(context_path, timestamps_ms, tz)
    task_id = task_dir.name
    state_key = f"codebuddy:{task_id}"
    previous = get_app_scan_state(conn, state_key)
    previous_total = int(previous["total_tokens"]) if previous else 0
    delta_tokens = max(estimated_total - previous_total, 0)

    task_metadata = _load_json(task_dir / "task_metadata.json")
    workspace = _extract_workspace(task_metadata)
    metadata = {
        "task_id": task_id,
        "task_dir": str(task_dir),
        "text_fragments": len(text_fragments),
        "files_in_context_count": len(task_metadata.get("files_in_context", []))
        if isinstance(task_metadata.get("files_in_context"), list)
        else 0,
        "estimated_total_tokens": estimated_total,
        "estimation_method": "cjk_chars_plus_non_cjk_chars_div_4",
        "latest_context_timestamp_ms": max(timestamps_ms) if timestamps_ms else None,
    }

    if delta_tokens > 0:
        stats.records_emitted += 1
        upsert_usage_record(
            conn,
            UsageRecord(
                source="codebuddy:local-history",
                app="codebuddy",
                external_id=f"{task_id}:{latest_seen_at}:{estimated_total}",
                started_at=latest_seen_at,
                local_date=local_date_for(latest_seen_at, tz),
                measurement_method="estimated",
                total_tokens=delta_tokens,
                category="local-history",
                workspace=workspace,
                metadata=metadata,
            ),
        )

    upsert_app_scan_state(
        conn,
        state_key=state_key,
        app="codebuddy",
        source="codebuddy:local-history",
        total_tokens=estimated_total,
        last_seen_at=latest_seen_at,
        metadata=metadata,
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _collect_text_and_timestamps(value: Any, texts: list[str], timestamps_ms: list[int]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _collect_text_and_timestamps(item, texts, timestamps_ms)
        return

    if not isinstance(value, list):
        return

    if (
        len(value) >= 3
        and isinstance(value[0], (int, float))
        and isinstance(value[1], str)
        and value[1] == "text"
        and isinstance(value[2], list)
    ):
        timestamps_ms.append(int(value[0]))
        for fragment in value[2]:
            if isinstance(fragment, str) and fragment.strip():
                texts.append(fragment)

    for item in value:
        _collect_text_and_timestamps(item, texts, timestamps_ms)


def _resolve_latest_seen_at(context_path: Path, timestamps_ms: list[int], tz: ZoneInfo) -> str:
    if timestamps_ms:
        return datetime.fromtimestamp(max(timestamps_ms) / 1000, tz=tz).isoformat()
    return datetime.fromtimestamp(context_path.stat().st_mtime, tz=tz).isoformat()


def _extract_workspace(task_metadata: dict[str, Any]) -> str | None:
    files = task_metadata.get("files_in_context")
    if not isinstance(files, list):
        return None

    resolved_paths: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path.startswith("file://"):
            continue
        parsed = urlsplit(raw_path)
        resolved = unquote(parsed.path)
        if resolved:
            resolved_paths.append(resolved)

    if not resolved_paths:
        return None

    try:
        return str(Path(resolved_paths[0]).parent)
    except Exception:
        return None
