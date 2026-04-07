from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import UsageRecord, upsert_usage_record
from .utils import local_date_for


@dataclass(slots=True)
class CursorScanStats:
    events_seen: int = 0
    records_emitted: int = 0


def scan_cursor(
    conn: sqlite3.Connection,
    *,
    sentry_scope_path: Path,
    tz: ZoneInfo,
) -> CursorScanStats:
    stats = CursorScanStats()
    if not sentry_scope_path.exists():
        return stats

    try:
        payload = json.loads(sentry_scope_path.read_text(encoding="utf-8"))
    except Exception:
        return stats

    breadcrumbs = payload.get("scope", {}).get("breadcrumbs", [])
    if not isinstance(breadcrumbs, list):
        return stats

    for index, crumb in enumerate(breadcrumbs):
        if not isinstance(crumb, dict) or crumb.get("message") != "ex_hs2":
            continue

        data = crumb.get("data")
        if not isinstance(data, dict):
            continue

        total_tokens = data.get("n")
        session_id = data.get("sessionId")
        timestamp_ms = data.get("ts")
        tool = data.get("tool")
        if not isinstance(total_tokens, int) or total_tokens <= 0:
            continue
        if not isinstance(session_id, str) or not session_id:
            continue
        if not isinstance(timestamp_ms, (int, float)):
            continue

        started_at = datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=tz).isoformat()
        stats.events_seen += 1
        stats.records_emitted += 1
        upsert_usage_record(
            conn,
            UsageRecord(
                source="cursor:sentry",
                app="cursor",
                external_id=f"{session_id}:{int(timestamp_ms)}:{tool or 'unknown'}:{total_tokens}:{index}",
                started_at=started_at,
                local_date=local_date_for(started_at, tz),
                measurement_method="estimated",
                total_tokens=total_tokens,
                category=_tool_label(tool),
                metadata={
                    "session_id": session_id,
                    "tool": tool,
                    "sentry_scope_path": str(sentry_scope_path),
                    "estimation_method": "cursor_sentry_ex_hs2_n",
                    "notes": "Estimated from local Cursor sentry ex_hs2 telemetry; not a billable token ledger.",
                },
            ),
        )

    conn.commit()
    return stats


def _tool_label(tool: object) -> str:
    if not isinstance(tool, str):
        return "unknown"
    normalized = tool.strip().lower()
    if normalized == "cx":
        return "composer"
    if normalized == "ac":
        return "agent"
    return normalized or "unknown"
