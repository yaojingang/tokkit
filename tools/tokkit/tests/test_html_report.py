from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokkit.cli import render_html_report
from tokkit.db import UsageRecord, init_db, upsert_usage_record
from tokkit.tok import _refresh_daily_html_report_if_needed, _run_html_command, _run_scan_command


class HtmlReportTests(unittest.TestCase):
    def test_html_report_renders_static_charts_and_tables(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        tz = ZoneInfo("Asia/Shanghai")
        for day, total in (("2026-05-02", 1000), ("2026-05-03", 2500)):
            upsert_usage_record(
                conn,
                UsageRecord(
                    source="codex:vscode",
                    app="codex",
                    external_id=f"{day}:record",
                    started_at=f"{day}T10:00:00+08:00",
                    local_date=day,
                    model="gpt-5.5",
                    input_tokens=total - 100,
                    output_tokens=100,
                    cached_input_tokens=total // 2,
                    reasoning_tokens=10,
                    total_tokens=total,
                    metadata={"originator": "Codex Desktop", "model_provider": "openai"},
                ),
            )
        conn.commit()

        rendered = render_html_report(conn, 7, tz)

        self.assertIn("<!doctype html>", rendered)
        self.assertIn('lang="zh-CN"', rendered)
        self.assertIn("每日 Token 趋势", rendered)
        self.assertIn("终端占比", rendered)
        self.assertIn("模型消耗排行", rendered)
        self.assertIn("每日明细", rendered)
        self.assertIn('class="topbar"', rendered)
        self.assertIn('data-range="7"', rendered)
        self.assertIn('data-range="30"', rendered)
        self.assertIn("重新扫描", rendered)
        self.assertIn('id="languageToggle"', rendered)
        self.assertIn("tokkit.report.language", rendered)
        self.assertIn("TokKit Usage Report - Last {days} Days", rendered)
        self.assertIn("Daily Token Trend", rendered)
        self.assertIn("function applyLanguage", rendered)
        self.assertIn('id="chartTooltip"', rendered)
        self.assertIn("data-tooltip", rendered)
        self.assertIn("function showChartTooltip", rendered)
        self.assertIn("function tooltipAttr", rendered)
        self.assertIn("function renderDashboard", rendered)
        self.assertIn("function lineChart", rendered)
        self.assertIn("--module-gap: 16px", rendered)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", rendered)
        self.assertIn(".chart-grid > .panel", rendered)
        self.assertNotIn("0.9fr", rendered)
        self.assertNotIn("1.1fr", rendered)
        self.assertIn("Codex Desktop", rendered)
        self.assertIn("GPT-5.5", rendered)

    def test_tok_html_command_maps_common_windows(self) -> None:
        with patch("tokkit.tok._run_report", return_value=0) as run_report:
            status = _run_html_command(["week"])

        self.assertEqual(status, 0)
        run_report.assert_called_once_with(["report-html", "--last", "7"])

        with patch("tokkit.tok._run_report", return_value=0) as run_report:
            status = _run_html_command(["last", "14", "--output", "/tmp/report.html"])

        self.assertEqual(status, 0)
        run_report.assert_called_once_with(["report-html", "--output", "/tmp/report.html", "--last", "14"])

    def test_daily_html_report_generates_once_without_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            expected_path = report_dir / "tokkit-last-14-2026-05-03.html"
            calls: list[list[str]] = []

            def fake_run(command, **kwargs):
                calls.append(command)
                stdout = kwargs["stdout"]
                stdout.write("wrote HTML report to hidden path\n")
                expected_path.write_text("<!doctype html>", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            with (
                patch.dict(os.environ, {"TOK_AUTO_HTML_REPORT": "1", "TOK_AUTO_HTML_LAST_DAYS": "14"}),
                patch("tokkit.tok._report_dir", return_value=report_dir),
                patch("tokkit.tok._auto_html_today_string", return_value="2026-05-03"),
                patch("tokkit.tok.subprocess.run", side_effect=fake_run),
            ):
                first_status = _refresh_daily_html_report_if_needed()
                second_status = _refresh_daily_html_report_if_needed()

        self.assertEqual(first_status, 0)
        self.assertEqual(second_status, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("report-html", calls[0])
        self.assertIn("--last", calls[0])
        self.assertIn("14", calls[0])
        self.assertIn("--output", calls[0])
        self.assertIn(str(expected_path), calls[0])

    def test_daily_html_report_can_be_disabled(self) -> None:
        with patch.dict(os.environ, {"TOK_AUTO_HTML_REPORT": "0"}):
            with patch("tokkit.tok.subprocess.run") as run:
                status = _refresh_daily_html_report_if_needed()

        self.assertEqual(status, 0)
        run.assert_not_called()

    def test_manual_scan_refreshes_daily_html_after_success(self) -> None:
        with (
            patch("tokkit.tok._run_tokkit", return_value=0) as run_tokkit,
            patch("tokkit.tok._refresh_daily_html_report_if_needed", return_value=0) as refresh,
        ):
            status = _run_scan_command(["codex"])

        self.assertEqual(status, 0)
        run_tokkit.assert_called_once_with(["scan-codex"])
        refresh.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
