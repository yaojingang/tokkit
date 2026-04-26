from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import sqlite3
import subprocess
import sys
import tomllib
from datetime import timedelta
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .augment_capture import apply_augment_capture_patch, inspect_augment_patch, remove_augment_capture_patch
from .budget import resolve_budget_config, write_budget_template
from .clients import CLIENT_DEFINITIONS, detect_installed_clients, is_codex_desktop_originator, logical_client_for_usage_row
from .db import connect_db
from .ingest_augment import scan_augment
from .ingest_augment_history import scan_augment_history
from .ingest_chatgpt_export import discover_chatgpt_export_path, scan_chatgpt_export
from .ingest_claude_code import scan_claude_code
from .ingest_copilot import discover_copilot_export_path, scan_copilot
from .ingest_codebuddy import scan_codebuddy
from .ingest_codex import scan_codex
from .ingest_cursor import scan_cursor
from .ingest_trae import scan_trae
from .ingest_warp import scan_warp
from .pricing import estimate_cost_usd, iter_price_book, normalize_model_display, resolve_price_book
from .proxy import ProxyConfig, serve_proxy
from .utils import DEFAULT_DB_PATH, default_augment_capture_path, default_db_path, default_log_dir, default_report_dir, format_float, format_int, get_timezone, parse_timestamp, resolve_app_home, today_string


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track daily token usage across local AI coding tools.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path.")
    parser.add_argument(
        "--timezone",
        default=None,
        help="IANA timezone name. Defaults to the local system timezone.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    codex_cmd = subparsers.add_parser("scan-codex", help="Ingest Codex Desktop and CLI usage.")
    codex_cmd.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")

    claude_cmd = subparsers.add_parser("scan-claude-code", help="Ingest local Claude Code usage.")
    claude_cmd.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")

    augment_cmd = subparsers.add_parser(
        "scan-augment",
        help="Ingest locally captured Augment usage plus estimated historical local usage.",
    )
    augment_cmd.add_argument("--capture-file", type=Path, default=default_augment_capture_path())
    augment_cmd.add_argument(
        "--workspace-storage-root",
        type=Path,
        default=Path.home() / "Library/Application Support/Code/User/workspaceStorage",
    )

    chatgpt_cmd = subparsers.add_parser(
        "scan-chatgpt-export",
        help="Estimate ChatGPT usage from an exported conversations.json or zip file.",
    )
    chatgpt_cmd.add_argument(
        "--export-file",
        type=Path,
        default=None,
        help="Path to conversations.json or a ChatGPT export zip. Defaults to auto-discovery in common folders.",
    )

    copilot_cmd = subparsers.add_parser(
        "scan-copilot",
        help="Ingest GitHub Copilot official usage metrics exports or API-backed reports.",
    )
    copilot_cmd.add_argument(
        "--export-file",
        type=Path,
        default=None,
        help="Path to a Copilot usage metrics JSON/NDJSON/zip export. Defaults to auto-discovery in common folders.",
    )
    copilot_scope_group = copilot_cmd.add_mutually_exclusive_group()
    copilot_scope_group.add_argument("--org", default=None, help="Organization slug for the Copilot usage metrics API.")
    copilot_scope_group.add_argument("--enterprise", default=None, help="Enterprise slug for the Copilot usage metrics API.")
    copilot_cmd.add_argument("--day", default=None, help="Specific report day in YYYY-MM-DD for API-backed scans.")
    copilot_cmd.add_argument("--user-login", default=None, help="GitHub login to filter user-level report rows.")
    copilot_cmd.add_argument("--all-users", action="store_true", help="Ingest all user rows instead of filtering to one login.")

    patch_augment_cmd = subparsers.add_parser(
        "patch-augment",
        help="Install, inspect, or remove the local Augment runtime capture hook.",
    )
    patch_augment_cmd.add_argument("--extension-dir", type=Path, default=None)
    patch_augment_cmd.add_argument("--capture-file", type=Path, default=default_augment_capture_path())
    patch_augment_cmd.add_argument("--json", action="store_true")
    action_group = patch_augment_cmd.add_mutually_exclusive_group()
    action_group.add_argument("--status", action="store_true")
    action_group.add_argument("--remove", action="store_true")

    codebuddy_cmd = subparsers.add_parser("scan-codebuddy", help="Estimate CodeBuddy usage from local task history.")
    codebuddy_cmd.add_argument(
        "--codebuddy-tasks-root",
        type=Path,
        default=Path.home() / "Library/Application Support/CodeBuddy/User/globalStorage/tencent.planning-genie/tasks",
    )

    cursor_cmd = subparsers.add_parser("scan-cursor", help="Estimate Cursor usage from local sentry telemetry.")
    cursor_cmd.add_argument(
        "--cursor-sentry-scope",
        type=Path,
        default=Path.home() / "Library/Application Support/Cursor/sentry/scope_v3.json",
    )

    trae_cmd = subparsers.add_parser("scan-trae", help="Ingest Trae task-history usage when local token fields are present.")
    trae_cmd.add_argument(
        "--trae-tasks-root",
        type=Path,
        default=Path.home() / "Library/Application Support/Trae/User/globalStorage/huohuaai.huohuaai/tasks",
    )

    warp_cmd = subparsers.add_parser("scan-warp", help="Ingest Warp AI usage.")
    warp_cmd.add_argument(
        "--warp-db",
        type=Path,
        default=(
            Path.home()
            / "Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite"
        ),
    )
    warp_cmd.add_argument(
        "--baseline-only",
        action="store_true",
        help="Seed Warp state without emitting first-seen historical usage rows.",
    )

    all_cmd = subparsers.add_parser("scan-all", help="Run all supported local ingesters together.")
    all_cmd.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    all_cmd.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    all_cmd.add_argument("--augment-capture-file", type=Path, default=default_augment_capture_path())
    all_cmd.add_argument(
        "--augment-workspace-storage-root",
        type=Path,
        default=Path.home() / "Library/Application Support/Code/User/workspaceStorage",
    )
    all_cmd.add_argument("--chatgpt-export-file", type=Path, default=None)
    all_cmd.add_argument("--copilot-export-file", type=Path, default=None)
    all_cmd.add_argument(
        "--codebuddy-tasks-root",
        type=Path,
        default=Path.home() / "Library/Application Support/CodeBuddy/User/globalStorage/tencent.planning-genie/tasks",
    )
    all_cmd.add_argument(
        "--cursor-sentry-scope",
        type=Path,
        default=Path.home() / "Library/Application Support/Cursor/sentry/scope_v3.json",
    )
    all_cmd.add_argument(
        "--trae-tasks-root",
        type=Path,
        default=Path.home() / "Library/Application Support/Trae/User/globalStorage/huohuaai.huohuaai/tasks",
    )
    all_cmd.add_argument(
        "--warp-db",
        type=Path,
        default=(
            Path.home()
            / "Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite"
        ),
    )
    all_cmd.add_argument("--baseline-only-warp", action="store_true")

    report_cmd = subparsers.add_parser("report-daily", help="Show a daily usage report.")
    report_cmd.add_argument(
        "--date",
        default="today",
        help="Date in YYYY-MM-DD, or 'today'/'yesterday'.",
    )
    report_cmd.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the rendered report.",
    )
    report_cmd.add_argument(
        "--json",
        action="store_true",
        help="Render the report as JSON.",
    )

    range_cmd = subparsers.add_parser("report-range", help="Show a multi-day summary.")
    range_cmd.add_argument("--last", type=int, default=7, help="Number of days to include.")
    range_cmd.add_argument("--json", action="store_true")

    clients_cmd = subparsers.add_parser("report-clients", help="Show cross-client coverage and aggregate totals.")
    window_group = clients_cmd.add_mutually_exclusive_group()
    window_group.add_argument(
        "--date",
        default=None,
        help="Date in YYYY-MM-DD, or 'today'/'yesterday'. Defaults to today.",
    )
    window_group.add_argument(
        "--last",
        type=int,
        default=None,
        help="Number of days to include instead of a single date.",
    )
    clients_cmd.add_argument("--json", action="store_true")

    pricing_cmd = subparsers.add_parser("pricing", help="Show the local pricing profiles used for cost estimation.")
    pricing_cmd.add_argument("--json", action="store_true")

    budget_cmd = subparsers.add_parser("budget", help="Show or initialize local cost and credits budgets.")
    budget_cmd.add_argument("--json", action="store_true")
    budget_subparsers = budget_cmd.add_subparsers(dest="budget_command", required=False)
    budget_init_cmd = budget_subparsers.add_parser("init", help="Write a starter budget.json file.")
    budget_init_cmd.add_argument("--force", action="store_true")

    doctor_cmd = subparsers.add_parser("doctor", help="Inspect local setup, coverage, and likely configuration issues.")
    doctor_cmd.add_argument("--json", action="store_true")

    setup_cmd = subparsers.add_parser("setup", help="Inspect or apply common local setup steps.")
    setup_cmd.add_argument("--json", action="store_true")
    setup_cmd.add_argument("--install-launchd", action="store_true")
    setup_cmd.add_argument("--scan-mode", choices=("all", "codex"), default="codex")
    setup_cmd.add_argument("--enable-kaku-proxy", action="store_true")
    setup_cmd.add_argument("--kaku-upstream-base-url", default=None)
    setup_cmd.add_argument("--migrate-home", action="store_true")

    proxy_cmd = subparsers.add_parser("serve-proxy", help="Run an OpenAI-compatible proxy for Kaku Assistant.")
    proxy_cmd.add_argument("--host", default="127.0.0.1")
    proxy_cmd.add_argument("--port", type=int, default=8765)
    proxy_cmd.add_argument("--upstream-base-url", required=True)
    proxy_cmd.add_argument("--app-name", default="kaku")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    tz = get_timezone(args.timezone)

    if args.command == "serve-proxy":
        serve_proxy(
            ProxyConfig(
                host=args.host,
                port=args.port,
                upstream_base_url=args.upstream_base_url,
                db_path=args.db,
                tz=tz,
                app_name=args.app_name,
            )
        )
        return 0

    if args.command == "setup":
        return run_setup(args, tz)

    if args.command == "patch-augment":
        if args.status:
            status = inspect_augment_patch(extension_dir=args.extension_dir, capture_path=args.capture_file)
            print(_render_augment_patch_status(status, json_mode=args.json))
            return 0
        if args.remove:
            status = remove_augment_capture_patch(extension_dir=args.extension_dir, capture_path=args.capture_file)
            print(_render_augment_patch_status(status, json_mode=args.json, action="removed"))
            return 0
        status = apply_augment_capture_patch(extension_dir=args.extension_dir, capture_path=args.capture_file)
        print(_render_augment_patch_status(status, json_mode=args.json, action="installed"))
        return 0

    conn = connect_db(args.db)
    try:
        if args.command == "scan-codex":
            stats = scan_codex(conn, codex_home=args.codex_home, tz=tz)
            print(f"codex scan complete: files={stats.files_scanned} token_events={stats.records_seen}")
            return 0

        if args.command == "scan-claude-code":
            stats = scan_claude_code(conn, claude_home=args.claude_home, tz=tz)
            print(f"claude-code scan complete: files={stats.files_scanned} token_events={stats.records_seen}")
            return 0

        if args.command == "scan-augment":
            exact_stats = scan_augment(conn, capture_file=args.capture_file, tz=tz)
            history_stats = scan_augment_history(
                conn,
                workspace_storage_root=args.workspace_storage_root,
                tz=tz,
            )
            print(
                "augment scan complete: "
                f"exact_lines={exact_stats.lines_scanned} "
                f"exact_records={exact_stats.records_emitted} "
                f"history_selection_entries={history_stats.selection_entries_seen} "
                f"history_checkpoints={history_stats.checkpoint_files_seen} "
                f"history_records={history_stats.request_records_emitted}"
            )
            return 0

        if args.command == "scan-chatgpt-export":
            stats = scan_chatgpt_export(conn, export_path=args.export_file, tz=tz)
            if stats.export_path is None:
                print("chatgpt export scan complete: export not found")
            else:
                print(
                    "chatgpt export scan complete: "
                    f"export={stats.export_path} "
                    f"conversations={stats.conversations_seen} "
                    f"messages={stats.messages_seen} "
                    f"emitted={stats.records_emitted}"
                )
            return 0

        if args.command == "scan-copilot":
            stats = scan_copilot(
                conn,
                export_path=args.export_file,
                org=args.org,
                enterprise=args.enterprise,
                day=args.day,
                user_login=args.user_login,
                all_users=args.all_users,
                tz=tz,
            )
            if stats.api_error:
                print(f"copilot scan failed: {stats.api_error}")
                return 1
            if stats.export_path is None and stats.endpoint is None:
                print("copilot scan complete: export/report not found")
            else:
                print(
                    "copilot scan complete: "
                    f"source={'api' if stats.endpoint else 'file'} "
                    f"filter={stats.user_filter or 'all-users'} "
                    f"rows={stats.rows_seen} "
                    f"cli_rows={stats.cli_rows_seen} "
                    f"skipped_without_cli_tokens={stats.skipped_without_cli_tokens} "
                    f"filtered_out={stats.filtered_out_rows} "
                    f"emitted={stats.records_emitted}"
                )
            return 0

        if args.command == "scan-codebuddy":
            stats = scan_codebuddy(conn, tasks_root=args.codebuddy_tasks_root, tz=tz)
            print(
                "codebuddy scan complete: "
                f"tasks={stats.tasks_seen} emitted={stats.records_emitted}"
            )
            return 0

        if args.command == "scan-cursor":
            stats = scan_cursor(conn, sentry_scope_path=args.cursor_sentry_scope, tz=tz)
            print(
                "cursor scan complete: "
                f"events={stats.events_seen} emitted={stats.records_emitted}"
            )
            return 0

        if args.command == "scan-trae":
            stats = scan_trae(conn, tasks_root=args.trae_tasks_root, tz=tz)
            print(
                "trae scan complete: "
                f"tasks={stats.tasks_seen} "
                f"request_events={stats.request_events_seen} "
                f"emitted={stats.records_emitted}"
            )
            return 0

        if args.command == "scan-warp":
            stats = scan_warp(
                conn,
                warp_db=args.warp_db,
                tz=tz,
                baseline_only=args.baseline_only,
            )
            print(
                "warp scan complete: "
                f"conversations={stats.conversations_seen} emitted={stats.records_emitted}"
            )
            return 0

        if args.command == "scan-all":
            codex_stats = scan_codex(conn, codex_home=args.codex_home, tz=tz)
            claude_stats = scan_claude_code(conn, claude_home=args.claude_home, tz=tz)
            augment_stats = scan_augment(conn, capture_file=args.augment_capture_file, tz=tz)
            augment_history_stats = scan_augment_history(
                conn,
                workspace_storage_root=args.augment_workspace_storage_root,
                tz=tz,
            )
            chatgpt_stats = scan_chatgpt_export(conn, export_path=args.chatgpt_export_file, tz=tz)
            copilot_stats = scan_copilot(
                conn,
                export_path=args.copilot_export_file,
                org=None,
                enterprise=None,
                day=None,
                user_login=None,
                all_users=False,
                tz=tz,
            )
            codebuddy_stats = scan_codebuddy(conn, tasks_root=args.codebuddy_tasks_root, tz=tz)
            cursor_stats = scan_cursor(conn, sentry_scope_path=args.cursor_sentry_scope, tz=tz)
            trae_stats = scan_trae(conn, tasks_root=args.trae_tasks_root, tz=tz)
            warp_stats = scan_warp(
                conn,
                warp_db=args.warp_db,
                tz=tz,
                baseline_only=args.baseline_only_warp,
            )
            print(
                "scan complete: "
                f"codex_files={codex_stats.files_scanned} "
                f"codex_events={codex_stats.records_seen} "
                f"claude_files={claude_stats.files_scanned} "
                f"claude_events={claude_stats.records_seen} "
                f"augment_exact_lines={augment_stats.lines_scanned} "
                f"augment_exact_records={augment_stats.records_emitted} "
                f"augment_history_selection_entries={augment_history_stats.selection_entries_seen} "
                f"augment_history_checkpoints={augment_history_stats.checkpoint_files_seen} "
                f"augment_history_records={augment_history_stats.request_records_emitted} "
                f"chatgpt_conversations={chatgpt_stats.conversations_seen} "
                f"chatgpt_messages={chatgpt_stats.messages_seen} "
                f"chatgpt_emitted={chatgpt_stats.records_emitted} "
                f"copilot_rows={copilot_stats.rows_seen} "
                f"copilot_cli_rows={copilot_stats.cli_rows_seen} "
                f"copilot_emitted={copilot_stats.records_emitted} "
                f"codebuddy_tasks={codebuddy_stats.tasks_seen} "
                f"codebuddy_emitted={codebuddy_stats.records_emitted} "
                f"cursor_events={cursor_stats.events_seen} "
                f"cursor_emitted={cursor_stats.records_emitted} "
                f"trae_tasks={trae_stats.tasks_seen} "
                f"trae_request_events={trae_stats.request_events_seen} "
                f"trae_emitted={trae_stats.records_emitted} "
                f"warp_conversations={warp_stats.conversations_seen} "
                f"warp_emitted={warp_stats.records_emitted}"
            )
            return 0

        if args.command == "report-daily":
            target_date = _resolve_date_alias(args.date, tz)
            rendered = render_daily_report(conn, target_date, json_mode=args.json, tz=tz)
            _emit_rendered(rendered, args.output)
            return 0

        if args.command == "report-range":
            rendered = render_range_report(conn, args.last, tz, json_mode=args.json)
            print(rendered)
            return 0

        if args.command == "report-clients":
            rendered = render_clients_report(
                conn,
                tz,
                target_date=_resolve_date_alias(args.date, tz) if args.date else None,
                last_days=args.last,
                json_mode=args.json,
            )
            print(rendered)
            return 0

        if args.command == "pricing":
            print(render_pricing_report(json_mode=args.json))
            return 0

        if args.command == "budget":
            if args.budget_command == "init":
                path = write_budget_template(force=args.force)
                print(f"wrote budget template to {path}")
                return 0
            print(render_budget_report(conn, tz, json_mode=args.json))
            return 0

        if args.command == "doctor":
            print(render_doctor_report(conn, args.db, tz, json_mode=args.json))
            return 0

        parser.error(f"unsupported command: {args.command}")
    finally:
        conn.close()
    return 1


