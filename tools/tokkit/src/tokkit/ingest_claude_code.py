from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import (
    UsageRecord,
    get_file_scan_state,
    upsert_file_scan_state,
    upsert_usage_record,
)
from .utils import local_date_for


_ENTRYPOINT_RE = re.compile(r"cc_entrypoint=([a-z0-9-]+)", re.IGNORECASE)


@dataclass(slots=True)
class ScanStats:
    files_scanned: int = 0
    records_seen: int = 0


def _iter_session_files(claude_home: Path) -> list[Path]:
    projects_dir = claude_home / "projects"
    if not projects_dir.exists():
        return []
    return sorted(projects_dir.glob("**/*.jsonl"))


def _entrypoint_for_session(claude_home: Path, session_id: str) -> str | None:
    debug_file = claude_home / "debug" / f"{session_id}.txt"
    if not debug_file.exists():
        return None

    try:
        with debug_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                match = _ENTRYPOINT_RE.search(line)
                if match:
                    return match.group(1).strip().lower()
    except OSError:
        return None
    return None


def _source_for_entrypoint(entrypoint: str | None) -> str:
    if not entrypoint:
        return "claude-code:unknown"
    if entrypoint == "claude-vscode":
        return "claude-code:vscode"
    if entrypoint in {"cli", "sdk-cli"}:
        return "claude-code:cli"
    return f"claude-code:{entrypoint}"


