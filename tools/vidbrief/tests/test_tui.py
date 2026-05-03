from __future__ import annotations

import unittest
from pathlib import Path

from vidbrief.tui import BROWSER_CHOICES, QUALITY_CHOICES, TuiResult


class TuiTests(unittest.TestCase):
    def test_tui_result_holds_selected_options(self) -> None:
        result = TuiResult(
            action="run",
            url="https://example.test/video",
            output=Path("/tmp/vb"),
            cookies_from_browser="chrome",
            report_provider="codex",
            language="zh-CN",
            video_format="best",
        )

        self.assertEqual(result.action, "run")
        self.assertEqual(result.cookies_from_browser, "chrome")
        self.assertEqual(result.output, Path("/tmp/vb"))

    def test_tui_choices_include_expected_defaults(self) -> None:
        self.assertEqual(BROWSER_CHOICES[0][0], "")
        self.assertIn(("chrome", "chrome"), BROWSER_CHOICES)
        self.assertIn("720p", QUALITY_CHOICES[0][1])


if __name__ == "__main__":
    unittest.main()