def render_daily_report(conn: sqlite3.Connection, target_date: str, *, json_mode: bool, tz=None) -> str:
    tz = tz or get_timezone(None)
    totals = conn.execute(
        """
        SELECT
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cached_input_tokens) AS cached_input_tokens,
            SUM(reasoning_tokens) AS reasoning_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records
        FROM usage_records
        WHERE local_date = ?
        """,
        (target_date,),
    ).fetchone()
    detailed_rows = _enrich_usage_rows(
        conn.execute(
        """
        SELECT
            app,
            source,
            measurement_method,
            COALESCE(model, '') AS model,
            COALESCE(json_extract(metadata_json, '$.originator'), '') AS originator,
            COALESCE(json_extract(metadata_json, '$.model_provider'), '') AS model_provider,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cached_input_tokens) AS cached_input_tokens,
            SUM(reasoning_tokens) AS reasoning_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records
        FROM usage_records
        WHERE local_date = ?
        GROUP BY app, source, measurement_method, model, originator, model_provider
        ORDER BY total_tokens DESC, credits DESC, app, source, model, originator, model_provider, measurement_method
        """,
        (target_date,),
        ).fetchall()
    )
    estimated_total_cost = _sum_estimated_cost(detailed_rows)
    by_terminal = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["terminal"],
        key_builder=lambda row: (_terminal_label(row["app"], row["source"], row.get("originator")),),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["terminal"])),
    )
    by_model = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["model_label"],
        key_builder=lambda row: (row["model_label"],),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["model_label"])),
    )
    by_source = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["app", "source", "model_label"],
        key_builder=lambda row: (row["app"], row["source"], row["model_label"]),
        sort_key=lambda row: (
            -int(row["total_tokens"]),
            -float(row["credits"]),
            str(row["app"]),
            str(row["source"]),
            str(row["model_label"]),
        ),
    )
    by_hour = _aggregate_hourly_usage_rows(conn, target_date, tz)

    if json_mode:
        totals_payload = dict(totals)
        totals_payload["estimated_cost_usd"] = estimated_total_cost
        payload = {
            "date": target_date,
            "totals": totals_payload,
            "by_hour": by_hour,
            "by_terminal": by_terminal,
            "by_model": by_model,
            "by_source": by_source,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [
        f"Daily token report for {target_date}",
        "",
        (
            "Totals: "
            f"input={format_int(totals['input_tokens'])} "
            f"output={format_int(totals['output_tokens'])} "
            f"cached={format_int(totals['cached_input_tokens'])} "
            f"reasoning={format_int(totals['reasoning_tokens'])} "
            f"total={format_int(totals['total_tokens'])} "
            f"est_usd={format_float(estimated_total_cost)} "
            f"credits={format_float(totals['credits'])} "
            f"records={totals['records']}"
        ),
        "",
        "By hour:",
    ]
    if not by_hour:
        lines.append("  (no records)")
    else:
        lines.append(
            _render_table(
                headers=[
                    "Hour",
                    "Total",
                    "Input",
                    "Output",
                    "Cached",
                    "Reasoning",
                    "Est.$",
                    "Credits",
                    "Records",
                ],
                rows=[
                    [
                        row["hour_label"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["estimated_cost_usd"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_hour
                ],
                right_align={1, 2, 3, 4, 5, 6, 7, 8},
            )
        )

    lines.extend(
        [
            "",
        "By terminal:",
        ]
    )
    if not by_terminal:
        lines.append("  (no records)")
    else:
        lines.append(
            _render_table(
                headers=[
                    "Terminal",
                    "Method",
                    "Total",
                    "Input",
                    "Output",
                    "Cached",
                    "Reasoning",
                    "Est.$",
                    "Credits",
                    "Records",
                ],
                rows=[
                    [
                        row["terminal"],
                        row["method"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["estimated_cost_usd"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_terminal
                ],
                right_align={2, 3, 4, 5, 6, 7, 8, 9},
            )
        )

    lines.extend(
        [
            "",
            "By model:",
        ]
    )
    if not by_model:
        lines.append("  (no records)")
    else:
        lines.append(
            _render_table(
                headers=[
                    "Model",
                    "Method",
                    "Total",
                    "Input",
                    "Output",
                    "Cached",
                    "Reasoning",
                    "Est.$",
                    "Credits",
                    "Records",
                ],
                rows=[
                    [
                        row["model_label"],
                        row["method"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["estimated_cost_usd"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_model
                ],
                right_align={2, 3, 4, 5, 6, 7, 8, 9},
            )
        )

    lines.extend(
        [
            "",
        "By source:",
        ]
    )
    if not by_source:
        lines.append("  (no records)")
    else:
        lines.append(
            _render_table(
                headers=[
                    "App",
                    "Source",
                    "Model",
                    "Method",
                    "Total",
                    "Input",
                    "Output",
                    "Cached",
                    "Reasoning",
                    "Est.$",
                    "Credits",
                    "Records",
                ],
                rows=[
                    [
                        row["app"],
                        row["source"],
                        row["model_label"],
                        row["method"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["estimated_cost_usd"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_source
                ],
                right_align={4, 5, 6, 7, 8, 9, 10, 11},
            )
        )
    return "\n".join(lines)


def render_range_report(conn: sqlite3.Connection, last_days: int, tz, *, json_mode: bool) -> str:
    end_date = today_string(tz)
    detailed_rows = _enrich_usage_rows(
        conn.execute(
        """
        SELECT
            local_date,
            app,
            source,
            measurement_method,
            COALESCE(model, '') AS model,
            COALESCE(json_extract(metadata_json, '$.originator'), '') AS originator,
            COALESCE(json_extract(metadata_json, '$.model_provider'), '') AS model_provider,
            SUM(input_tokens) AS input_tokens,
            SUM(output_tokens) AS output_tokens,
            SUM(cached_input_tokens) AS cached_input_tokens,
            SUM(reasoning_tokens) AS reasoning_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records
        FROM usage_records
        WHERE local_date >= date(?, ?)
        GROUP BY local_date, app, source, measurement_method, model, originator, model_provider
        ORDER BY local_date DESC, total_tokens DESC, app, source, model, originator, model_provider, measurement_method
        """,
        (end_date, f"-{max(last_days - 1, 0)} day"),
        ).fetchall()
    )
    by_date_rows = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["local_date"],
        key_builder=lambda row: (row["local_date"],),
        sort_key=lambda row: (-int(str(row["local_date"]).replace("-", "")),),
    )
    by_terminal = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["terminal"],
        key_builder=lambda row: (_terminal_label(row["app"], row["source"], row.get("originator")),),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["terminal"])),
    )
    by_model = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["model_label"],
        key_builder=lambda row: (row["model_label"],),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["model_label"])),
    )
    rows = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["local_date", "app", "source", "model_label"],
        key_builder=lambda row: (row["local_date"], row["app"], row["source"], row["model_label"]),
        sort_key=lambda row: (
            -int(str(row["local_date"]).replace("-", "")),
            -int(row["total_tokens"]),
            str(row["app"]),
            str(row["source"]),
            str(row["model_label"]),
        ),
    )
    if json_mode:
        return json.dumps(
            {
                "range_days": last_days,
                "by_date": by_date_rows,
                "by_terminal": by_terminal,
                "by_model": by_model,
                "by_source": rows,
            },
            ensure_ascii=False,
            indent=2,
        )

    lines = [f"Range report for last {last_days} day(s)", ""]
    if not by_date_rows:
        lines.append("(no records)")
        return "\n".join(lines)

    lines.extend(
        [
            "Trend (total tokens):",
            _render_trend_chart(
                by_date_rows,
                label_field="local_date",
                value_field="total_tokens",
                width=28,
            ),
            "",
            "By date:",
            _render_table(
                headers=["Date", "Total", "Input", "Output", "Cached", "Reasoning", "Est.$", "Credits", "Records"],
                rows=[
                    [
                        row["local_date"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["estimated_cost_usd"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_date_rows
                ],
                right_align={1, 2, 3, 4, 5, 6, 7, 8},
            ),
            "",
            "By terminal:",
            _render_table(
                headers=["Terminal", "Method", "Total", "Input", "Output", "Cached", "Reasoning", "Est.$", "Credits", "Records"],
                rows=[
                    [
                        row["terminal"],
                        row["method"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["estimated_cost_usd"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_terminal
                ],
                right_align={2, 3, 4, 5, 6, 7, 8, 9},
            ),
            "",
            "By model:",
            _render_table(
                headers=["Model", "Method", "Total", "Input", "Output", "Cached", "Reasoning", "Est.$", "Credits", "Records"],
                rows=[
                    [
                        row["model_label"],
                        row["method"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["estimated_cost_usd"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_model
                ],
                right_align={2, 3, 4, 5, 6, 7, 8, 9},
            ),
            "",
            "By source:",
        ]
    )

    lines.append(
        _render_table(
            headers=[
                "Date",
                "App",
                "Source",
                "Model",
                "Method",
                "Total",
                "Input",
                "Output",
                "Cached",
                "Reasoning",
                "Est.$",
                "Credits",
                "Records",
            ],
            rows=[
                [
                    row["local_date"],
                    row["app"],
                    row["source"],
                    row["model_label"],
                    row["method"],
                    format_int(row["total_tokens"]),
                    format_int(row["input_tokens"]),
                    format_int(row["output_tokens"]),
                    format_int(row["cached_input_tokens"]),
                    format_int(row["reasoning_tokens"]),
                    format_float(row["estimated_cost_usd"]),
                    format_float(row["credits"]),
                    str(row["records"]),
                ]
                for row in rows
            ],
            right_align={5, 6, 7, 8, 9, 10, 11, 12},
        )
    )
    return "\n".join(lines)


def render_clients_report(
    conn: sqlite3.Connection,
    tz,
    *,
    target_date: str | None,
    last_days: int | None,
    json_mode: bool,
) -> str:
    if last_days is None:
        target_date = target_date or today_string(tz)
    period_label, query_sql, query_params = _client_report_window(target_date=target_date, last_days=last_days, tz=tz)

    source_rows = conn.execute(
        f"""
        SELECT
            app,
            source,
            COALESCE(json_extract(metadata_json, '$.originator'), '') AS originator,
            measurement_method,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records,
            MAX(started_at) AS last_seen
        FROM usage_records
        WHERE {query_sql}
        GROUP BY app, source, originator, measurement_method
        ORDER BY total_tokens DESC, credits DESC, app, source, originator
        """,
        query_params,
    ).fetchall()

    method_rows = conn.execute(
        f"""
        SELECT
            measurement_method,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records
        FROM usage_records
        WHERE {query_sql}
        GROUP BY measurement_method
        ORDER BY CASE measurement_method
            WHEN 'exact' THEN 0
            WHEN 'partial' THEN 1
            WHEN 'estimated' THEN 2
            ELSE 3
        END
        """,
        query_params,
    ).fetchall()

    date_rows = []
    if last_days is not None:
        date_rows = conn.execute(
            f"""
            SELECT
                local_date,
                measurement_method,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(credits), 0.0) AS credits,
                COUNT(*) AS records
            FROM usage_records
            WHERE {query_sql}
            GROUP BY local_date, measurement_method
            ORDER BY local_date DESC
            """,
            query_params,
        ).fetchall()

    installed_map = detect_installed_clients()
    by_client = _aggregate_client_rows(source_rows, installed_map)
    blended_total_tokens = sum(int(row["total_tokens"]) for row in method_rows)
    blended_total_credits = sum(float(row["credits"]) for row in method_rows)
    blended_total_records = sum(int(row["records"]) for row in method_rows)

    if json_mode:
        payload = {
            "period": period_label,
            "method_totals": [dict(row) for row in method_rows],
            "by_date": _build_client_date_rows(date_rows),
            "by_client": by_client,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [
        f"Client usage report for {period_label}",
        "",
        (
            "Blended totals: "
            f"tokens={format_int(blended_total_tokens)} "
            f"credits={format_float(blended_total_credits)} "
            f"records={blended_total_records}"
        ),
        "",
        "By method:",
    ]
    if method_rows:
        lines.append(
            _render_table(
                headers=["Method", "Total", "Credits", "Records"],
                rows=[
                    [
                        row["measurement_method"],
                        format_int(row["total_tokens"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in method_rows
                ],
                right_align={1, 2, 3},
            )
        )
    else:
        lines.append("  (no records)")

    if date_rows:
        lines.extend(
            [
                "",
                "By date:",
                _render_table(
                    headers=["Date", "Exact", "Partial", "Estimated", "Blended", "Credits", "Records"],
                    rows=[
                        [
                            row["local_date"],
                            format_int(row["exact_tokens"]),
                            format_int(row["partial_tokens"]),
                            format_int(row["estimated_tokens"]),
                            format_int(row["blended_tokens"]),
                            format_float(row["credits"]),
                            str(row["records"]),
                        ]
                        for row in _build_client_date_rows(date_rows)
                    ],
                    right_align={1, 2, 3, 4, 5, 6},
                ),
            ]
        )

    lines.extend(
        [
            "",
            "By client:",
            _render_table(
                headers=["Client", "Installed", "Coverage", "Total", "Credits", "Records", "Last Seen", "Notes"],
                rows=[
                    [
                        row["label"],
                        "yes" if row["installed"] else "no",
                        row["coverage"],
                        format_int(row["total_tokens"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                        row["last_seen"] or "-",
                        row["notes"],
                    ]
                    for row in by_client
                ],
                right_align={3, 4, 5},
            ),
        ]
    )
    return "\n".join(lines)


def render_pricing_report(*, json_mode: bool) -> str:
    resolution = resolve_price_book()
    rows = [
        {
            "model": profile.model,
            "input_per_million": profile.pricing.input_per_million,
            "cached_input_per_million": profile.pricing.cached_input_per_million,
            "output_per_million": profile.pricing.output_per_million,
            "source": profile.source,
        }
        for profile in iter_price_book(resolution)
    ]
    if json_mode:
        return json.dumps(
            {
                "profiles": rows,
                "override_path": str(resolution.override_path),
                "override_loaded": resolution.override_loaded,
                "override_error": resolution.override_error,
                "notes": {
                    "estimate_column": "Est.$ is a local estimate, not vendor billing.",
                    "unit": "USD per 1M tokens",
                },
            },
            ensure_ascii=False,
            indent=2,
        )

    return "\n".join(
        [
            "Pricing profiles for Est.$",
            "",
            "Local estimate only. Unit: USD per 1M tokens.",
            (
                f"Override file: {resolution.override_path} "
                f"({'loaded' if resolution.override_loaded else 'not loaded'})"
            ),
            (
                f"Override status: fallback to built-in ({resolution.override_error})"
                if resolution.override_error
                else "Override status: built-in + override merge"
                if resolution.override_loaded
                else "Override status: built-in only"
            ),
            "",
            _render_table(
                headers=["Model", "Input $/1M", "Cached $/1M", "Output $/1M", "Source"],
                rows=[
                    [
                        row["model"],
                        format_float(row["input_per_million"], precision=3),
                        format_float(row["cached_input_per_million"], precision=3),
                        format_float(row["output_per_million"], precision=3),
                        row["source"],
                    ]
                    for row in rows
                ],
                right_align={1, 2, 3},
            ),
        ]
    )


def render_budget_report(conn: sqlite3.Connection, tz, *, json_mode: bool) -> str:
    resolution = resolve_budget_config()
    today = today_string(tz)
    week_start = _shift_date(today, -6)
    month_start = _month_start(today)
    windows = [
        ("Today", today, today, resolution.config.daily_est_usd, resolution.config.daily_credits),
        ("Last 7 Days", week_start, today, resolution.config.weekly_est_usd, resolution.config.weekly_credits),
        ("Month to Date", month_start, today, resolution.config.monthly_est_usd, resolution.config.monthly_credits),
    ]

    window_rows = [
        _budget_window_row(
            conn,
            label=label,
            start_date=start_date,
            end_date=end_date,
            est_budget=est_budget,
            credits_budget=credits_budget,
        )
        for label, start_date, end_date, est_budget, credits_budget in windows
    ]

    payload = {
        "budget_path": str(resolution.path),
        "budget_exists": resolution.exists,
        "budget_loaded": resolution.loaded,
        "budget_error": resolution.error,
        "currency": resolution.config.currency,
        "windows": window_rows,
    }

    if json_mode:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [
        "TokKit budget",
        "",
        f"Budget file: {resolution.path} ({'loaded' if resolution.loaded else 'not loaded' if resolution.exists else 'missing'})",
    ]
    if resolution.error:
        lines.append(f"Budget error: {resolution.error}")
    if not resolution.exists:
        lines.append("Run `tok budget init` to create a starter budget file.")

    lines.extend(
        [
            "",
            _render_table(
                headers=[
                    "Window",
                    "Total",
                    "Est.$",
                    "Budget $",
                    "USD %",
                    "Credits",
                    "Budget Credits",
                    "Credits %",
                    "Status",
                ],
                rows=[
                    [
                        row["window"],
                        format_int(row["total_tokens"]),
                        format_float(row["estimated_cost_usd"]),
                        format_float(row["est_budget"]),
                        row["est_pct_label"],
                        format_float(row["credits"]),
                        format_float(row["credits_budget"]),
                        row["credits_pct_label"],
                        row["status"],
                    ]
                    for row in window_rows
                ],
                right_align={1, 2, 3, 5, 6},
            ),
        ]
    )
    return "\n".join(lines)


def render_doctor_report(conn: sqlite3.Connection, db_path: Path, tz, *, json_mode: bool) -> str:
    pricing_resolution = resolve_price_book()
    installed_map = detect_installed_clients()
    augment_state = _read_augment_setup_state()
    chatgpt_export_path = discover_chatgpt_export_path()
    copilot_export_path = discover_copilot_export_path()
    source_rows = conn.execute(
        """
        SELECT
            app,
            source,
            COALESCE(json_extract(metadata_json, '$.originator'), '') AS originator,
            measurement_method,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records,
            MAX(started_at) AS last_seen
        FROM usage_records
        GROUP BY app, source, originator, measurement_method
        ORDER BY total_tokens DESC, credits DESC, app, source, originator
        """
    ).fetchall()
    by_client = _aggregate_client_rows(source_rows, installed_map)
    total_records = conn.execute("SELECT COUNT(*) AS count FROM usage_records").fetchone()["count"]
    latest_record = conn.execute("SELECT MAX(started_at) AS last_seen FROM usage_records").fetchone()["last_seen"]
    app_home = resolve_app_home()
    report_dir = default_report_dir()
    log_dir = default_log_dir()
    launchd_status = _detect_launchd_status()

    config_payload = {
        "app_home": str(app_home),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "report_dir": str(report_dir),
        "report_dir_exists": report_dir.exists(),
        "log_dir": str(log_dir),
        "log_dir_exists": log_dir.exists(),
        "timezone": str(tz),
        "pricing_override_path": str(pricing_resolution.override_path),
        "pricing_override_loaded": pricing_resolution.override_loaded,
        "pricing_override_error": pricing_resolution.override_error,
        "legacy_home_in_use": ".tokstat" in str(db_path),
        "usage_records": total_records,
        "latest_record": latest_record,
    }

    launchd_payload = {
        "tokkit_labels": launchd_status["tokkit_labels"],
        "legacy_tokstat_labels": launchd_status["legacy_tokstat_labels"],
        "installed": bool(launchd_status["tokkit_labels"]),
    }

    doctor_rows = [
        {
            "client": row["label"],
            "installed": row["installed"],
            "coverage": row["coverage"],
            "records": row["records"],
            "last_seen": row["last_seen"],
            "notes": _doctor_notes_for_client(
                row,
                augment_state=augment_state,
                chatgpt_export_path=chatgpt_export_path,
                copilot_export_path=copilot_export_path,
            ),
            "recommended_action": _doctor_action_for_client(
                row,
                augment_state=augment_state,
                chatgpt_export_path=chatgpt_export_path,
            ),
        }
        for row in by_client
    ]

    if json_mode:
        return json.dumps(
            {
                "config": config_payload,
                "launchd": launchd_payload,
                "augment": augment_state,
                "chatgpt_export_path": str(chatgpt_export_path) if chatgpt_export_path else None,
                "copilot_export_path": str(copilot_export_path) if copilot_export_path else None,
                "clients": doctor_rows,
            },
            ensure_ascii=False,
            indent=2,
        )

    lines = [
        "TokKit doctor",
        "",
        "Configuration:",
        _render_table(
            headers=["Item", "Value"],
            rows=[
                ["App home", str(app_home)],
                ["Database", str(db_path)],
                ["Database exists", "yes" if db_path.exists() else "no"],
                ["Report dir", str(report_dir)],
                ["Report dir exists", "yes" if report_dir.exists() else "no"],
                ["Log dir", str(log_dir)],
                ["Log dir exists", "yes" if log_dir.exists() else "no"],
                ["Timezone", str(tz)],
                ["Pricing override", str(pricing_resolution.override_path)],
                ["Override loaded", "yes" if pricing_resolution.override_loaded else "no"],
                ["Legacy .tokstat home", "yes" if ".tokstat" in str(db_path) else "no"],
                ["Usage records", str(total_records)],
                ["Latest record", latest_record or "-"],
            ],
        ),
        "",
        "Automation:",
        _render_table(
            headers=["Item", "Value"],
            rows=[
                ["TokKit launchd labels", ", ".join(launchd_status["tokkit_labels"]) or "-"],
                ["Legacy tokstat labels", ", ".join(launchd_status["legacy_tokstat_labels"]) or "-"],
                ["Automatic mode installed", "yes" if launchd_status["tokkit_labels"] else "no"],
            ],
        ),
        "",
        "Augment diagnostics:",
        _render_table(
            headers=["Item", "Value"],
            rows=[
                ["Settings path", str(augment_state["settings_path"])],
                ["Settings exist", "yes" if augment_state["settings_exists"] else "no"],
                ["Capture hook installed", "yes" if augment_state["capture_patch_installed"] else "no"],
                ["Capture backup exists", "yes" if augment_state["capture_backup_exists"] else "no"],
                ["Capture file", str(augment_state["capture_file"])],
                ["Capture file exists", "yes" if augment_state["capture_file_exists"] else "no"],
                ["Captured events", str(augment_state["capture_events"])],
                ["Captured bytes", str(augment_state["capture_bytes"])],
                ["OAuth mode", "yes" if augment_state["use_oauth"] else "no"],
                ["API token configured", "yes" if augment_state["api_token_configured"] else "no"],
                ["Completion URL", augment_state["completion_url"] or "-"],
                ["Chat URL override", augment_state["chat_url"] or "-"],
                ["Next Edit URL override", augment_state["next_edit_url"] or "-"],
                ["Smart Paste URL override", augment_state["smart_paste_url"] or "-"],
                ["Proxy exact potential", "yes" if augment_state["proxy_exact_possible"] else "no"],
                ["Assessment", str(augment_state["assessment"])],
                ["Proxy assessment", str(augment_state.get("proxy_assessment") or "-")],
            ],
        ),
        "",
        "By client:",
        _render_table(
            headers=["Client", "Installed", "Coverage", "Records", "Last Seen", "Recommended Action", "Notes"],
            rows=[
                [
                    row["client"],
                    "yes" if row["installed"] else "no",
                    row["coverage"],
                    str(row["records"]),
                    row["last_seen"] or "-",
                    row["recommended_action"],
                    row["notes"],
                ]
                for row in doctor_rows
            ],
            right_align={3},
        ),
    ]

    if pricing_resolution.override_error:
        lines.extend(["", f"Pricing override error: {pricing_resolution.override_error}"])

    return "\n".join(lines)


def run_setup(args, tz) -> int:
    action_logs: list[str] = []

    try:
        if args.migrate_home:
            action_logs.append(_migrate_home_directory())

        kaku_state_before = _read_kaku_setup_state()
        upstream_url = args.kaku_upstream_base_url or _infer_kaku_upstream_base_url(kaku_state_before)

        if args.enable_kaku_proxy:
            action_logs.append(_configure_kaku_proxy(kaku_state_before["config_path"]))

        if args.install_launchd:
            wants_kaku_proxy = args.enable_kaku_proxy or bool(kaku_state_before["proxy_configured"])
            if wants_kaku_proxy and not upstream_url:
                raise RuntimeError(
                    "Kaku is configured for the local proxy, but no upstream base URL is known. "
                    "Pass --kaku-upstream-base-url <url>."
                )
            should_install_proxy = wants_kaku_proxy and bool(upstream_url)
            action_logs.append(
                _install_launchd_jobs(
                    scan_mode=args.scan_mode,
                    install_kaku_proxy=should_install_proxy,
                    kaku_upstream_base_url=upstream_url,
                )
            )
    except RuntimeError as exc:
        print(f"tokkit setup: {exc}", file=sys.stderr)
        return 1

    effective_db_path = default_db_path() if args.db == DEFAULT_DB_PATH else args.db
    conn = connect_db(effective_db_path)
    try:
        rendered = render_setup_report(
            conn,
            effective_db_path,
            tz,
            json_mode=args.json,
            action_logs=action_logs,
        )
    finally:
        conn.close()

    print(rendered)
    return 0


def render_setup_report(
    conn: sqlite3.Connection,
    db_path: Path,
    tz,
    *,
    json_mode: bool,
    action_logs: list[str] | None = None,
) -> str:
    action_logs = action_logs or []
    app_home = resolve_app_home()
    report_dir = default_report_dir()
    log_dir = default_log_dir()
    pricing_resolution = resolve_price_book()
    launchd_status = _detect_launchd_status()
    launchd_env = _read_launchd_env("com.laoyao.tokkit.scan")
    proxy_launchd_env = _read_launchd_env("com.laoyao.tokkit.kaku-proxy")
    kaku_state = _read_kaku_setup_state()
    usage_records = conn.execute("SELECT COUNT(*) AS count FROM usage_records").fetchone()["count"]

    recommendations = _build_setup_recommendations(
        app_home=app_home,
        launchd_status=launchd_status,
        kaku_state=kaku_state,
        scan_mode=launchd_env.get("TOKKIT_SCAN_MODE", ""),
        pricing_override_exists=pricing_resolution.override_path.exists(),
        proxy_upstream=proxy_launchd_env.get("TOKKIT_KAKU_UPSTREAM_BASE_URL", ""),
    )

    payload = {
        "actions": action_logs,
        "app_home": str(app_home),
        "db_path": str(db_path),
        "report_dir": str(report_dir),
        "log_dir": str(log_dir),
        "timezone": str(tz),
        "usage_records": usage_records,
        "launchd": {
            "installed": bool(launchd_status["tokkit_labels"]),
            "labels": launchd_status["tokkit_labels"],
            "scan_mode": launchd_env.get("TOKKIT_SCAN_MODE"),
            "proxy_upstream_base_url": proxy_launchd_env.get("TOKKIT_KAKU_UPSTREAM_BASE_URL"),
        },
        "kaku": {
            "config_path": str(kaku_state["config_path"]),
            "config_exists": kaku_state["config_exists"],
            "enabled": kaku_state["enabled"],
            "model": kaku_state["model"],
            "base_url": kaku_state["base_url"],
            "proxy_configured": kaku_state["proxy_configured"],
        },
        "pricing": {
            "override_path": str(pricing_resolution.override_path),
            "override_exists": pricing_resolution.override_path.exists(),
            "override_loaded": pricing_resolution.override_loaded,
        },
        "recommendations": recommendations,
    }

    if json_mode:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines: list[str] = ["TokKit setup", ""]

    if action_logs:
        lines.extend(
            [
                "Actions applied:",
                *[f"- {item}" for item in action_logs],
                "",
            ]
        )

    lines.extend(
        [
            "Current state:",
            _render_table(
                headers=["Item", "Value"],
                rows=[
                    ["App home", str(app_home)],
                    ["Database", str(db_path)],
                    ["Report dir", str(report_dir)],
                    ["Log dir", str(log_dir)],
                    ["Timezone", str(tz)],
                    ["Usage records", str(usage_records)],
                    ["Launchd installed", "yes" if launchd_status["tokkit_labels"] else "no"],
                    ["Launchd scan mode", launchd_env.get("TOKKIT_SCAN_MODE", "-") or "-"],
                    ["Kaku config", str(kaku_state["config_path"])],
                    ["Kaku config exists", "yes" if kaku_state["config_exists"] else "no"],
                    ["Kaku enabled", "yes" if kaku_state["enabled"] else "no"],
                    ["Kaku model", kaku_state["model"] or "-"],
                    ["Kaku base_url", kaku_state["base_url"] or "-"],
                    ["Kaku proxy configured", "yes" if kaku_state["proxy_configured"] else "no"],
                    ["Kaku upstream", proxy_launchd_env.get("TOKKIT_KAKU_UPSTREAM_BASE_URL", "-") or "-"],
                    ["Pricing override", str(pricing_resolution.override_path)],
                    ["Pricing override exists", "yes" if pricing_resolution.override_path.exists() else "no"],
                ],
            ),
            "",
            "Recommended next steps:",
        ]
    )

    if recommendations:
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(recommendations, start=1))
    else:
        lines.append("1. Setup looks healthy. Use `tok doctor` for deeper diagnostics.")

    return "\n".join(lines)


def _client_report_window(*, target_date: str | None, last_days: int | None, tz) -> tuple[str, str, tuple[str, ...]]:
    if last_days is not None:
        end_date = today_string(tz)
        return (
            f"last {last_days} day(s)",
            "local_date >= date(?, ?)",
            (end_date, f"-{max(last_days - 1, 0)} day"),
        )
    resolved_date = target_date or today_string(tz)
    return (resolved_date, "local_date = ?", (resolved_date,))


def _aggregate_client_rows(source_rows: list[sqlite3.Row], installed_map: dict[str, bool]) -> list[dict[str, object]]:
    totals: dict[str, dict[str, object]] = {
        client.key: {
            "key": client.key,
            "label": client.label,
            "installed": installed_map.get(client.key, False),
            "coverage": client.default_coverage,
            "notes": client.notes,
            "total_tokens": 0,
            "credits": 0.0,
            "records": 0,
            "last_seen": None,
            "methods": set(),
        }
        for client in CLIENT_DEFINITIONS
    }

    for row in source_rows:
        client_key = logical_client_for_usage_row(row["app"], row["source"], row["originator"])
        if client_key is None or client_key not in totals:
            continue
        item = totals[client_key]
        item["total_tokens"] = int(item["total_tokens"]) + int(row["total_tokens"])
        item["credits"] = float(item["credits"]) + float(row["credits"])
        item["records"] = int(item["records"]) + int(row["records"])
        item["methods"].add(row["measurement_method"])
        last_seen = row["last_seen"]
        if last_seen and (item["last_seen"] is None or str(last_seen) > str(item["last_seen"])):
            item["last_seen"] = str(last_seen)

    ordered: list[dict[str, object]] = []
    for client in CLIENT_DEFINITIONS:
        item = totals[client.key]
        methods = sorted(item.pop("methods"))
        if methods:
            item["coverage"] = "+".join(methods)
        item["credits"] = round(float(item["credits"]), 8)
        ordered.append(item)

    ordered.sort(
        key=lambda item: (
            0 if item["records"] else 1,
            -int(item["total_tokens"]),
            item["label"],
        )
    )
    return ordered


def _build_client_date_rows(rows: list[sqlite3.Row]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        bucket = grouped.setdefault(
            row["local_date"],
            {
                "local_date": row["local_date"],
                "exact_tokens": 0,
                "partial_tokens": 0,
                "estimated_tokens": 0,
                "blended_tokens": 0,
                "credits": 0.0,
                "records": 0,
            },
        )
        method = row["measurement_method"]
        if method == "exact":
            bucket["exact_tokens"] = int(bucket["exact_tokens"]) + int(row["total_tokens"])
        elif method == "partial":
            bucket["partial_tokens"] = int(bucket["partial_tokens"]) + int(row["total_tokens"])
        elif method == "estimated":
            bucket["estimated_tokens"] = int(bucket["estimated_tokens"]) + int(row["total_tokens"])
        bucket["blended_tokens"] = int(bucket["blended_tokens"]) + int(row["total_tokens"])
        bucket["credits"] = float(bucket["credits"]) + float(row["credits"])
        bucket["records"] = int(bucket["records"]) + int(row["records"])

    ordered = [grouped[key] for key in sorted(grouped.keys(), reverse=True)]
    for row in ordered:
        row["credits"] = round(float(row["credits"]), 8)
    return ordered


def _detect_launchd_status() -> dict[str, list[str]]:
    launch_agents_dir = Path.home() / "Library/LaunchAgents"
    labels = {
        "tokkit_labels": [],
        "legacy_tokstat_labels": [],
    }
    if not launch_agents_dir.exists():
        return labels

    for label in (
        "com.laoyao.tokkit.scan",
        "com.laoyao.tokkit.daily-report",
        "com.laoyao.tokkit.kaku-proxy",
    ):
        if (launch_agents_dir / f"{label}.plist").exists():
            labels["tokkit_labels"].append(label)

    for label in (
        "com.laoyao.tokstat.scan",
        "com.laoyao.tokstat.daily-report",
        "com.laoyao.tokstat.kaku-proxy",
    ):
        if (launch_agents_dir / f"{label}.plist").exists():
            labels["legacy_tokstat_labels"].append(label)
    return labels


def _budget_window_row(
    conn: sqlite3.Connection,
    *,
    label: str,
    start_date: str,
    end_date: str,
    est_budget: float | None,
    credits_budget: float | None,
) -> dict[str, object]:
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits
        FROM usage_records
        WHERE local_date >= ? AND local_date <= ?
        """,
        (start_date, end_date),
    ).fetchone()
    detailed_rows = _enrich_usage_rows(
        conn.execute(
            """
            SELECT
                app,
                source,
                measurement_method,
                COALESCE(model, '') AS model,
                COALESCE(json_extract(metadata_json, '$.model_provider'), '') AS model_provider,
                SUM(input_tokens) AS input_tokens,
                SUM(output_tokens) AS output_tokens,
                SUM(cached_input_tokens) AS cached_input_tokens,
                SUM(reasoning_tokens) AS reasoning_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(credits), 0.0) AS credits,
                COUNT(*) AS records
            FROM usage_records
            WHERE local_date >= ? AND local_date <= ?
            GROUP BY app, source, measurement_method, model, model_provider
            """,
            (start_date, end_date),
        ).fetchall()
    )
    estimated_cost = _sum_estimated_cost(detailed_rows)
    est_pct = _ratio(estimated_cost, est_budget)
    credits_pct = _ratio(float(totals["credits"]), credits_budget)
    return {
        "window": label,
        "start_date": start_date,
        "end_date": end_date,
        "total_tokens": int(totals["total_tokens"]),
        "estimated_cost_usd": estimated_cost,
        "est_budget": est_budget,
        "est_pct": est_pct,
        "est_pct_label": _format_ratio(est_pct),
        "credits": round(float(totals["credits"]), 8),
        "credits_budget": credits_budget,
        "credits_pct": credits_pct,
        "credits_pct_label": _format_ratio(credits_pct),
        "status": _budget_status(est_pct, credits_pct),
    }


def _read_launchd_env(label: str) -> dict[str, str]:
    plist_path = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    if not plist_path.exists():
        return {}
    with plist_path.open("rb") as handle:
        payload = plistlib.load(handle)
    environment = payload.get("EnvironmentVariables", {})
    if not isinstance(environment, dict):
        return {}
    return {str(key): str(value) for key, value in environment.items()}


def _read_kaku_setup_state() -> dict[str, object]:
    config_path = Path.home() / ".config/kaku/assistant.toml"
    state: dict[str, object] = {
        "config_path": config_path,
        "config_exists": config_path.exists(),
        "enabled": False,
        "model": "",
        "base_url": "",
        "proxy_configured": False,
    }
    if not config_path.exists():
        return state

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base_url = str(payload.get("base_url") or "")
    state["enabled"] = bool(payload.get("enabled", False))
    state["model"] = str(payload.get("model") or "")
    state["base_url"] = base_url
    state["proxy_configured"] = _is_local_proxy_url(base_url)
    return state


def _read_augment_setup_state() -> dict[str, object]:
    settings_path = Path.home() / "Library/Application Support/Code/User/settings.json"
    capture_path = default_augment_capture_path()
    patch_status = inspect_augment_patch(capture_path=capture_path)
    capture_events = 0
    capture_bytes = 0
    if capture_path.exists():
        try:
            capture_bytes = capture_path.stat().st_size
            with capture_path.open("r", encoding="utf-8") as handle:
                capture_events = sum(1 for line in handle if line.strip())
        except OSError:
            capture_events = 0
            capture_bytes = 0

    default_oauth_url = "https://auth.augmentcode.com"
    state: dict[str, object] = {
        "settings_path": str(settings_path),
        "settings_exists": settings_path.exists(),
        "capture_patch_installed": patch_status.patched,
        "capture_backup_exists": patch_status.backup_exists,
        "capture_file": str(capture_path),
        "capture_file_exists": capture_path.exists(),
        "capture_events": capture_events,
        "capture_bytes": capture_bytes,
        "api_token_configured": False,
        "completion_url": "",
        "chat_url": "",
        "next_edit_url": "",
        "smart_paste_url": "",
        "oauth_url": default_oauth_url,
        "use_oauth": True,
        "proxy_exact_possible": False,
        "assessment": _augment_runtime_assessment(patch_status.patched, capture_path.exists(), capture_events),
    }
    if not settings_path.exists():
        return state

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        state["assessment"] = f"Failed to parse VS Code settings.json: {exc}"
        return state

    if not isinstance(payload, dict):
        state["assessment"] = "VS Code settings.json is not a JSON object."
        return state

    advanced = payload.get("augment.advanced")
    if not isinstance(advanced, dict):
        state["proxy_assessment"] = (
            "No augment.advanced overrides are configured in VS Code settings. "
            "Runtime behavior will use the default OAuth tenant route."
        )
        return state

    api_token = str(advanced.get("apiToken") or "").strip()
    completion_url = str(advanced.get("completionURL") or "").strip()
    oauth = advanced.get("oauth")
    chat = advanced.get("chat")
    next_edit = advanced.get("nextEdit")
    smart_paste = advanced.get("smartPaste")

    oauth_url = str(oauth.get("url") or "").strip() if isinstance(oauth, dict) else ""
    chat_url = str(chat.get("url") or "").strip() if isinstance(chat, dict) else ""
    next_edit_url = str(next_edit.get("url") or "").strip() if isinstance(next_edit, dict) else ""
    smart_paste_url = str(smart_paste.get("url") or "").strip() if isinstance(smart_paste, dict) else ""

    use_oauth = not bool(api_token or completion_url)
    has_hidden_overrides = any((chat_url, next_edit_url, smart_paste_url))
    proxy_exact_possible = bool(api_token and completion_url)

    if proxy_exact_possible and has_hidden_overrides:
        proxy_assessment = (
            "Augment is in API-token mode with custom URLs configured. Proxy-based exact tracking looks feasible."
        )
    elif proxy_exact_possible:
        proxy_assessment = (
            "Augment is in API-token mode with completionURL configured. Chat/Next Edit/Smart Paste may still need "
            "hidden URL overrides for full exact coverage."
        )
    elif use_oauth:
        proxy_assessment = (
            "Augment currently uses OAuth tenant routing. Local exact tracking is unavailable; switching to API-token "
            "mode would be required for proxy-based exact capture."
        )
    else:
        proxy_assessment = (
            "Augment is not configured for API-token mode yet. A proxy path may exist if you set "
            "augment.advanced.apiToken and augment.advanced.completionURL manually in VS Code settings."
        )

    state.update(
        {
            "api_token_configured": bool(api_token),
            "completion_url": completion_url,
            "chat_url": chat_url,
            "next_edit_url": next_edit_url,
            "smart_paste_url": smart_paste_url,
            "oauth_url": oauth_url,
            "use_oauth": use_oauth,
            "proxy_exact_possible": proxy_exact_possible,
            "proxy_assessment": proxy_assessment,
        }
    )
    return state


def _augment_runtime_assessment(patched: bool, capture_exists: bool, capture_events: int) -> str:
    if patched and capture_exists and capture_events > 0:
        return "Runtime capture hook is installed and local Augment usage events are present. Run `tok scan augment` to ingest exact usage."
    if patched:
        return "Runtime capture hook is installed. Restart VS Code if needed, use Augment once, then run `tok scan augment`."
    return (
        "Augment can now be estimated from persisted local request context and checkpoint diffs. "
        "Run `tok scan augment` for historical estimates, or `tok augment install` to start exact runtime capture "
        "for new requests."
    )


def _is_local_proxy_url(url: str) -> bool:
    normalized = url.strip().lower()
    return normalized.startswith("http://127.0.0.1:8765") or normalized.startswith("http://localhost:8765")


def _infer_kaku_upstream_base_url(kaku_state: dict[str, object]) -> str | None:
    base_url = str(kaku_state.get("base_url") or "")
    if base_url and not _is_local_proxy_url(base_url):
        return base_url

    launchd_env = _read_launchd_env("com.laoyao.tokkit.kaku-proxy")
    upstream = launchd_env.get("TOKKIT_KAKU_UPSTREAM_BASE_URL")
    if upstream:
        return upstream
    return None


def _configure_kaku_proxy(config_path: Path) -> str:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(
            "\n".join(
                [
                    "# Kaku Assistant configuration",
                    "enabled = true",
                    'model = "gpt-5.4"',
                    'base_url = "http://127.0.0.1:8765"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return f"Wrote {config_path} with TokKit proxy base_url."

    original = config_path.read_text(encoding="utf-8")
    if re.search(r'(?m)^\s*base_url\s*=\s*"http://127\.0\.0\.1:8765"\s*$', original):
        return f"Kaku already points to the TokKit proxy in {config_path}."

    if re.search(r"(?m)^\s*base_url\s*=", original):
        updated = re.sub(
            r'(?m)^(\s*base_url\s*=\s*).*$',
            r'\1"http://127.0.0.1:8765"',
            original,
            count=1,
        )
    else:
        suffix = "" if original.endswith("\n") else "\n"
        updated = original + suffix + 'base_url = "http://127.0.0.1:8765"\n'
    config_path.write_text(updated, encoding="utf-8")
    return f"Updated Kaku base_url to the TokKit proxy in {config_path}."


def _migrate_home_directory() -> str:
    modern = Path.home() / ".tokkit"
    legacy = Path.home() / ".tokstat"

    if modern.exists():
        if legacy.is_symlink() and legacy.resolve() == modern.resolve():
            return "TokKit home is already migrated to ~/.tokkit."
        return "TokKit home already uses ~/.tokkit."

    if not legacy.exists():
        modern.mkdir(parents=True, exist_ok=True)
        return "Created new TokKit home at ~/.tokkit."

    legacy.rename(modern)
    legacy.symlink_to(modern)
    return "Moved ~/.tokstat to ~/.tokkit and kept ~/.tokstat as a compatibility symlink."


def _install_launchd_jobs(*, scan_mode: str, install_kaku_proxy: bool, kaku_upstream_base_url: str | None) -> str:
    script_path = Path(__file__).resolve().parents[2] / "scripts/install_launchd.sh"
    if not script_path.exists():
        raise RuntimeError(f"Launchd installer not found: {script_path}")

    if install_kaku_proxy and not kaku_upstream_base_url:
        raise RuntimeError("Kaku proxy install requires --kaku-upstream-base-url or an existing upstream URL.")

    env = dict(os.environ)
    env.setdefault("TOKKIT_HOME", str(resolve_app_home()))
    env.setdefault("TOKKIT_DB_PATH", str(default_db_path()))
    env.setdefault("TOKKIT_REPORT_DIR", str(default_report_dir()))
    env.setdefault("TOKKIT_LOG_DIR", str(default_log_dir()))
    env["TOKKIT_TIMEZONE"] = env.get("TOKKIT_TIMEZONE") or "Asia/Shanghai"
    env["TOKKIT_SCAN_MODE"] = scan_mode
    env["TOKKIT_INSTALL_KAKU_PROXY"] = "1" if install_kaku_proxy else "0"
    if kaku_upstream_base_url:
        env["TOKKIT_KAKU_UPSTREAM_BASE_URL"] = kaku_upstream_base_url

    completed = subprocess.run(
        [str(script_path)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip()
        raise RuntimeError(output or "install_launchd.sh failed")

    label = "Installed TokKit launchd automation"
    if install_kaku_proxy:
        label += " with the Kaku proxy."
    else:
        label += "."
    return label


def _build_setup_recommendations(
    *,
    app_home: Path,
    launchd_status: dict[str, list[str]],
    kaku_state: dict[str, object],
    scan_mode: str,
    pricing_override_exists: bool,
    proxy_upstream: str,
) -> list[str]:
    recommendations: list[str] = []

    if app_home.name == ".tokstat":
        recommendations.append("Run `tok setup --migrate-home` to move your data directory to `~/.tokkit`.")

    if not launchd_status["tokkit_labels"]:
        recommendations.append("Run `tok setup --install-launchd --scan-mode codex` to enable hourly scans and daily reports.")
    elif scan_mode:
        recommendations.append(f"Automatic scans are installed and currently use scan mode `{scan_mode}`.")

    if kaku_state["config_exists"] and not kaku_state["proxy_configured"]:
        base_url = str(kaku_state["base_url"] or "")
        if base_url:
            recommendations.append(
                "Run `tok setup --enable-kaku-proxy --install-launchd "
                f"--kaku-upstream-base-url {base_url}` to route Kaku through the local TokKit proxy."
            )
        else:
            recommendations.append("Run `tok setup --enable-kaku-proxy` to point Kaku at the local TokKit proxy.")
    elif kaku_state["proxy_configured"] and not proxy_upstream:
        recommendations.append("TokKit can see Kaku pointing at the local proxy, but the proxy upstream is unknown. Reinstall launchd with `tok setup --install-launchd --kaku-upstream-base-url <url>`.")

    if not pricing_override_exists:
        recommendations.append("Optional: create `~/.tokkit/pricing.json` if you want local pricing overrides for `Est.$`.")

    return recommendations


def _render_augment_patch_status(status, *, json_mode: bool, action: str | None = None) -> str:
    payload = asdict(status)
    if action:
        payload["action"] = action
    if json_mode:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = ["TokKit Augment capture", ""]
    if action == "installed":
        lines.append("Installed the Augment runtime capture hook. Restart VS Code to load the patched extension.")
        lines.append("")
    elif action == "removed":
        lines.append("Removed the Augment runtime capture hook. Restart VS Code to restore the original extension bundle.")
        lines.append("")

    lines.append(
        _render_table(
            headers=["Item", "Value"],
            rows=[
                ["Installed versions", ", ".join(status.installed_versions) or "-"],
                ["Selected extension", status.extension_dir or "-"],
                ["Extension bundle", status.extension_js or "-"],
                ["Backup bundle", status.backup_path or "-"],
                ["Extension exists", "yes" if status.extension_exists else "no"],
                ["Capture hook installed", "yes" if status.patched else "no"],
                ["Backup exists", "yes" if status.backup_exists else "no"],
                ["Capture file", status.capture_path],
                ["Patch version", status.patch_version],
            ],
        )
    )
    if action == "installed":
        lines.extend(
            [
                "",
                "Next steps:",
                "1. Restart Visual Studio Code.",
                "2. Use Augment once.",
                "3. Run `tok scan augment` or any report command.",
            ]
        )
    return "\n".join(lines)


def _shift_date(raw_date: str, days: int) -> str:
    from datetime import date

    return (date.fromisoformat(raw_date) + timedelta(days=days)).isoformat()


def _month_start(raw_date: str) -> str:
    from datetime import date

    value = date.fromisoformat(raw_date)
    return value.replace(day=1).isoformat()


def _ratio(value: float | None, budget: float | None) -> float | None:
    if value is None or budget is None or budget <= 0:
        return None
    return value / budget


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _budget_status(est_pct: float | None, credits_pct: float | None) -> str:
    ratios = [ratio for ratio in (est_pct, credits_pct) if ratio is not None]
    if not ratios:
        return "track"
    highest = max(ratios)
    if highest > 1.0:
        return "over"
    if highest >= 0.8:
        return "watch"
    return "ok"


def _doctor_notes_for_client(
    row: dict[str, object],
    *,
    augment_state: dict[str, object] | None = None,
    chatgpt_export_path: Path | None = None,
    copilot_export_path: Path | None = None,
) -> str:
    client = str(row.get("client") or row.get("label") or "")
    notes = str(row.get("notes") or "")
    if client == "ChatGPT" and chatgpt_export_path is not None:
        return f"{notes} Latest export candidate: {chatgpt_export_path}".strip()
    if client == "GitHub Copilot" and copilot_export_path is not None:
        return f"{notes} Latest export candidate: {copilot_export_path}".strip()
    if client != "Augment" or not augment_state:
        return notes
    parts = [
        str(augment_state.get("assessment") or "").strip(),
        str(augment_state.get("proxy_assessment") or "").strip(),
    ]
    details = " ".join(part for part in parts if part)
    if not details:
        return notes
    return f"{notes} {details}".strip()


def _doctor_action_for_client(
    row: dict[str, object],
    *,
    augment_state: dict[str, object] | None = None,
    chatgpt_export_path: Path | None = None,
) -> str:
    installed = bool(row["installed"])
    records = int(row["records"])
    client = str(row.get("client") or row.get("label") or "")

    if not installed:
        return "-"
    if records > 0:
        return "working"
    if client == "Kaku":
        return "point Kaku to the TokKit proxy, then retry"
    if client == "Warp":
        return "run `tok scan warp`"
    if client == "Claude Code":
        return "run `tok scan claude-code`"
    if client == "Augment":
        if augment_state and bool(augment_state.get("capture_patch_installed")):
            if int(augment_state.get("capture_events") or 0) > 0:
                return "run `tok scan augment`"
            return "restart VS Code, use Augment once, then run `tok scan augment`"
        if augment_state and bool(augment_state.get("proxy_exact_possible")):
            if any(
                str(augment_state.get(key) or "").strip()
                for key in ("chat_url", "next_edit_url", "smart_paste_url")
            ):
                return "experimental: point Augment URLs to a local proxy, then build an Augment ingester"
            return "experimental: completionURL is configured, but chat/nextEdit URLs may still need proxy overrides"
        return "run `tok augment install`"
    if client == "CodeBuddy":
        return "run `tok scan codebuddy`"
    if client == "Codex":
        return "run `tok scan codex`"
    if client == "Visual Studio Code":
        return "use the Codex extension or verify codex:vscode usage"
    if client == "ChatGPT":
        if chatgpt_export_path is not None:
            return "run `tok scan chatgpt`"
        return "export your ChatGPT data, then run `tok scan chatgpt`"
    if client == "GitHub Copilot":
        return "run `tok scan copilot --org <org>` or scan a downloaded usage metrics export"
    if client == "Cursor":
        return "run `tok scan cursor`"
    if client == "Trae":
        return "run `tok scan trae`"
    return "scan or configure this client"


def _aggregate_hourly_usage_rows(conn: sqlite3.Connection, target_date: str, tz) -> list[dict[str, object]]:
    raw_rows = _enrich_usage_rows(
        conn.execute(
            """
            SELECT
                started_at,
                app,
                source,
                measurement_method,
                COALESCE(model, '') AS model,
                COALESCE(json_extract(metadata_json, '$.model_provider'), '') AS model_provider,
                input_tokens,
                output_tokens,
                cached_input_tokens,
                reasoning_tokens,
                COALESCE(total_tokens, 0) AS total_tokens,
                COALESCE(credits, 0.0) AS credits,
                1 AS records
            FROM usage_records
            WHERE local_date = ?
            ORDER BY started_at ASC
            """,
            (target_date,),
        ).fetchall()
    )
    for row in raw_rows:
        row["hour_label"] = parse_timestamp(str(row["started_at"])).astimezone(tz).strftime("%H:00")
    return _aggregate_usage_rows(
        raw_rows,
        key_fields=["hour_label"],
        key_builder=lambda row: (row["hour_label"],),
        sort_key=lambda row: (str(row["hour_label"]),),
    )


def _aggregate_usage_rows(
    rows: Iterable[sqlite3.Row | dict[str, object]],
    *,
    key_fields: list[str],
    key_builder,
    sort_key,
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, ...], dict[str, object]] = {}
    for row in rows:
        key_values = tuple(str(value) for value in key_builder(row))
        bucket = grouped.setdefault(
            key_values,
            {
                **{field: key_values[idx] for idx, field in enumerate(key_fields)},
                "methods": set(),
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "credits": 0.0,
                "records": 0,
                "estimated_cost_usd": 0.0,
                "estimated_cost_present": False,
                "input_present": False,
                "output_present": False,
                "cached_present": False,
                "reasoning_present": False,
            },
        )
        bucket["methods"].add(str(row["measurement_method"]))
        if row["input_tokens"] is not None:
            bucket["input_tokens"] = int(bucket["input_tokens"]) + int(row["input_tokens"])
            bucket["input_present"] = True
        if row["output_tokens"] is not None:
            bucket["output_tokens"] = int(bucket["output_tokens"]) + int(row["output_tokens"])
            bucket["output_present"] = True
        if row["cached_input_tokens"] is not None:
            bucket["cached_input_tokens"] = int(bucket["cached_input_tokens"]) + int(row["cached_input_tokens"])
            bucket["cached_present"] = True
        if row["reasoning_tokens"] is not None:
            bucket["reasoning_tokens"] = int(bucket["reasoning_tokens"]) + int(row["reasoning_tokens"])
            bucket["reasoning_present"] = True
        bucket["total_tokens"] = int(bucket["total_tokens"]) + int(row["total_tokens"])
        bucket["credits"] = float(bucket["credits"]) + float(row["credits"])
        bucket["records"] = int(bucket["records"]) + int(row["records"])
        estimated_cost = row.get("estimated_cost_usd") if isinstance(row, dict) else None
        if estimated_cost is not None:
            bucket["estimated_cost_usd"] = float(bucket["estimated_cost_usd"]) + float(estimated_cost)
            bucket["estimated_cost_present"] = True

    aggregated = list(grouped.values())
    for row in aggregated:
        row["method"] = _format_measurement_methods(row.pop("methods"))
        row["credits"] = round(float(row["credits"]), 8)
        estimated_cost_present = bool(row.pop("estimated_cost_present"))
        input_present = bool(row.pop("input_present"))
        output_present = bool(row.pop("output_present"))
        cached_present = bool(row.pop("cached_present"))
        reasoning_present = bool(row.pop("reasoning_present"))
        if not input_present:
            row["input_tokens"] = None
        if not output_present:
            row["output_tokens"] = None
        if not cached_present:
            row["cached_input_tokens"] = None
        if not reasoning_present:
            row["reasoning_tokens"] = None
        if estimated_cost_present:
            row["estimated_cost_usd"] = round(float(row["estimated_cost_usd"]), 8)
        else:
            row["estimated_cost_usd"] = None
    aggregated.sort(key=sort_key)
    return aggregated


def _format_measurement_methods(methods: set[str]) -> str:
    method_order = {"exact": 0, "partial": 1, "estimated": 2}
    return "+".join(sorted(methods, key=lambda method: (method_order.get(method, 99), method)))


def _terminal_label(app: str | None, source: str | None, originator: str | None = None) -> str:
    source_value = (source or "").strip().lower()
    app_value = (app or "").strip()
    if app_value.lower() == "codex" and source_value == "codex:vscode":
        if is_codex_desktop_originator(originator):
            return "Codex Desktop"
        return "VS Code"
    if "vscode" in source_value:
        return "VS Code"
    if source_value.endswith(":cli") or source_value == "cli":
        return "CLI"
    if source_value.startswith("warp") or source_value == "warp":
        return "Warp"
    if source_value.startswith("kaku") or app_value.lower() == "kaku":
        return "Kaku"
    if source_value.startswith("codebuddy") or app_value.lower() == "codebuddy":
        return "CodeBuddy"
    if source_value.startswith("chatgpt") or app_value.lower() == "chatgpt":
        return "ChatGPT"
    if app_value:
        return app_value
    if source:
        return source
    return "unknown"


def _model_label(model: str | None, provider: str | None) -> str:
    return normalize_model_display(model, provider)


def _enrich_usage_rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, object]]:
    pricing_resolution = resolve_price_book()
    enriched: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["model_label"] = _model_label(item.get("model"), item.get("model_provider"))
        item["estimated_cost_usd"] = estimate_cost_usd(
            model=item.get("model"),
            provider=item.get("model_provider"),
            measurement_method=str(item.get("measurement_method") or ""),
            input_tokens=int(item.get("input_tokens") or 0),
            cached_input_tokens=int(item.get("cached_input_tokens") or 0),
            output_tokens=int(item.get("output_tokens") or 0),
            pricing_resolution=pricing_resolution,
        )
        enriched.append(item)
    return enriched


def _sum_estimated_cost(rows: Iterable[dict[str, object]]) -> float | None:
    total = 0.0
    present = False
    for row in rows:
        value = row.get("estimated_cost_usd")
        if value is None:
            continue
        total += float(value)
        present = True
    if not present:
        return None
    return round(total, 8)


def _render_table(
    *,
    headers: list[str],
    rows: Iterable[list[str]],
    right_align: set[int] | None = None,
) -> str:
    rendered_rows = [list(map(str, row)) for row in rows]
    widths = [len(header) for header in headers]
    for row in rendered_rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    right_align = right_align or set()

    def format_row(values: list[str]) -> str:
        cells = []
        for idx, value in enumerate(values):
            if idx in right_align:
                cells.append(value.rjust(widths[idx]))
            else:
                cells.append(value.ljust(widths[idx]))
        return "| " + " | ".join(cells) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    parts = [separator, format_row(headers), separator]
    for row in rendered_rows:
        parts.append(format_row(row))
    parts.append(separator)
    return "\n".join(parts)


def _render_trend_chart(
    rows: Iterable[sqlite3.Row | dict[str, object]],
    *,
    label_field: str,
    value_field: str,
    width: int = 24,
) -> str:
    chart_rows = [row for row in rows]
    if not chart_rows:
        return "(no records)"

    max_value = max(int(row[value_field]) for row in chart_rows)
    if max_value <= 0:
        return "(no records)"

    rendered: list[str] = []
    for row in reversed(chart_rows):
        label = str(row[label_field])
        value = int(row[value_field])
        bar_length = max(1, round((value / max_value) * width)) if value > 0 else 0
        bar = "#" * bar_length
        rendered.append(f"{label} | {bar.ljust(width)} {format_int(value)}")
    return "\n".join(rendered)


def _resolve_date_alias(raw: str, tz) -> str:
    if raw == "today":
        return today_string(tz)
    if raw == "yesterday":
        from datetime import datetime

        return (datetime.now(tz).date() - timedelta(days=1)).isoformat()
    return raw


def _emit_rendered(rendered: str, output_path: Path | None) -> None:
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote report to {output_path}")
        return
    print(rendered)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
