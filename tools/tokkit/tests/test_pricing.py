from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokkit.pricing import estimate_cost_usd, normalize_model_display


class NormalizeModelDisplayTests(unittest.TestCase):
    def test_normalizes_gpt_5_5_pro_slug(self) -> None:
        self.assertEqual(normalize_model_display("gpt-5.5-pro"), "GPT-5.5 Pro")

    def test_normalizes_gpt_5_3_codex_slug(self) -> None:
        self.assertEqual(normalize_model_display("gpt-5.3-codex"), "GPT-5.3 Codex")

    def test_preserves_fast_parenthetical_suffix(self) -> None:
        self.assertEqual(normalize_model_display("gpt-5.5 (Fast)"), "GPT-5.5 (Fast)")


class EstimateCostUsdTests(unittest.TestCase):
    def test_estimates_gpt_5_5_cost(self) -> None:
        self.assertEqual(
            estimate_cost_usd(
                model="gpt-5.5",
                provider="openai",
                measurement_method="exact",
                input_tokens=1_000_000,
                cached_input_tokens=100_000,
                output_tokens=500_000,
            ),
            19.55,
        )

    def test_estimates_gpt_5_5_pro_without_cached_discount(self) -> None:
        self.assertEqual(
            estimate_cost_usd(
                model="gpt-5.5-pro",
                provider="openai",
                measurement_method="exact",
                input_tokens=1_000_000,
                cached_input_tokens=250_000,
                output_tokens=500_000,
            ),
            120.0,
        )

    def test_estimates_gpt_5_3_codex_cost(self) -> None:
        self.assertEqual(
            estimate_cost_usd(
                model="gpt-5.3-codex",
                provider="openai",
                measurement_method="exact",
                input_tokens=1_000_000,
                cached_input_tokens=200_000,
                output_tokens=500_000,
            ),
            8.435,
        )


if __name__ == "__main__":
    unittest.main()
