from __future__ import annotations

import unittest

from vidbrief.cli import _normalize_argv, build_parser, render_help


class CLITests(unittest.TestCase):
    def test_no_args_is_allowed_for_guided_mode(self) -> None:
        args = build_parser().parse_args([])

        self.assertIsNone(args.command)

    def test_run_url_is_optional_for_interactive_prompt(self) -> None:
        args = build_parser().parse_args(["run"])

        self.assertEqual(args.command, "run")
        self.assertIsNone(args.url)

    def test_normalizes_missing_space_between_command_and_url(self) -> None:
        self.assertEqual(
            _normalize_argv(["infohttps://example.test/video"]),
            ["info", "https://example.test/video"],
        )

    def test_help_command_parses(self) -> None:
        args = build_parser().parse_args(["help"])

        self.assertEqual(args.command, "help")

    def test_tui_command_parses(self) -> None:
        args = build_parser().parse_args(["tui"])

        self.assertEqual(args.command, "tui")

    def test_render_help_is_bilingual(self) -> None:
        rendered = render_help()

        self.assertIn("Usage / 用法", rendered)
        self.assertIn("下载、转写、生成报告", rendered)
        self.assertIn("vb tui", rendered)
        self.assertIn("vb run", rendered)


if __name__ == "__main__":
    unittest.main()
