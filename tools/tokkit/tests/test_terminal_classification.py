from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokkit.cli import _source_label, _terminal_label
from tokkit.clients import logical_client_for_usage_row


class TerminalClassificationTests(unittest.TestCase):
    def test_codex_desktop_is_not_labeled_as_vscode(self) -> None:
        self.assertEqual(_terminal_label("codex", "codex:vscode", "Codex Desktop"), "Codex Desktop")

    def test_non_desktop_codex_vscode_source_stays_vscode(self) -> None:
        self.assertEqual(_terminal_label("codex", "codex:vscode", "VS Code"), "VS Code")

    def test_codex_desktop_counts_as_codex_client(self) -> None:
        self.assertEqual(logical_client_for_usage_row("codex", "codex:vscode", "Codex Desktop"), "codex")

    def test_real_vscode_codex_source_counts_as_vscode_client(self) -> None:
        self.assertEqual(logical_client_for_usage_row("codex", "codex:vscode", "VS Code"), "visual-studio-code")

    def test_source_label_hides_raw_codex_vscode_for_desktop(self) -> None:
        self.assertEqual(_source_label("codex", "codex:vscode", "Codex Desktop"), "Codex Desktop")


if __name__ == "__main__":
    unittest.main()
