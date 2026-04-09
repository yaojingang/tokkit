from __future__ import annotations

import json
import sqlite3
import subprocess
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import UsageRecord, upsert_usage_record
from .utils import local_date_for


@dataclass(slots=True)
class CopilotScanStats:
    files_seen: int = 0
    rows_seen: int = 0
    cli_rows_seen: int = 0
    aggregate_rows_seen: int = 0
    skipped_without_cli_tokens: int = 0
    filtered_out_rows: int = 0
    records_emitted: int = 0
    export_path: Path | None = None
    endpoint: str | None = None
    user_filter: str | None = None
    api_error: str | None = None


def discover_copilot_export_path(explicit_path: Path | None = None) -> Path | None:
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
        candidates.extend(root.glob("*copilot*metrics*.json"))
        candidates.extend(root.glob("*copilot*metrics*.ndjson"))
        candidates.extend(root.glob("*copilot*usage*.json"))
        candidates.extend(root.glob("*copilot*usage*.ndjson"))
        candidates.extend(root.glob("*copilot*.zip"))

    valid: list[Path] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() != ".zip":
            valid.append(candidate)
            continue
        try:
            with zipfile.ZipFile(candidate) as archive:
                members = [name for name in archive.namelist() if _looks_like_copilot_export_member(name)]
                if members:
                    valid.append(candidate)
        except Exception:
            continue

    if not valid:
        return None
    return max(valid, key=lambda path: path.stat().st_mtime)


def scan_copilot(
    conn: sqlite3.Connection,
    *,
    export_path: Path | None,
    org: str | None,
    enterprise: str | None,
    day: str | None,
    user_login: str | None,
    all_users: bool,
    tz: ZoneInfo,
) -> CopilotScanStats:
    stats = CopilotScanStats()
    if not all_users:
        stats.user_filter = user_login or _detect_github_login()

    documents: list[tuple[str, Any]] = []
    if org or enterprise:
        endpoint, links, api_error = _fetch_copilot_report_links(
            org=org,
            enterprise=enterprise,
            day=day,
        )
        stats.endpoint = endpoint
        if api_error:
            stats.api_error = api_error
            return stats
        for index, link in enumerate(links):
            text = _download_signed_report(link)
            if text is None:
                continue
            for payload in _load_payloads_from_text(text):
                documents.append((f"{endpoint}#{index + 1}", payload))
    else:
        resolved_path = discover_copilot_export_path(export_path)
        if resolved_path is None:
            return stats
        stats.export_path = resolved_path
        documents.extend(_load_documents_from_path(resolved_path))

    stats.files_seen = len(documents)
    for document_name, payload in documents:
        for row, parent_context in _iter_usage_rows(payload):
            stats.rows_seen += 1
            if "user_login" not in row and not row.get("user_login"):
                stats.aggregate_rows_seen += 1

            row_user_login = _string_value(row.get("user_login")) or _string_value(parent_context.get("user_login"))
            if stats.user_filter and row_user_login and row_user_login.lower() != stats.user_filter.lower():
                stats.filtered_out_rows += 1
                continue
            if stats.user_filter and not row_user_login:
                stats.filtered_out_rows += 1
                continue

            totals_by_cli = row.get("totals_by_cli")
            if not isinstance(totals_by_cli, dict):
                stats.skipped_without_cli_tokens += 1
                continue
            token_usage = totals_by_cli.get("token_usage")
            if not isinstance(token_usage, dict):
                stats.skipped_without_cli_tokens += 1
                continue

            prompt_tokens = _as_int(token_usage.get("prompt_tokens_sum"))
            output_tokens = _as_int(token_usage.get("output_tokens_sum"))
            total_tokens = prompt_tokens + output_tokens
            if total_tokens <= 0:
                stats.skipped_without_cli_tokens += 1
                continue

            day_value = _string_value(row.get("day")) or _string_value(parent_context.get("day"))
            if not day_value:
                stats.skipped_without_cli_tokens += 1
                continue

            started_at = datetime.fromisoformat(f"{day_value}T00:00:00+00:00").astimezone(tz).isoformat()
            scope = "enterprise" if enterprise or row.get("enterprise_id") or parent_context.get("enterprise_id") else "organization"
            org_name = org or _string_value(parent_context.get("org")) or _string_value(row.get("org"))
            metadata = {
                "user_login": row_user_login,
                "user_id": row.get("user_id"),
                "org": org_name,
                "enterprise": enterprise,
                "scope": scope,
                "report_source": "api" if stats.endpoint else "file",
                "document_name": document_name,
                "export_path": str(stats.export_path) if stats.export_path else None,
                "endpoint": stats.endpoint,
                "used_cli": row.get("used_cli"),
                "used_chat": row.get("used_chat"),
                "used_agent": row.get("used_agent"),
                "totals_by_cli": {
                    "prompt_count": totals_by_cli.get("prompt_count"),
                    "request_count": totals_by_cli.get("request_count"),
                    "session_count": totals_by_cli.get("session_count"),
                    "token_usage": {
                        "avg_tokens_per_request": token_usage.get("avg_tokens_per_request"),
                        "prompt_tokens_sum": prompt_tokens,
                        "output_tokens_sum": output_tokens,
                    },
                },
                "ides": _extract_ide_names(row.get("totals_by_ide")),
                "notes": (
                    "Official GitHub Copilot usage metrics expose CLI token usage here. "
                    "IDE and editor metrics in the same report expose activity and LoC, not IDE token totals."
                ),
            }
            external_parts = [
                scope,
                org_name or enterprise or "unknown-scope",
                row_user_login or "aggregate",
                day_value,
                str(prompt_tokens),
                str(output_tokens),
            ]

            stats.cli_rows_seen += 1
            stats.records_emitted += 1
            upsert_usage_record(
                conn,
                UsageRecord(
                    source="copilot:usage-metrics",
                    app="copilot",
                    external_id=":".join(external_parts),
                    started_at=started_at,
                    local_date=local_date_for(started_at, tz),
                    measurement_method="partial",
                    input_tokens=prompt_tokens or None,
                    output_tokens=output_tokens or None,
                    total_tokens=total_tokens,
                    category="cli",
                    metadata=metadata,
                ),
            )

    conn.commit()
    return stats


