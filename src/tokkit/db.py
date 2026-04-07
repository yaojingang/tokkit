from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import DEFAULT_DB_PATH, json_dumps


@dataclass(slots=True)
class UsageRecord:
    source: str
    app: str
    external_id: str
    started_at: str
    local_date: str
    measurement_method: str = "exact"
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    credits: float | None = None
    category: str | None = None
    workspace: str | None = None
    metadata: dict[str, Any] | None = None


def connect_db(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            app TEXT NOT NULL,
            external_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            local_date TEXT NOT NULL,
            measurement_method TEXT NOT NULL DEFAULT 'exact',
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cached_input_tokens INTEGER,
            reasoning_tokens INTEGER,
            total_tokens INTEGER,
            credits REAL,
            category TEXT,
            workspace TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, external_id)
        );

        CREATE INDEX IF NOT EXISTS idx_usage_records_local_date
            ON usage_records(local_date);

        CREATE INDEX IF NOT EXISTS idx_usage_records_app_source
            ON usage_records(app, source);

        CREATE TABLE IF NOT EXISTS warp_state (
            external_key TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            model TEXT,
            category TEXT,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            credits REAL NOT NULL DEFAULT 0,
            last_modified_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS app_scan_state (
            state_key TEXT PRIMARY KEY,
            app TEXT NOT NULL,
            source TEXT NOT NULL,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            last_seen_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    _ensure_usage_records_columns(conn)
    _backfill_measurement_methods(conn)
    conn.commit()


def _ensure_usage_records_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(usage_records)").fetchall()
    }
    if "measurement_method" not in columns:
        conn.execute(
            "ALTER TABLE usage_records ADD COLUMN measurement_method TEXT NOT NULL DEFAULT 'exact'"
        )


def _backfill_measurement_methods(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE usage_records
        SET measurement_method = CASE
            WHEN app = 'warp' THEN 'partial'
            WHEN app = 'codebuddy' THEN 'estimated'
            WHEN app = 'cursor' THEN 'estimated'
            ELSE 'exact'
        END
        WHERE measurement_method IS NULL
           OR measurement_method = ''
           OR measurement_method = 'exact'
        """
    )


def upsert_usage_record(conn: sqlite3.Connection, record: UsageRecord) -> None:
    conn.execute(
        """
        INSERT INTO usage_records (
            source,
            app,
            external_id,
            started_at,
            local_date,
            measurement_method,
            model,
            input_tokens,
            output_tokens,
            cached_input_tokens,
            reasoning_tokens,
            total_tokens,
            credits,
            category,
            workspace,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            app = excluded.app,
            started_at = excluded.started_at,
            local_date = excluded.local_date,
            measurement_method = excluded.measurement_method,
            model = excluded.model,
            input_tokens = excluded.input_tokens,
            output_tokens = excluded.output_tokens,
            cached_input_tokens = excluded.cached_input_tokens,
            reasoning_tokens = excluded.reasoning_tokens,
            total_tokens = excluded.total_tokens,
            credits = excluded.credits,
            category = excluded.category,
            workspace = excluded.workspace,
            metadata_json = excluded.metadata_json
        """,
        (
            record.source,
            record.app,
            record.external_id,
            record.started_at,
            record.local_date,
            record.measurement_method,
            record.model,
            record.input_tokens,
            record.output_tokens,
            record.cached_input_tokens,
            record.reasoning_tokens,
            record.total_tokens,
            record.credits,
            record.category,
            record.workspace,
            json_dumps(record.metadata or {}),
        ),
    )


def get_app_scan_state(conn: sqlite3.Connection, state_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM app_scan_state WHERE state_key = ?",
        (state_key,),
    ).fetchone()


def upsert_app_scan_state(
    conn: sqlite3.Connection,
    *,
    state_key: str,
    app: str,
    source: str,
    total_tokens: int,
    last_seen_at: str,
    metadata: dict[str, Any] | None,
) -> None:
    conn.execute(
        """
        INSERT INTO app_scan_state (
            state_key,
            app,
            source,
            total_tokens,
            last_seen_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            app = excluded.app,
            source = excluded.source,
            total_tokens = excluded.total_tokens,
            last_seen_at = excluded.last_seen_at,
            metadata_json = excluded.metadata_json
        """,
        (
            state_key,
            app,
            source,
            total_tokens,
            last_seen_at,
            json_dumps(metadata or {}),
        ),
    )


def get_warp_state(conn: sqlite3.Connection, external_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM warp_state WHERE external_key = ?",
        (external_key,),
    ).fetchone()


def upsert_warp_state(
    conn: sqlite3.Connection,
    *,
    external_key: str,
    conversation_id: str,
    model: str,
    category: str,
    total_tokens: int,
    credits: float,
    last_modified_at: str,
    metadata: dict[str, Any] | None,
) -> None:
    conn.execute(
        """
        INSERT INTO warp_state (
            external_key,
            conversation_id,
            model,
            category,
            total_tokens,
            credits,
            last_modified_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(external_key) DO UPDATE SET
            conversation_id = excluded.conversation_id,
            model = excluded.model,
            category = excluded.category,
            total_tokens = excluded.total_tokens,
            credits = excluded.credits,
            last_modified_at = excluded.last_modified_at,
            metadata_json = excluded.metadata_json
        """,
        (
            external_key,
            conversation_id,
            model,
            category,
            total_tokens,
            credits,
            last_modified_at,
            json_dumps(metadata or {}),
        ),
    )
