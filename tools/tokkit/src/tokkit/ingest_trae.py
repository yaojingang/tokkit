from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import UsageRecord, upsert_usage_record
from .utils import local_date_for


_WORKSPACE_RE = re.compile(r"# Current Working Directory \(([^)]+)\)")


@dataclass(slots=True)
class TraeScanStats:
    tasks_seen: int = 0
    request_events_seen: int = 0
    records_emitted: int = 0


def scan_trae(
    conn: sqlite3.Connection,
    *,
    tasks_root: Path,
    tz: ZoneInfo,
) -> TraeScanStats:
    stats = TraeScanStats()
    if not tasks_root.exists():
        return stats

    for task_dir in sorted(path for path in tasks_root.iterdir() if path.is_dir()):
        ui_messages = task_dir / "ui_messages.json"
        if not ui_messages.exists():
            continue
        stats.tasks_seen += 1
        _scan_task_ui_messages(conn, task_dir, ui_messages, tz, stats)

    conn.commit()
    return stats


def _scan_task_ui_messages(
    conn: sqlite3.Connection,
    task_dir: Path,
    ui_messages_path: Path,
    tz: ZoneInfo,
    stats: TraeScanStats,
) -> None:
    try:
        payload = json.loads(ui_messages_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, list):
        return

    task_id = task_dir.name
    for idx, event in enumerate(payload):
        if not isinstance(event, dict):
            continue
        if str(event.get("type") or "") != "say":
            continue
        if str(event.get("say") or "") != "api_req_started":
            continue

        raw_text = event.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        try:
            request_payload = json.loads(raw_text)
        except Exception:
            continue
        if not isinstance(request_payload, dict):
            continue

        stats.request_events_seen += 1

        tokens_in = _as_int(request_payload.get("tokensIn"))
        tokens_out = _as_int(request_payload.get("tokensOut"))
        cache_writes = _as_int(request_payload.get("cacheWrites"))
        cache_reads = _as_int(request_payload.get("cacheReads"))
        reported_cost = _as_float(request_payload.get("cost"))
        started_at = _resolve_started_at(event, ui_messages_path, tz)
        request_text = str(request_payload.get("request") or "")
        workspace = _extract_workspace(request_text)
        total_tokens = tokens_in + tokens_out + cache_writes + cache_reads

        metadata = {
            "task_id": task_id,
            "task_dir": str(task_dir),
            "ui_messages_path": str(ui_messages_path),
            "conversation_history_index": event.get("conversationHistoryIndex"),
            "source_extension": "huohuaai.huohuaai",
            "cache_writes": cache_writes,
            "cache_reads": cache_reads,
            "reported_cost": reported_cost,
            "notes": (
                "Exact token fields were recovered from Trae extension task history. "
                "This covers detected huohuaai task requests, not all native Trae traffic."
            ),
        }

        stats.records_emitted += 1
        upsert_usage_record(
            conn,
            UsageRecord(
                source="trae:huohuaai-task-history",
                app="trae",
                external_id=f"{task_id}:{idx}:{int(event.get('ts') or 0)}",
                started_at=started_at,
                local_date=local_date_for(started_at, tz),
                measurement_method="exact",
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                cached_input_tokens=cache_reads if cache_reads > 0 else None,
                total_tokens=total_tokens,
                category="task-history",
                workspace=workspace,
                metadata=metadata,
            ),
        )


def _resolve_started_at(event: dict[str, Any], ui_messages_path: Path, tz: ZoneInfo) -> str:
    value = event.get("ts")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=tz).isoformat()
    return datetime.fromtimestamp(ui_messages_path.stat().st_mtime, tz=tz).isoformat()


def _extract_workspace(request_text: str) -> str | None:
    if not request_text:
        return None
    match = _WORKSPACE_RE.search(request_text)
    if match:
        return match.group(1)
    return None


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except Exception:
            return 0
    return 0


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return None
    return None
