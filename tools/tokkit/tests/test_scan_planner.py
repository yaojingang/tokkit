from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokkit.db import UsageRecord, init_db, upsert_usage_record
from tokkit.scan_planner import ALL_SCAN_TARGETS, recent_active_targets, record_scan_plan_result, resolve_scan_plan
from tokkit.tok import _resolve_scan_target


class ScanPlannerTests(unittest.TestCase):
    def test_first_scan_runs_full_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = resolve_scan_plan(app_home=Path(tmp))

        self.assertTrue(plan.full_scan)
        self.assertEqual(plan.targets, ALL_SCAN_TARGETS)
        self.assertIn("Codex", plan.label)
        self.assertIn("Warp", plan.label)

    def test_followup_scan_reuses_global_active_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_home = Path(tmp)
            first_plan = resolve_scan_plan(session_key="terminal:a", app_home=app_home)
            record_scan_plan_result(
                first_plan,
                active_targets=["codex", "augment", "warp"],
                scanned_targets=first_plan.targets,
                app_home=app_home,
            )

            second_plan = resolve_scan_plan(session_key="terminal:b", app_home=app_home)

        self.assertFalse(second_plan.full_scan)
        self.assertEqual(second_plan.targets, ("codex", "augment", "warp"))
        self.assertEqual(second_plan.label, "Codex + Augment + Warp")

    def test_force_full_overrides_active_target_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_home = Path(tmp)
            first_plan = resolve_scan_plan(session_key="terminal:test", app_home=app_home)
            record_scan_plan_result(
                first_plan,
                active_targets=["codex", "claude-code"],
                scanned_targets=first_plan.targets,
                app_home=app_home,
            )

            second_plan = resolve_scan_plan(
                session_key="terminal:test",
                app_home=app_home,
                force_full=True,
            )

        self.assertTrue(second_plan.full_scan)
        self.assertEqual(second_plan.targets, ALL_SCAN_TARGETS)

    def test_recent_active_targets_use_last_30_days_of_usage(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        tz = ZoneInfo("Asia/Shanghai")
        today = datetime.now(tz).date()
        old_date = today - timedelta(days=45)

        upsert_usage_record(
            conn,
            UsageRecord(
                source="codex:cli",
                app="codex",
                external_id="recent-codex",
                started_at=f"{today.isoformat()}T10:00:00+08:00",
                local_date=today.isoformat(),
                total_tokens=1234,
            ),
        )
        upsert_usage_record(
            conn,
            UsageRecord(
                source="warp",
                app="warp",
                external_id="old-warp",
                started_at=f"{old_date.isoformat()}T10:00:00+08:00",
                local_date=old_date.isoformat(),
                total_tokens=999,
                credits=1.0,
            ),
        )
        conn.commit()

        targets = recent_active_targets(conn, tz, lookback_days=30)

        self.assertEqual(targets, ("codex",))

    def test_tok_scan_target_label_is_generic_for_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_home = os.environ.get("TOKKIT_HOME")
            original_session = os.environ.get("TOKKIT_SCAN_SESSION_KEY")
            try:
                os.environ["TOKKIT_HOME"] = tmp
                os.environ["TOKKIT_SCAN_SESSION_KEY"] = "terminal:test"
                command, label = _resolve_scan_target("all")
            finally:
                if original_home is None:
                    os.environ.pop("TOKKIT_HOME", None)
                else:
                    os.environ["TOKKIT_HOME"] = original_home
                if original_session is None:
                    os.environ.pop("TOKKIT_SCAN_SESSION_KEY", None)
                else:
                    os.environ["TOKKIT_SCAN_SESSION_KEY"] = original_session

        self.assertEqual(command, ["scan-all"])
        self.assertEqual(label, "usage data / 正在统计中")


if __name__ == "__main__":
    unittest.main()
