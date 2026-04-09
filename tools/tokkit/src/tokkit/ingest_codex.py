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
    files_scanned: int = 0
    records_seen: int = 0


def _extract_turn_model(payload: dict[str, object]) -> str | None:
    model = payload.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()

    collaboration_mode = payload.get("collaboration_mode")
    if isinstance(collaboration_mode, dict):
        nested_model = collaboration_mode.get("model")
        if isinstance(nested_model, str) and nested_model.strip():
            return nested_model.strip()
        settings = collaboration_mode.get("settings")
        if isinstance(settings, dict):
            settings_model = settings.get("model")
            if isinstance(settings_model, str) and settings_model.strip():
                return settings_model.strip()

    return None


def _iter_session_files(codex_home: Path) -> list[Path]:
    files: list[Path] = []
    archived = codex_home / "archived_sessions"
    current = codex_home / "sessions"
    if archived.exists():
        files.extend(sorted(archived.glob("*.jsonl")))
    if current.exists():
        files.extend(sorted(current.glob("**/*.jsonl")))
    return files


def scan_codex(
    conn: sqlite3.Connection,
    *,
    codex_home: Path,
    tz: ZoneInfo,
) -> ScanStats:
    stats = ScanStats()
    for session_file in _iter_session_files(codex_home):
        stats.files_scanned += 1
        _scan_session_file(conn, session_file, tz, stats)
    conn.commit()
    return stats


def _scan_session_file(
    conn: sqlite3.Connection,
    session_file: Path,
    tz: ZoneInfo,
    stats: ScanStats,
) -> None:
    session_id = None
    session_source = None
    cwd = None
    originator = None
    model_provider = None
    current_model = None
    current_turn_id = None

    with session_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            payload = event.get("payload") or {}
            if event.get("type") == "session_meta":
                session_id = payload.get("id") or session_id
                session_source = payload.get("source") or session_source
                cwd = payload.get("cwd") or cwd
                originator = payload.get("originator") or originator
                model_provider = payload.get("model_provider") or model_provider
                continue

            if event.get("type") == "turn_context":
                current_turn_id = payload.get("turn_id") or current_turn_id
                current_model = _extract_turn_model(payload) or current_model
                cwd = payload.get("cwd") or cwd
                continue

            if event.get("type") != "event_msg":
                continue
            if payload.get("type") != "token_count":
                continue

            info = payload.get("info") or {}
            usage = info.get("last_token_usage") or {}
            if not usage:
                continue

            timestamp = event.get("timestamp")
            if not timestamp:
                continue

            stats.records_seen += 1
            upsert_usage_record(
                conn,
                UsageRecord(
                    source=f"codex:{session_source or 'unknown'}",
                    app="codex",
                    external_id=f"{session_id or session_file.name}:{timestamp}",
                    started_at=timestamp,
                    local_date=local_date_for(timestamp, tz),
                    measurement_method="exact",
                    model=current_model,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    cached_input_tokens=usage.get("cached_input_tokens"),
                    reasoning_tokens=usage.get("reasoning_output_tokens"),
                    total_tokens=usage.get("total_tokens"),
                    category=session_source,
                    workspace=cwd,
                    metadata={
                        "session_id": session_id,
                        "session_file": str(session_file),
                        "originator": originator,
                        "turn_id": current_turn_id,
                        "turn_model": current_model,
                        "model_provider": model_provider,
                        "model_context_window": info.get("model_context_window"),
                    },
                ),
            )
