from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokkit.scan_planner import ALL_SCAN_TARGETS, record_scan_plan_result, resolve_scan_plan
from tokkit.tok import _resolve_scan_target


class ScanPlannerTests(unittest.TestCase):
    def test_first_scan_for_session_runs_full_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = resolve_scan_plan(session_key="terminal:test", app_home=Path(tmp))

        self.assertTrue(plan.full_scan)
        self.assertEqual(plan.targets, ALL_SCAN_TARGETS)
        self.assertIn("Codex", plan.label)
        self.assertIn("Warp", plan.label)

    def test_followup_scan_reuses_active_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_home = Path(tmp)
            first_plan = resolve_scan_plan(session_key="terminal:test", app_home=app_home)
            record_scan_plan_result(
                first_plan,
                active_targets=["codex", "augment", "warp"],
                scanned_targets=first_plan.targets,
                app_home=app_home,
            )

            second_plan = resolve_scan_plan(session_key="terminal:test", app_home=app_home)

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

    def test_tok_scan_target_label_uses_cached_active_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_home = os.environ.get("TOKKIT_HOME")
            original_session = os.environ.get("TOKKIT_SCAN_SESSION_KEY")
            try:
                os.environ["TOKKIT_HOME"] = tmp
                os.environ["TOKKIT_SCAN_SESSION_KEY"] = "terminal:test"
                first_plan = resolve_scan_plan()
                record_scan_plan_result(
                    first_plan,
                    active_targets=["codex", "claude-code"],
                    scanned_targets=first_plan.targets,
                )

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
        self.assertEqual(label, "Codex + Claude Code")


if __name__ == "__main__":
    unittest.main()
