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
from .utils import estimate_text_tokens, local_date_for


_CHECKPOINT_NAME_RE = re.compile(r".*-(\d+)-([0-9a-f-]{36})\.json$")


@dataclass(slots=True)
class AugmentHistoryScanStats:
    selection_entries_seen: int = 0
    selection_requests_with_timestamps: int = 0
    checkpoint_files_seen: int = 0
    request_records_emitted: int = 0


def scan_augment_history(
    conn: sqlite3.Connection,
    *,
    workspace_storage_root: Path,
    tz: ZoneInfo,
) -> AugmentHistoryScanStats:
    stats = AugmentHistoryScanStats()
    conn.execute(
        """
        DELETE FROM usage_records
        WHERE app = 'augment'
          AND source = 'augment:history'
        """
    )
    if not workspace_storage_root.exists():
        conn.commit()
        return stats

    selection_by_request = _load_selection_metadata(workspace_storage_root, stats)
    request_timestamp_index = _load_request_timestamp_index(workspace_storage_root, tz)
    checkpoint_totals = _load_checkpoint_totals(conn, workspace_storage_root, stats, tz)

    request_ids = set(checkpoint_totals.keys()) | set(selection_by_request.keys())
    for request_id in sorted(request_ids):
        checkpoint = checkpoint_totals.get(request_id, {})
        selection = selection_by_request.get(request_id, {})
        started_at = str(checkpoint.get("started_at") or request_timestamp_index.get(request_id) or "").strip()
        if not started_at:
            continue

        input_tokens = _estimate_selection_tokens(selection)
        output_tokens = int(checkpoint.get("output_tokens") or 0)
        total_tokens = input_tokens + output_tokens
        if total_tokens <= 0:
            continue

        if input_tokens > 0:
            stats.selection_requests_with_timestamps += 1

        metadata = {
            "estimation_method": "augment_request_selection_plus_checkpoint_diff",
            "selection_context_lengths": {
                "selected_code_chars": len(str(selection.get("selectedCode") or "")),
                "prefix_chars": len(str(selection.get("prefix") or "")),
                "suffix_chars": len(str(selection.get("suffix") or "")),
            },
            "selection_path": selection.get("path"),
            "selection_language": selection.get("language"),
            "checkpoint_count": int(checkpoint.get("checkpoint_count") or 0),
            "output_token_estimate": output_tokens,
            "workspace_storage_root": str(workspace_storage_root),
            "notes": (
                "Estimated from persisted Augment request selection context and checkpoint diffs. "
                "This is historical local estimation, not an official billable token ledger."
            ),
        }
        sample_documents = checkpoint.get("sample_documents")
        if sample_documents:
            metadata["sample_documents"] = sample_documents

        workspace = checkpoint.get("workspace")
        upsert_usage_record(
            conn,
            UsageRecord(
                source="augment:history",
                app="augment",
                external_id=f"history:{request_id}",
                started_at=started_at,
                local_date=local_date_for(started_at, tz),
                measurement_method="estimated",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=0,
                reasoning_tokens=None,
                total_tokens=total_tokens,
                category="local-history",
                workspace=str(workspace) if workspace else None,
                metadata=metadata,
            ),
        )
        stats.request_records_emitted += 1

    conn.commit()
    return stats


def _load_selection_metadata(
    workspace_storage_root: Path,
    stats: AugmentHistoryScanStats,
) -> dict[str, dict[str, object]]:
    selections: dict[str, dict[str, object]] = {}
    pattern = "*/Augment.vscode-augment/augment-global-state/requestIdSelectionMetadata.json"
    for path in sorted(workspace_storage_root.glob(pattern)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not (
                isinstance(item, list)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], dict)
            ):
                continue
            value = item[1].get("value")
            if not isinstance(value, dict):
                continue
            request_id = item[0].strip()
            if not request_id:
                continue
            stats.selection_entries_seen += 1
            selections[request_id] = {
                "selectedCode": str(value.get("selectedCode") or ""),
                "prefix": str(value.get("prefix") or ""),
                "suffix": str(value.get("suffix") or ""),
                "path": str(value.get("path") or ""),
                "language": str(value.get("language") or ""),
            }
    return selections


def _load_request_timestamp_index(
    workspace_storage_root: Path,
    tz: ZoneInfo,
) -> dict[str, str]:
    timestamps: dict[str, str] = {}
    pattern = "*/Augment.vscode-augment/augment-user-assets/agent-edits/shards/*.json"
    for path in sorted(workspace_storage_root.glob(pattern)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        checkpoints = payload.get("checkpoints")
        if not isinstance(checkpoints, dict):
            continue
        for entries in checkpoints.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                request_id = entry.get("sourceToolCallRequestId")
                timestamp_ms = entry.get("timestamp")
                if not isinstance(request_id, str) or not request_id.strip():
                    continue
                if not isinstance(timestamp_ms, (int, float)) or float(timestamp_ms) <= 0:
                    continue
                started_at = datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=tz).isoformat()
                previous = timestamps.get(request_id)
                if previous is None or started_at < previous:
                    timestamps[request_id] = started_at
    return timestamps


def _load_checkpoint_totals(
    conn: sqlite3.Connection,
    workspace_storage_root: Path,
    stats: AugmentHistoryScanStats,
    tz: ZoneInfo,
) -> dict[str, dict[str, object]]:
    pattern = "*/Augment.vscode-augment/augment-user-assets/checkpoint-documents/*/*.json"
    for path in sorted(workspace_storage_root.glob(pattern)):
        _sync_checkpoint_state(conn, path, stats, tz)

    return _checkpoint_totals_from_state(conn, workspace_storage_root)