def _usage_totals(usage: dict[str, object]) -> tuple[int, int, int, int]:
    direct_input = int(usage.get("input_tokens") or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    output = int(usage.get("output_tokens") or 0)
    return direct_input + cache_creation, cache_read, output, direct_input + cache_creation + cache_read + output


def _usage_rank(record: dict[str, object]) -> tuple[int, int, str]:
    return (
        int(record["total_tokens"]),
        int(record["output_tokens"]),
        str(record["started_at"]),
    )


def scan_claude_code(
    conn: sqlite3.Connection,
    *,
    claude_home: Path,
    tz: ZoneInfo,
) -> ScanStats:
    stats = ScanStats()
    for session_file in _iter_session_files(claude_home):
        if _scan_session_file(conn, session_file, claude_home=claude_home, tz=tz, stats=stats):
            stats.files_scanned += 1
    conn.commit()
    return stats


def _scan_session_file(
    conn: sqlite3.Connection,
    session_file: Path,
    *,
    claude_home: Path,
    tz: ZoneInfo,
    stats: ScanStats,
) -> bool:
    session_id = session_file.stem
    fallback_entrypoint = _entrypoint_for_session(claude_home, session_id)
    try:
        stat = session_file.stat()
    except OSError:
        return False

    state_key = _state_key_for_file("claude-code", session_file)
    previous = get_file_scan_state(conn, state_key)
    start_offset = 0
    full_reset = True
    if previous is not None:
        previous_size = int(previous["file_size"] or 0)
        previous_mtime_ns = int(previous["mtime_ns"] or 0)
        previous_offset = int(previous["offset"] or 0)
        previous_entrypoint = _state_entrypoint(previous)
        if (
            previous_size == int(stat.st_size)
            and previous_mtime_ns == int(stat.st_mtime_ns)
            and previous_entrypoint == fallback_entrypoint
        ):
            return False
        if (
            int(stat.st_size) > previous_size
            and previous_offset <= previous_size
            and previous_entrypoint == fallback_entrypoint
        ):
            full_reset = False
            start_offset = previous_offset

    if full_reset:
        _delete_claude_session_records(conn, session_id)

    best_records: dict[str, dict[str, object]] = {}
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

                if event.get("type") != "assistant":
                    continue

                message = event.get("message")
                if not isinstance(message, dict):
                    continue

                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue

                entrypoint = event.get("entrypoint")
                if not isinstance(entrypoint, str) or not entrypoint.strip():
                    entrypoint = fallback_entrypoint

                started_at = event.get("timestamp")
                message_id = message.get("id") or event.get("uuid")
                if not isinstance(started_at, str) or not started_at or not isinstance(message_id, str):
                    continue

                input_tokens, cached_input_tokens, output_tokens, total_tokens = _usage_totals(usage)
                if total_tokens <= 0:
                    continue

                source = _source_for_entrypoint(entrypoint)

                record = {
                    "external_id": message_id,
                    "record_key": f"{session_id}:{message_id}",
                    "started_at": started_at,
                    "source": source,
                    "model": message.get("model"),
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "workspace": event.get("cwd"),
                    "metadata": {
                        "session_file": str(session_file),
                        "session_id": session_id,
                        "entrypoint": entrypoint,
                        "message_uuid": event.get("uuid"),
                        "message_type": message.get("type"),
                        "claude_version": event.get("version"),
                        "git_branch": event.get("gitBranch"),
                    },
                }

                previous = best_records.get(message_id)
                if previous is None or _usage_rank(record) >= _usage_rank(previous):
                    best_records[message_id] = record
            last_offset = handle.tell()
    except OSError:
        return False

    for record in best_records.values():
        existing = _existing_claude_record(conn, str(record["record_key"]))
        if existing is not None and _usage_rank(record) < existing:
            continue
        if existing is not None:
            conn.execute(
                "DELETE FROM usage_records WHERE app = 'claude-code' AND external_id = ?",
                (str(record["record_key"]),),
            )
        stats.records_seen += 1
        upsert_usage_record(
            conn,
            UsageRecord(
                source=str(record["source"]),
                app="claude-code",
                external_id=str(record["record_key"]),
                started_at=str(record["started_at"]),
                local_date=local_date_for(str(record["started_at"]), tz),
                measurement_method="exact",
                model=str(record["model"]) if record["model"] else None,
                input_tokens=int(record["input_tokens"]),
                output_tokens=int(record["output_tokens"]),
                cached_input_tokens=int(record["cached_input_tokens"]),
                reasoning_tokens=None,
                total_tokens=int(record["total_tokens"]),
                category=str(record["source"]).split(":", 1)[1] if ":" in str(record["source"]) else str(record["source"]),
                workspace=str(record["workspace"]) if record["workspace"] else None,
                metadata=dict(record["metadata"]),
            ),
        )

    upsert_file_scan_state(
        conn,
        state_key=state_key,
        app="claude-code",
        file_path=str(session_file),
        offset=last_offset,
        file_size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        last_scanned_at=datetime.now(timezone.utc).isoformat(),
        metadata={
            "session_id": session_id,
            "entrypoint": fallback_entrypoint,
        },
    )
    return True


def _state_key_for_file(app: str, session_file: Path) -> str:
    return f"{app}:file:{session_file.resolve()}"


def _state_entrypoint(previous) -> str | None:
    if previous is None:
        return None
    try:
        metadata = json.loads(previous["metadata_json"] or "{}")
    except Exception:
        return None
    if not isinstance(metadata, dict):
        return None
    entrypoint = metadata.get("entrypoint")
    if isinstance(entrypoint, str) and entrypoint.strip():
        return entrypoint.strip().lower()
    return None


def _delete_claude_session_records(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        """
        DELETE FROM usage_records
        WHERE app = 'claude-code'
          AND external_id LIKE ?
        """,
        (f"{session_id}:%",),
    )


def _existing_claude_record(
    conn: sqlite3.Connection,
    external_id: str,
) -> tuple[int, int, str] | None:
    row = conn.execute(
        """
        SELECT
            COALESCE(total_tokens, 0) AS total_tokens,
            COALESCE(output_tokens, 0) AS output_tokens,
            started_at
        FROM usage_records
        WHERE app = 'claude-code'
          AND external_id = ?
        ORDER BY total_tokens DESC, output_tokens DESC, started_at DESC
        LIMIT 1
        """,
        (external_id,),
    ).fetchone()
    if row is None:
        return None
    return (
        int(row["total_tokens"]),
        int(row["output_tokens"]),
        str(row["started_at"]),
    )
