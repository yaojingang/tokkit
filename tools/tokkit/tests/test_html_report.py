from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokkit.cli import render_html_report
from tokkit.db import UsageRecord, init_db, upsert_usage_record
from tokkit.tok import _run_html_command


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
        self.assertIn("function renderDashboard", rendered)
        self.assertIn("function lineChart", rendered)
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


if __name__ == "__main__":
    unittest.main()
