from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import UsageRecord, get_warp_state, upsert_usage_record, upsert_warp_state
from .utils import local_date_for, normalize_timestamp


@dataclass(slots=True)
class WarpScanStats:
    conversations_seen: int = 0
    records_emitted: int = 0


def scan_warp(
    conn: sqlite3.Connection,
    *,
    warp_db: Path,
    tz: ZoneInfo,
    baseline_only: bool = False,
) -> WarpScanStats:
    stats = WarpScanStats()
    if not warp_db.exists():
        return stats

    warp_conn = sqlite3.connect(warp_db)
    warp_conn.row_factory = sqlite3.Row

    latest_query_meta = _load_latest_query_metadata(warp_conn)
    rows = warp_conn.execute(
        """
        SELECT
            conversation_id,
            last_modified_at,
            json_extract(conversation_data, '$.server_conversation_token') AS server_conversation_token,
            json_extract(conversation_data, '$.conversation_usage_metadata.credits_spent') AS credits_spent,
            json_extract(conversation_data, '$.conversation_usage_metadata.token_usage') AS token_usage_json
        FROM agent_conversations
        WHERE json_array_length(json_extract(conversation_data, '$.conversation_usage_metadata.token_usage')) > 0
        """
    ).fetchall()

    for row in rows:
        stats.conversations_seen += 1
        token_usage = json.loads(row["token_usage_json"])
        total_conversation_tokens = sum(
            int(entry.get("warp_tokens", 0)) + int(entry.get("byok_tokens", 0))
            for entry in token_usage
        )
        credits_spent = float(row["credits_spent"] or 0.0)
        query_meta = latest_query_meta.get(row["conversation_id"], {})

        for entry in token_usage:
            model_id = entry.get("model_id") or "unknown"
            category_map = _merged_category_map(entry)
            for category, current_tokens in category_map.items():
                if current_tokens <= 0:
                    continue
                current_credits = 0.0
                if credits_spent > 0 and total_conversation_tokens > 0:
                    current_credits = credits_spent * (current_tokens / total_conversation_tokens)

                external_key = f"{row['conversation_id']}|{model_id}|{category}"
                previous = get_warp_state(conn, external_key)
                if previous:
                    delta_tokens = current_tokens - int(previous["total_tokens"])
                    delta_credits = current_credits - float(previous["credits"])
                else:
                    delta_tokens = current_tokens
                    delta_credits = current_credits

                if baseline_only and previous is None:
                    delta_tokens = 0
                    delta_credits = 0.0

                if delta_tokens > 0 or delta_credits > 0:
                    stats.records_emitted += 1
                    timestamp = normalize_timestamp(row["last_modified_at"], naive_tz=tz)
                    upsert_usage_record(
                        conn,
                        UsageRecord(
                            source="warp",
                            app="warp",
                            external_id=(
                                f"{external_key}|{row['last_modified_at']}|"
                                f"{current_tokens}|{round(current_credits, 8)}"
                            ),
                            started_at=timestamp,
                            local_date=local_date_for(timestamp, tz),
                            measurement_method="partial",
                            model=model_id,
                            total_tokens=max(delta_tokens, 0),
                            credits=round(delta_credits, 8) if delta_credits > 0 else None,
                            category=category,
                            workspace=query_meta.get("working_directory"),
                            metadata={
                                "conversation_id": row["conversation_id"],
                                "server_conversation_token": row["server_conversation_token"],
                                "scan_mode": "delta_from_conversation_aggregate",
                                "bootstrap_record": previous is None,
                                "latest_query_ts": query_meta.get("start_ts"),
                                "query_model_id": query_meta.get("model_id"),
                                "output_status": query_meta.get("output_status"),
                            },
                        ),
                    )

                upsert_warp_state(
                    conn,
                    external_key=external_key,
                    conversation_id=row["conversation_id"],
                    model=model_id,
                    category=category,
                    total_tokens=current_tokens,
                    credits=current_credits,
                    last_modified_at=normalize_timestamp(row["last_modified_at"], naive_tz=tz),
                    metadata={
                        "server_conversation_token": row["server_conversation_token"],
                        "latest_query_ts": query_meta.get("start_ts"),
                        "working_directory": query_meta.get("working_directory"),
                    },
                )

    warp_conn.close()
    conn.commit()
    return stats


def _merged_category_map(entry: dict[str, object]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for bucket_name in ("warp_token_usage_by_category", "byok_token_usage_by_category"):
        bucket = entry.get(bucket_name) or {}
        if not isinstance(bucket, dict):
            continue
        for category, value in bucket.items():
            merged[category] = merged.get(category, 0) + int(value)
    if merged:
        return merged
    total = int(entry.get("warp_tokens", 0)) + int(entry.get("byok_tokens", 0))
    return {"unknown": total}


def _load_latest_query_metadata(warp_conn: sqlite3.Connection) -> dict[str, dict[str, str | None]]:
    rows = warp_conn.execute(
        """
        SELECT conversation_id, start_ts, working_directory, output_status, model_id
        FROM ai_queries
        ORDER BY start_ts DESC
        """
    ).fetchall()
    latest: dict[str, dict[str, str | None]] = {}
    for row in rows:
        if row["conversation_id"] in latest:
            continue
        latest[row["conversation_id"]] = {
            "start_ts": row["start_ts"],
            "working_directory": row["working_directory"],
            "output_status": row["output_status"],
            "model_id": row["model_id"],
        }
    return latest