def _load_documents_from_path(path: Path) -> list[tuple[str, Any]]:
    path = path.expanduser()
    if path.is_dir():
        documents: list[tuple[str, Any]] = []
        for child in sorted(path.iterdir()):
            if child.is_file() and _looks_like_copilot_export_member(child.name):
                documents.extend(_load_documents_from_path(child))
        return documents

    if path.suffix.lower() == ".zip":
        documents = []
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if not _looks_like_copilot_export_member(member):
                    continue
                with archive.open(member) as handle:
                    text = handle.read().decode("utf-8")
                for payload in _load_payloads_from_text(text):
                    documents.append((member, payload))
        return documents

    text = path.read_text(encoding="utf-8")
    return [(path.name, payload) for payload in _load_payloads_from_text(text)]


def _load_payloads_from_text(text: str) -> list[Any]:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return [json.loads(stripped)]
    except Exception:
        pass

    payloads: list[Any] = []
    for line in stripped.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            payloads.append(json.loads(candidate))
        except Exception:
            continue
    return payloads


def _iter_usage_rows(payload: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if isinstance(payload, list):
        for item in payload:
            rows.extend(_iter_usage_rows(item))
        return rows

    if not isinstance(payload, dict):
        return rows

    if isinstance(payload.get("day_totals"), list):
        parent_context = {
            "org": payload.get("org"),
            "enterprise_id": payload.get("enterprise_id"),
            "report_start_day": payload.get("report_start_day"),
            "report_end_day": payload.get("report_end_day"),
            "etl_id": payload.get("etl_id"),
        }
        for item in payload["day_totals"]:
            if isinstance(item, dict):
                rows.append((item, parent_context))
        return rows

    rows.append((payload, {}))
    return rows


def _looks_like_copilot_export_member(name: str) -> bool:
    normalized = name.lower()
    return "copilot" in normalized and normalized.endswith((".json", ".ndjson", ".jsonl"))


def _fetch_copilot_report_links(
    *,
    org: str | None,
    enterprise: str | None,
    day: str | None,
) -> tuple[str | None, list[str], str | None]:
    if bool(org) == bool(enterprise):
        return None, [], "choose exactly one of --org or --enterprise"

    if org:
        endpoint = (
            f"/orgs/{org}/copilot/metrics/reports/users-1-day?day={day}"
            if day
            else f"/orgs/{org}/copilot/metrics/reports/users-28-day/latest"
        )
    else:
        endpoint = (
            f"/enterprises/{enterprise}/copilot/metrics/reports/users-1-day?day={day}"
            if day
            else f"/enterprises/{enterprise}/copilot/metrics/reports/users-28-day/latest"
        )

    completed = subprocess.run(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2026-03-10",
            endpoint,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stdout + completed.stderr).strip()
        return endpoint, [], message or "gh api failed"
    raw = completed.stdout.strip()
    if not raw:
        return endpoint, [], None
    try:
        payload = json.loads(raw)
    except Exception:
        return endpoint, [], "copilot usage metrics response was not valid JSON"

    links = payload.get("download_links")
    if not isinstance(links, list):
        return endpoint, [], "copilot usage metrics response did not include download_links"
    return endpoint, [str(link) for link in links if isinstance(link, str) and link.strip()], None


def _download_signed_report(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url) as response:
            return response.read().decode("utf-8")
    except Exception:
        return None


def _detect_github_login() -> str | None:
    completed = subprocess.run(
        ["gh", "api", "/user", "--jq", ".login"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    login = completed.stdout.strip()
    return login or None


def _extract_ide_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        ide = _string_value(item.get("ide"))
        if ide:
            names.append(ide)
    return names


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
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
