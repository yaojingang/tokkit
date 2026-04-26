from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokkit.cli import render_range_report
from tokkit.db import UsageRecord, init_db, upsert_usage_record


class ReportRenderingTests(unittest.TestCase):
    def test_range_report_source_uses_human_friendly_codex_desktop_label(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        upsert_usage_record(
            conn,
            UsageRecord(
                source="codex:vscode",
                app="codex",
                external_id="session-1:2026-04-26T01:00:00Z",
                started_at="2026-04-26T01:00:00Z",
                local_date="2026-04-26",
                model="gpt-5.5",
                input_tokens=1000,
                output_tokens=100,
                cached_input_tokens=500,
                reasoning_tokens=10,
                total_tokens=1110,
                metadata={"originator": "Codex Desktop", "model_provider": "openai"},
            ),
        )
        conn.commit()

        rendered = render_range_report(conn, 7, ZoneInfo("Asia/Shanghai"), json_mode=False)

        self.assertIn("Codex Desktop", rendered)
        self.assertNotIn("codex:vscode", rendered)

    def test_range_report_exposes_unsplit_tokens_for_total_only_codex_events(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        upsert_usage_record(
            conn,
            UsageRecord(
                source="codex:vscode",
                app="codex",
                external_id="session-2:2026-04-26T02:00:00Z",
                started_at="2026-04-26T02:00:00Z",
                local_date="2026-04-26",
                model="gpt-5.5",
                input_tokens=0,
                output_tokens=0,
                cached_input_tokens=0,
                reasoning_tokens=0,
                total_tokens=150702,
                metadata={"originator": "Codex Desktop", "model_provider": "openai"},
            ),
        )
        upsert_usage_record(
            conn,
            UsageRecord(
                source="codex:vscode",
                app="codex",
                external_id="session-2:2026-04-26T02:30:00Z",
                started_at="2026-04-26T02:30:00Z",
                local_date="2026-04-26",
                model="gpt-5.5",
                input_tokens=1000,
                output_tokens=100,
                cached_input_tokens=500,
                reasoning_tokens=10,
                total_tokens=1100,
                metadata={"originator": "Codex Desktop", "model_provider": "openai"},
            ),
        )
        conn.commit()

        rendered = render_range_report(conn, 7, ZoneInfo("Asia/Shanghai"), json_mode=False)
        payload = json.loads(render_range_report(conn, 7, ZoneInfo("Asia/Shanghai"), json_mode=True))

        self.assertIn("Unsplit", rendered)
        self.assertIn("150,702", rendered)
        self.assertEqual(payload["by_source"][0]["unsplit_tokens"], 150702)
        self.assertEqual(payload["by_source"][0]["input_tokens"], 1000)
        self.assertEqual(payload["by_source"][0]["output_tokens"], 100)
        self.assertEqual(payload["by_source"][0]["total_tokens"], 151802)
        self.assertEqual(payload["by_date"][0]["unsplit_tokens"], 150702)


if __name__ == "__main__":
    unittest.main()
