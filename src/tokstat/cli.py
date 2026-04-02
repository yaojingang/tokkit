from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path
from typing import Iterable

from .clients import CLIENT_DEFINITIONS, detect_installed_clients, logical_client_for_usage_row
from .db import connect_db
from .ingest_codebuddy import scan_codebuddy
from .ingest_codex import scan_codex
from .ingest_warp import scan_warp
from .proxy import ProxyConfig, serve_proxy
from .utils import DEFAULT_DB_PATH, format_float, format_int, get_timezone, today_string


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

    codebuddy_cmd = subparsers.add_parser("scan-codebuddy", help="Estimate CodeBuddy usage from local task history.")
    codebuddy_cmd.add_argument(
        "--codebuddy-tasks-root",
        type=Path,
        default=Path.home() / "Library/Application Support/CodeBuddy/User/globalStorage/tencent.planning-genie/tasks",
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
    all_cmd.add_argument(
        "--codebuddy-tasks-root",
        type=Path,
        default=Path.home() / "Library/Application Support/CodeBuddy/User/globalStorage/tencent.planning-genie/tasks",
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

    conn = connect_db(args.db)
    try:
        if args.command == "scan-codex":
            stats = scan_codex(conn, codex_home=args.codex_home, tz=tz)
            print(f"codex scan complete: files={stats.files_scanned} token_events={stats.records_seen}")
            return 0

        if args.command == "scan-codebuddy":
            stats = scan_codebuddy(conn, tasks_root=args.codebuddy_tasks_root, tz=tz)
            print(
                "codebuddy scan complete: "
                f"tasks={stats.tasks_seen} emitted={stats.records_emitted}"
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
            codebuddy_stats = scan_codebuddy(conn, tasks_root=args.codebuddy_tasks_root, tz=tz)
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
                f"codebuddy_tasks={codebuddy_stats.tasks_seen} "
                f"codebuddy_emitted={codebuddy_stats.records_emitted} "
                f"warp_conversations={warp_stats.conversations_seen} "
                f"warp_emitted={warp_stats.records_emitted}"
            )
            return 0

        if args.command == "report-daily":
            target_date = _resolve_date_alias(args.date, tz)
            rendered = render_daily_report(conn, target_date, json_mode=args.json)
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

        parser.error(f"unsupported command: {args.command}")
    finally:
        conn.close()
    return 1


def render_daily_report(conn: sqlite3.Connection, target_date: str, *, json_mode: bool) -> str:
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records
        FROM usage_records
        WHERE local_date = ?
        """,
        (target_date,),
    ).fetchone()
    detailed_rows = conn.execute(
        """
        SELECT
            app,
            source,
            measurement_method,
            COALESCE(model, '') AS model,
            COALESCE(json_extract(metadata_json, '$.model_provider'), '') AS model_provider,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records
        FROM usage_records
        WHERE local_date = ?
        GROUP BY app, source, measurement_method, model, model_provider
        ORDER BY total_tokens DESC, credits DESC, app, source, model, model_provider, measurement_method
        """,
        (target_date,),
    ).fetchall()
    by_terminal = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["terminal"],
        key_builder=lambda row: (_terminal_label(row["app"], row["source"]),),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["terminal"])),
    )
    by_model = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["model_label"],
        key_builder=lambda row: (_model_label(row["model"], row["model_provider"]),),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["model_label"])),
    )
    by_source = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["app", "source"],
        key_builder=lambda row: (row["app"], row["source"]),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["app"]), str(row["source"])),
    )

    if json_mode:
        payload = {
            "date": target_date,
            "totals": dict(totals),
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
            f"credits={format_float(totals['credits'])} "
            f"records={totals['records']}"
        ),
        "",
        "By terminal:",
    ]
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
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_terminal
                ],
                right_align={2, 3, 4, 5, 6, 7, 8},
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
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_model
                ],
                right_align={2, 3, 4, 5, 6, 7, 8},
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
                    "Method",
                    "Total",
                    "Input",
                    "Output",
                    "Cached",
                    "Reasoning",
                    "Credits",
                    "Records",
                ],
                rows=[
                    [
                        row["app"],
                        row["source"],
                        row["method"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_source
                ],
                right_align={3, 4, 5, 6, 7, 8, 9},
            )
        )
    return "\n".join(lines)


def render_range_report(conn: sqlite3.Connection, last_days: int, tz, *, json_mode: bool) -> str:
    end_date = today_string(tz)
    by_date_rows = conn.execute(
        """
        SELECT
            local_date,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records
        FROM usage_records
        WHERE local_date >= date(?, ?)
        GROUP BY local_date
        ORDER BY local_date DESC
        """,
        (end_date, f"-{max(last_days - 1, 0)} day"),
    ).fetchall()

    detailed_rows = conn.execute(
        """
        SELECT
            local_date,
            app,
            source,
            measurement_method,
            COALESCE(model, '') AS model,
            COALESCE(json_extract(metadata_json, '$.model_provider'), '') AS model_provider,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records
        FROM usage_records
        WHERE local_date >= date(?, ?)
        GROUP BY local_date, app, source, measurement_method, model, model_provider
        ORDER BY local_date DESC, total_tokens DESC, app, source, model, model_provider, measurement_method
        """,
        (end_date, f"-{max(last_days - 1, 0)} day"),
    ).fetchall()
    by_terminal = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["terminal"],
        key_builder=lambda row: (_terminal_label(row["app"], row["source"]),),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["terminal"])),
    )
    by_model = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["model_label"],
        key_builder=lambda row: (_model_label(row["model"], row["model_provider"]),),
        sort_key=lambda row: (-int(row["total_tokens"]), -float(row["credits"]), str(row["model_label"])),
    )
    rows = _aggregate_usage_rows(
        detailed_rows,
        key_fields=["local_date", "app", "source"],
        key_builder=lambda row: (row["local_date"], row["app"], row["source"]),
        sort_key=lambda row: (
            -int(str(row["local_date"]).replace("-", "")),
            -int(row["total_tokens"]),
            str(row["app"]),
            str(row["source"]),
        ),
    )
    if json_mode:
        return json.dumps(
            {
                "range_days": last_days,
                "by_date": [dict(row) for row in by_date_rows],
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
                headers=["Date", "Total", "Input", "Output", "Cached", "Reasoning", "Credits", "Records"],
                rows=[
                    [
                        row["local_date"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_date_rows
                ],
                right_align={1, 2, 3, 4, 5, 6, 7},
            ),
            "",
            "By terminal:",
            _render_table(
                headers=["Terminal", "Method", "Total", "Input", "Output", "Cached", "Reasoning", "Credits", "Records"],
                rows=[
                    [
                        row["terminal"],
                        row["method"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_terminal
                ],
                right_align={2, 3, 4, 5, 6, 7, 8},
            ),
            "",
            "By model:",
            _render_table(
                headers=["Model", "Method", "Total", "Input", "Output", "Cached", "Reasoning", "Credits", "Records"],
                rows=[
                    [
                        row["model_label"],
                        row["method"],
                        format_int(row["total_tokens"]),
                        format_int(row["input_tokens"]),
                        format_int(row["output_tokens"]),
                        format_int(row["cached_input_tokens"]),
                        format_int(row["reasoning_tokens"]),
                        format_float(row["credits"]),
                        str(row["records"]),
                    ]
                    for row in by_model
                ],
                right_align={2, 3, 4, 5, 6, 7, 8},
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
                "Method",
                "Total",
                "Input",
                "Output",
                "Cached",
                "Reasoning",
                "Credits",
                "Records",
            ],
            rows=[
                [
                    row["local_date"],
                    row["app"],
                    row["source"],
                    row["method"],
                    format_int(row["total_tokens"]),
                    format_int(row["input_tokens"]),
                    format_int(row["output_tokens"]),
                    format_int(row["cached_input_tokens"]),
                    format_int(row["reasoning_tokens"]),
                    format_float(row["credits"]),
                    str(row["records"]),
                ]
                for row in rows
            ],
            right_align={4, 5, 6, 7, 8, 9, 10},
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
            measurement_method,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(credits), 0.0) AS credits,
            COUNT(*) AS records,
            MAX(started_at) AS last_seen
        FROM usage_records
        WHERE {query_sql}
        GROUP BY app, source, measurement_method
        ORDER BY total_tokens DESC, credits DESC, app, source
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
        client_key = logical_client_for_usage_row(row["app"], row["source"])
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


def _aggregate_usage_rows(
    rows: Iterable[sqlite3.Row],
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
            },
        )
        bucket["methods"].add(str(row["measurement_method"]))
        bucket["input_tokens"] = int(bucket["input_tokens"]) + int(row["input_tokens"])
        bucket["output_tokens"] = int(bucket["output_tokens"]) + int(row["output_tokens"])
        bucket["cached_input_tokens"] = int(bucket["cached_input_tokens"]) + int(row["cached_input_tokens"])
        bucket["reasoning_tokens"] = int(bucket["reasoning_tokens"]) + int(row["reasoning_tokens"])
        bucket["total_tokens"] = int(bucket["total_tokens"]) + int(row["total_tokens"])
        bucket["credits"] = float(bucket["credits"]) + float(row["credits"])
        bucket["records"] = int(bucket["records"]) + int(row["records"])

    aggregated = list(grouped.values())
    for row in aggregated:
        row["method"] = _format_measurement_methods(row.pop("methods"))
        row["credits"] = round(float(row["credits"]), 8)
    aggregated.sort(key=sort_key)
    return aggregated


def _format_measurement_methods(methods: set[str]) -> str:
    method_order = {"exact": 0, "partial": 1, "estimated": 2}
    return "+".join(sorted(methods, key=lambda method: (method_order.get(method, 99), method)))


def _terminal_label(app: str | None, source: str | None) -> str:
    source_value = (source or "").strip().lower()
    app_value = (app or "").strip()
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
    model_value = (model or "").strip()
    provider_value = (provider or "").strip()
    if model_value:
        return model_value
    if provider_value:
        return f"unknown (provider={provider_value})"
    return "unknown"


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
