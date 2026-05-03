from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import (
    UsageRecord,
    get_file_scan_state,
    upsert_file_scan_state,
    upsert_usage_record,
)
from .utils import local_date_for


@dataclass(slots=True)
class ScanStats:
    files_scanned: int = 0
    records_seen: int = 0


@dataclass(slots=True)
class SessionCursor:
    session_id: str | None = None
    session_source: str | None = None
    cwd: str | None = None
    originator: str | None = None
    model_provider: str | None = None
    current_model: str | None = None
    current_turn_id: str | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_source": self.session_source,
            "cwd": self.cwd,
            "originator": self.originator,
            "model_provider": self.model_provider,
            "current_model": self.current_model,
            "current_turn_id": self.current_turn_id,
        }


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
        if _scan_session_file(conn, session_file, tz, stats):
            stats.files_scanned += 1
    conn.commit()
    return stats


def _scan_session_file(
    conn: sqlite3.Connection,
    session_file: Path,
    tz: ZoneInfo,
    stats: ScanStats,
) -> bool:
    try:
        stat = session_file.stat()
    except OSError:
        return False

    state_key = _state_key_for_file("codex", session_file)
    previous = get_file_scan_state(conn, state_key)
    start_offset = 0
    full_reset = previous is None
    if previous is not None:
        previous_size = int(previous["file_size"] or 0)
        previous_mtime_ns = int(previous["mtime_ns"] or 0)
        previous_offset = int(previous["offset"] or 0)
        if previous_size == int(stat.st_size) and previous_mtime_ns == int(stat.st_mtime_ns):
            return False
        if int(stat.st_size) > previous_size and previous_offset <= previous_size:
            full_reset = False
            start_offset = previous_offset
        else:
            full_reset = True
            _delete_codex_file_records(conn, session_file)

    cursor = SessionCursor() if full_reset else _cursor_from_state(previous)
    last_offset = start_offset
    try:
        with session_file.open("r", encoding="utf-8") as handle:
            if start_offset:
                handle.seek(start_offset)
            while True:
                line = handle.readline()
                if not line:
                    break
                last_offset = handle.tell()
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                payload = event.get("payload") or {}
                if event.get("type") == "session_meta":
                    cursor.session_id = _clean_str(payload.get("id")) or cursor.session_id
                    cursor.session_source = _clean_str(payload.get("source")) or cursor.session_source
                    cursor.cwd = _clean_str(payload.get("cwd")) or cursor.cwd
                    cursor.originator = _clean_str(payload.get("originator")) or cursor.originator
                    cursor.model_provider = _clean_str(payload.get("model_provider")) or cursor.model_provider
                    continue

                if event.get("type") == "turn_context":
                    cursor.current_turn_id = _clean_str(payload.get("turn_id")) or cursor.current_turn_id
                    cursor.current_model = _extract_turn_model(payload) or cursor.current_model
                    cursor.cwd = _clean_str(payload.get("cwd")) or cursor.cwd
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
                if not isinstance(timestamp, str) or not timestamp:
                    continue

                stats.records_seen += 1
                upsert_usage_record(
                    conn,
                    UsageRecord(
                        source=f"codex:{cursor.session_source or 'unknown'}",
                        app="codex",
                        external_id=f"{cursor.session_id or session_file.name}:{timestamp}",
                        started_at=timestamp,
                        local_date=local_date_for(timestamp, tz),
                        measurement_method="exact",
                        model=cursor.current_model,
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                        cached_input_tokens=usage.get("cached_input_tokens"),
                        reasoning_tokens=usage.get("reasoning_output_tokens"),
                        total_tokens=usage.get("total_tokens"),
                        category=cursor.session_source,
                        workspace=cursor.cwd,
                        metadata={
                            "session_id": cursor.session_id,
                            "session_file": str(session_file),
                            "originator": cursor.originator,
                            "turn_id": cursor.current_turn_id,
                            "turn_model": cursor.current_model,
                            "model_provider": cursor.model_provider,
                            "model_context_window": info.get("model_context_window"),
                        },
                    ),
                )
            last_offset = handle.tell()
    except OSError:
        return False

    upsert_file_scan_state(
        conn,
        state_key=state_key,
        app="codex",
        file_path=str(session_file),
        offset=last_offset,
        file_size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        last_scanned_at=datetime.now(timezone.utc).isoformat(),
        metadata=cursor.as_metadata(),
    )
    return True


def _clean_str(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _cursor_from_state(previous) -> SessionCursor:
    if previous is None:
        return SessionCursor()

    try:
        metadata = json.loads(previous["metadata_json"] or "{}")
    except Exception:
        metadata = {}

    if not isinstance(metadata, dict):
        metadata = {}

    return SessionCursor(
        session_id=_clean_str(metadata.get("session_id")),
        session_source=_clean_str(metadata.get("session_source")),
        cwd=_clean_str(metadata.get("cwd")),
        originator=_clean_str(metadata.get("originator")),
        model_provider=_clean_str(metadata.get("model_provider")),
        current_model=_clean_str(metadata.get("current_model")),
        current_turn_id=_clean_str(metadata.get("current_turn_id")),
    )


def _state_key_for_file(app: str, session_file: Path) -> str:
    return f"{app}:file:{session_file.resolve()}"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _delete_codex_file_records(conn: sqlite3.Connection, session_file: Path) -> None:
    file_pattern = f'%"session_file": {_escape_like(_json_string_fragment(str(session_file)))}%'
    conn.execute(
        """
        DELETE FROM usage_records
        WHERE app = 'codex'
          AND metadata_json LIKE ? ESCAPE '\\'
        """,
        (file_pattern,),
    )


def _json_string_fragment(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
