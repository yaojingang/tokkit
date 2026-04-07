from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import UsageRecord, upsert_usage_record
from .utils import local_date_for


@dataclass(slots=True)
class ScanStats:
    lines_scanned: int = 0
    records_emitted: int = 0


def scan_augment(
    conn: sqlite3.Connection,
    *,
    capture_file: Path,
    tz: ZoneInfo,
) -> ScanStats:
    stats = ScanStats()
    conn.execute("DELETE FROM usage_records WHERE app = 'augment'")
    if not capture_file.exists():
        conn.commit()
        return stats

    best_records: dict[str, dict[str, object]] = {}
    try:
        with capture_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                stats.lines_scanned += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                record = _normalize_capture_record(payload, capture_file)
                if record is None:
                    continue
                request_id = str(record["request_id"])
                previous = best_records.get(request_id)
                if previous is None or _record_rank(record) >= _record_rank(previous):
                    best_records[request_id] = record
    except OSError:
        conn.commit()
        return stats

    for record in best_records.values():
        stats.records_emitted += 1
        upsert_usage_record(
            conn,
            UsageRecord(
                source=str(record["source"]),
                app="augment",
                external_id=str(record["external_id"]),
                started_at=str(record["started_at"]),
                local_date=local_date_for(str(record["started_at"]), tz),
                measurement_method="exact",
                model=str(record["model"]) if record["model"] else None,
                input_tokens=int(record["input_tokens"]),
                output_tokens=int(record["output_tokens"]),
                cached_input_tokens=int(record["cached_input_tokens"]),
                reasoning_tokens=None,
                total_tokens=int(record["total_tokens"]),
                credits=float(record["credits"]) if record["credits"] is not None else None,
                category=str(record["category"]) if record["category"] else None,
                workspace=str(record["workspace"]) if record["workspace"] else None,
                metadata=dict(record["metadata"]),
            ),
        )
    conn.commit()
    return stats


def _normalize_capture_record(payload: object, capture_file: Path) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None

    request_id = _string_value(payload, "request_id", "requestId", "external_id")
    started_at = _string_value(payload, "started_at", "captured_at", "capturedAt")
    if not request_id or not started_at:
        return None

    direct_input = _int_value(payload, "input_tokens")
    cache_creation = _int_value(payload, "cache_creation_input_tokens")
    cache_read = _int_value(payload, "cache_read_input_tokens")
    output_tokens = _int_value(payload, "output_tokens")
    credits = _float_value(payload, "credits", "credits_consumed")

    input_tokens = direct_input + cache_creation
    cached_input_tokens = cache_read
    total_tokens = input_tokens + cached_input_tokens + output_tokens
    if total_tokens <= 0 and credits is None:
        return None

    source = _string_value(payload, "source") or "augment:vscode"
    endpoint = _string_value(payload, "endpoint", "route")
    request_model = _string_value(payload, "model", "request_model")
    response_model = _string_value(payload, "response_model", "model_id")
    metadata = {
        "capture_file": str(capture_file),
        "endpoint": endpoint,
        "url": _string_value(payload, "url"),
        "session_id": _string_value(payload, "session_id", "sessionId"),
        "conversation_id": _string_value(payload, "conversation_id"),
        "mode": _string_value(payload, "mode"),
        "path": _string_value(payload, "path"),
        "request_model": request_model,
        "response_model": response_model,
        "capture_version": _string_value(payload, "capture_version"),
        "capture_kind": _string_value(payload, "kind"),
    }

    return {
        "request_id": request_id,
        "external_id": f"augment:{request_id}",
        "started_at": started_at,
        "source": source,
        "model": response_model or request_model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "total_tokens": total_tokens,
        "credits": credits,
        "category": endpoint,
        "workspace": _string_value(payload, "workspace", "workspace_root"),
        "metadata": {key: value for key, value in metadata.items() if value},
    }


def _record_rank(record: dict[str, object]) -> tuple[int, float, str]:
    return (
        int(record["total_tokens"]),
        float(record["credits"] or 0.0),
        str(record["started_at"]),
    )


def _string_value(payload: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return ""


def _int_value(payload: dict[str, object], *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                continue
            try:
                return int(float(normalized))
            except ValueError:
                continue
    return 0


def _float_value(payload: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                continue
            try:
                return float(normalized)
            except ValueError:
                continue
    return None