def _sync_checkpoint_state(
    conn: sqlite3.Connection,
    path: Path,
    stats: AugmentHistoryScanStats,
    tz: ZoneInfo,
) -> None:
    match = _CHECKPOINT_NAME_RE.match(path.name)
    if match is None:
        return
    try:
        stat = path.stat()
    except OSError:
        return

    state_key = _checkpoint_state_key(path)
    previous = get_file_scan_state(conn, state_key)
    if previous is not None:
        previous_size = int(previous["file_size"] or 0)
        previous_mtime_ns = int(previous["mtime_ns"] or 0)
        if previous_size == int(stat.st_size) and previous_mtime_ns == int(stat.st_mtime_ns):
            return

    stats.checkpoint_files_seen += 1
    timestamp_ms = int(match.group(1))
    request_id = match.group(2)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    output_tokens = _estimate_checkpoint_output_tokens(payload)
    if output_tokens <= 0:
        output_tokens = 0

    doc_path = payload.get("path")
    workspace = _workspace_from_doc_path(doc_path)
    sample_document = _path_from_doc_path(doc_path)
    started_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=tz).isoformat()

    upsert_file_scan_state(
        conn,
        state_key=state_key,
        app="augment-history-checkpoint",
        file_path=str(path),
        offset=0,
        file_size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        last_scanned_at=datetime.now(timezone.utc).isoformat(),
        metadata={
            "request_id": request_id,
            "started_at": started_at,
            "output_tokens": output_tokens,
            "workspace": workspace,
            "sample_document": sample_document,
        },
    )


def _checkpoint_totals_from_state(
    conn: sqlite3.Connection,
    workspace_storage_root: Path,
) -> dict[str, dict[str, object]]:
    aggregated: dict[str, dict[str, object]] = {}
    root_prefix = str(workspace_storage_root)
    rows = conn.execute(
        """
        SELECT file_path, metadata_json
        FROM file_scan_state
        WHERE app = 'augment-history-checkpoint'
        """
    ).fetchall()
    for row in rows:
        file_path = str(row["file_path"] or "")
        if root_prefix and not file_path.startswith(root_prefix):
            continue
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            continue
        if not isinstance(metadata, dict):
            continue
        request_id = str(metadata.get("request_id") or "").strip()
        started_at = str(metadata.get("started_at") or "").strip()
        if not request_id or not started_at:
            continue
        output_tokens = int(metadata.get("output_tokens") or 0)
        workspace = metadata.get("workspace")
        sample_document = metadata.get("sample_document")

        bucket = aggregated.setdefault(
            request_id,
            {
                "started_at": started_at,
                "output_tokens": 0,
                "checkpoint_count": 0,
                "workspace": workspace,
                "sample_documents": [],
            },
        )
        if started_at < str(bucket["started_at"]):
            bucket["started_at"] = started_at
        bucket["output_tokens"] = int(bucket["output_tokens"]) + output_tokens
        bucket["checkpoint_count"] = int(bucket["checkpoint_count"]) + 1
        if workspace and not bucket.get("workspace"):
            bucket["workspace"] = workspace
        if sample_document:
            sample_documents = bucket["sample_documents"]
            if isinstance(sample_documents, list) and sample_document not in sample_documents and len(sample_documents) < 3:
                sample_documents.append(sample_document)
    return aggregated


def _checkpoint_state_key(path: Path) -> str:
    return f"augment-history-checkpoint:file:{path.resolve()}"


def _estimate_selection_tokens(selection: dict[str, object]) -> int:
    return (
        estimate_text_tokens(str(selection.get("selectedCode") or ""))
        + estimate_text_tokens(str(selection.get("prefix") or ""))
        + estimate_text_tokens(str(selection.get("suffix") or ""))
    )


def _estimate_checkpoint_output_tokens(payload: object) -> int:
    if not isinstance(payload, dict):
        return 0
    original = payload.get("originalCode")
    modified = payload.get("modifiedCode")
    original_text = original if isinstance(original, str) else ""
    modified_text = modified if isinstance(modified, str) else ""
    if not modified_text:
        return 0
    if not original_text:
        return estimate_text_tokens(modified_text)
    if original_text == modified_text:
        return 0
    return estimate_text_tokens(_changed_modified_segment(original_text, modified_text))


def _changed_modified_segment(original: str, modified: str) -> str:
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    if not original_lines or not modified_lines:
        return modified

    prefix = 0
    max_prefix = min(len(original_lines), len(modified_lines))
    while prefix < max_prefix and original_lines[prefix] == modified_lines[prefix]:
        prefix += 1

    suffix = 0
    max_suffix = min(len(original_lines) - prefix, len(modified_lines) - prefix)
    while suffix < max_suffix and original_lines[-(suffix + 1)] == modified_lines[-(suffix + 1)]:
        suffix += 1

    end_index = len(modified_lines) - suffix if suffix else len(modified_lines)
    changed_lines = modified_lines[prefix:end_index]
    if changed_lines:
        return "".join(changed_lines)
    return modified


def _workspace_from_doc_path(doc_path: object) -> str | None:
    if not isinstance(doc_path, dict):
        return None
    root_path = doc_path.get("rootPath")
    rel_path = doc_path.get("relPath")
    if not isinstance(root_path, str) or not root_path.strip():
        return None
    if not isinstance(rel_path, str) or not rel_path.strip():
        return root_path
    try:
        full_path = Path(root_path) / rel_path
        return str(full_path.parent)
    except Exception:
        return root_path


def _path_from_doc_path(doc_path: object) -> str | None:
    if not isinstance(doc_path, dict):
        return None
    root_path = doc_path.get("rootPath")
    rel_path = doc_path.get("relPath")
    if not isinstance(root_path, str) or not root_path.strip():
        return None
    if not isinstance(rel_path, str) or not rel_path.strip():
        return root_path
    return str(Path(root_path) / rel_path)
