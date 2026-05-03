from __future__ import annotations

import unittest

from vidbrief.ai import build_report_prompt


class AITests(unittest.TestCase):
    def test_build_report_prompt_includes_core_metadata_and_transcript(self) -> None:
        prompt = build_report_prompt(
            {"title": "Demo", "webpage_url": "https://example.test/v", "duration": 90, "uploader": "Yao"},
            "Transcript body",
            language="zh-CN",
        )

        self.assertIn("Demo", prompt)
        self.assertIn("https://example.test/v", prompt)
        self.assertIn("1:30", prompt)
        self.assertIn("Transcript body", prompt)


if __name__ == "__main__":
    unittest.main()
