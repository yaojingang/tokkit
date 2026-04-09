from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import UsageRecord, upsert_usage_record
from .utils import estimate_text_tokens, local_date_for


@dataclass(slots=True)
class ChatGPTExportScanStats:
    conversations_seen: int = 0
    messages_seen: int = 0
    records_emitted: int = 0
    export_path: Path | None = None


def discover_chatgpt_export_path(explicit_path: Path | None = None) -> Path | None:
    if explicit_path is not None:
        candidate = explicit_path.expanduser()
        return candidate if candidate.exists() else None

    search_roots = (
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path.home() / "Documents",
    )
    candidates: list[Path] = []

    for root in search_roots:
        if not root.exists():
            continue
        candidates.extend(root.glob("conversations.json"))
        candidates.extend(root.glob("*chatgpt*.zip"))
        candidates.extend(root.glob("*openai*.zip"))
        candidates.extend(root.glob("*export*.zip"))

    valid: list[Path] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.name == "conversations.json":
            valid.append(candidate)
            continue
        if candidate.suffix.lower() != ".zip":
            continue
        try:
            with zipfile.ZipFile(candidate) as archive:
                if any(name.endswith("conversations.json") for name in archive.namelist()):
                    valid.append(candidate)
        except Exception:
            continue

    if not valid:
        return None
    return max(valid, key=lambda path: path.stat().st_mtime)


def scan_chatgpt_export(
    conn: sqlite3.Connection,
    *,
    export_path: Path | None,
    tz: ZoneInfo,
) -> ChatGPTExportScanStats:
    stats = ChatGPTExportScanStats()
    resolved_path = discover_chatgpt_export_path(export_path)
    if resolved_path is None:
        return stats

    payload = _load_export_payload(resolved_path)
    if not isinstance(payload, list):
        return stats

    stats.export_path = resolved_path
    for conversation in payload:
        if not isinstance(conversation, dict):
            continue
        stats.conversations_seen += 1
        _scan_conversation(conn, conversation, resolved_path, tz, stats)

    conn.commit()
    return stats


def _load_export_payload(path: Path) -> Any:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.endswith("conversations.json")]
            if not members:
                return None
            with archive.open(members[0]) as handle:
                return json.loads(handle.read().decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_conversation(
    conn: sqlite3.Connection,
    conversation: dict[str, Any],
    export_path: Path,
    tz: ZoneInfo,
    stats: ChatGPTExportScanStats,
) -> None:
    conversation_id = _string_value(conversation.get("id")) or "unknown-conversation"
    title = _string_value(conversation.get("title"))
    default_model = (
        _string_value(conversation.get("default_model_slug"))
        or _string_value(conversation.get("model_slug"))
        or _string_value(conversation.get("gizmo_id"))
    )
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        return

    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue

        role = _extract_role(message)
        text = _extract_message_text(message)
        if not text:
            continue

        stats.messages_seen += 1
        total_tokens = estimate_text_tokens(text)
        started_at = _resolve_started_at(message, node, conversation, tz)
        model = _extract_model_slug(message) or default_model
        message_id = _string_value(message.get("id")) or _string_value(node_id) or f"message-{stats.messages_seen}"
        metadata = {
            "conversation_id": conversation_id,
            "conversation_title": title,
            "message_id": message_id,
            "node_id": _string_value(node_id),
            "role": role,
            "export_path": str(export_path),
            "estimation_method": "chatgpt_export_text_parts",
            "notes": "Estimated from official ChatGPT export text, not provider billable usage.",
        }

        input_tokens = total_tokens if role != "assistant" else None
        output_tokens = total_tokens if role == "assistant" else None
        stats.records_emitted += 1
        upsert_usage_record(
            conn,
            UsageRecord(
                source="chatgpt:export",
                app="chatgpt",
                external_id=f"{conversation_id}:{message_id}",
                started_at=started_at,
                local_date=local_date_for(started_at, tz),
                measurement_method="estimated",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                category=role,
                metadata=metadata,
            ),
        )


def _extract_role(message: dict[str, Any]) -> str:
    author = message.get("author")
    if isinstance(author, dict):
        role = _string_value(author.get("role"))
        if role:
            return role
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        role = _string_value(metadata.get("role")) or _string_value(metadata.get("author_role"))
        if role:
            return role
    return "unknown"


def _extract_model_slug(message: dict[str, Any]) -> str | None:
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return None
    for key in ("model_slug", "default_model_slug", "requested_model_slug"):
        value = _string_value(metadata.get(key))
        if value:
            return value
    return None


def _extract_message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, dict):
        return ""

    fragments: list[str] = []
    parts = content.get("parts")
    if isinstance(parts, list):
        for part in parts:
            _collect_text_fragments(part, fragments)
    for key in ("text", "result", "content", "value"):
        if key in content:
            _collect_text_fragments(content.get(key), fragments)
    return "\n".join(fragment for fragment in fragments if fragment.strip()).strip()


def _collect_text_fragments(value: Any, fragments: list[str]) -> None:
    if isinstance(value, str):
        if value.strip():
            fragments.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text_fragments(item, fragments)
        return
    if isinstance(value, dict):
        for key in ("text", "content", "value", "result"):
            if key in value:
                _collect_text_fragments(value.get(key), fragments)


def _resolve_started_at(
    message: dict[str, Any],
    node: dict[str, Any],
    conversation: dict[str, Any],
    tz: ZoneInfo,
) -> str:
    for value in (
        message.get("create_time"),
        node.get("create_time"),
        conversation.get("update_time"),
        conversation.get("create_time"),
    ):
        timestamp = _normalize_time_value(value, tz)
        if timestamp:
            return timestamp
    return datetime.now(tz).isoformat()


def _normalize_time_value(value: Any, tz: ZoneInfo) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(tz).isoformat()
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            if raw.endswith("Z"):
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(tz).isoformat()
            return datetime.fromisoformat(raw).astimezone(tz).isoformat()
        except Exception:
            return None
    return None


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
