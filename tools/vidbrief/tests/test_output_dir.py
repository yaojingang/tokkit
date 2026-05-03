from __future__ import annotations

import unittest
from pathlib import Path

from vidbrief.cli import build_parser
from vidbrief.utils import DEFAULT_OUTPUT_DIR


class OutputDirTests(unittest.TestCase):
    def test_default_output_dir_is_downloads_folder(self) -> None:
        self.assertIn(DEFAULT_OUTPUT_DIR.name, {"下载", "Downloads"})
        self.assertEqual(DEFAULT_OUTPUT_DIR.parent, Path.home())

    def test_dir_alias_sets_output(self) -> None:
        args = build_parser().parse_args(["run", "https://example.test/video", "--dir", "/tmp/vb-output"])

        self.assertEqual(args.output, Path("/tmp/vb-output"))


if __name__ == "__main__":
    unittest.main()
