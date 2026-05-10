from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from bis_prates.speeches import (
    compute_monthly_policy_moves,
    compute_term_frequencies,
    load_recent_speeches,
    render_speeches_chart,
    term_frequency_summary,
)


class SpeechesTest(unittest.TestCase):
    def test_load_recent_speeches_calls_year_loader_with_timeout_keyword(self) -> None:
        raw_speeches = pd.DataFrame(
            {
                "date": ["2024-06-01"],
                "text": ["Inflation and policy rates."],
            }
        )

        with patch(
            "bis_prates.speeches._load_speeches_year",
            return_value=raw_speeches,
        ) as loader:
            result = load_recent_speeches(
                today=datetime(2024, 6, 1),
                lookback_years=0,
                timeout=7,
            )

        loader.assert_called_once_with(2024, timeout=7)
        self.assertEqual(len(result), 1)


    def test_compute_term_frequencies_counts_terms_by_month(self) -> None:
        speeches = pd.DataFrame(
            {
                "date": ["2024-06-01", "2024-06-15", "2024-07-01"],
                "text": [
                    "Inflation and rates. Tightening tightening.",
                    "Price stability and interest rates point to a restrictive stance.",
                    "Inflationary pressure, CPI, a policy rate and hikes.",
                ],
            }
        )

        result = compute_term_frequencies(speeches)

        june = result[result["month"].eq(pd.Timestamp("2024-06-01"))].iloc[0]
        july = result[result["month"].eq(pd.Timestamp("2024-07-01"))].iloc[0]
        self.assertEqual(june["speech_count"], 2)
        self.assertEqual(june["inflation"], 2)
        self.assertEqual(june["rate"], 2)
        self.assertEqual(june["tightening"], 3)
        self.assertEqual(july["inflation"], 2)
        self.assertEqual(july["rate"], 1)
        self.assertEqual(july["tightening"], 1)

    def test_compute_monthly_policy_moves_returns_signed_country_bps(self) -> None:
        policy_rates = pd.DataFrame(
            {
                "requested_code": ["US", "US", "GB", "GB"],
                "period_start": [
                    "2024-01-31",
                    "2024-02-29",
                    "2024-01-31",
                    "2024-02-29",
                ],
                "obs_value_numeric": [5.00, 5.25, 4.50, 4.00],
            }
        )

        result = compute_monthly_policy_moves(policy_rates)

        february = result[result["month"].eq(pd.Timestamp("2024-02-01"))]
        self.assertEqual(set(february["requested_code"]), {"GB", "US"})
        self.assertEqual(
            february.loc[february["requested_code"].eq("US"), "policy_move_bps"].iloc[0],
            25.0,
        )
        self.assertEqual(
            february.loc[february["requested_code"].eq("GB"), "policy_move_bps"].iloc[0],
            -50.0,
        )

    def test_term_summary_and_chart_render(self) -> None:
        frequencies = pd.DataFrame(
            {
                "month": [pd.Timestamp("2024-06-01")],
                "speech_count": [2],
                "inflation": [3],
                "rate": [4],
                "tightening": [1],
                "total_term_hits": [8],
            }
        )
        moves = pd.DataFrame(
            {
                "month": [pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-01")],
                "requested_code": ["US", "GB"],
                "policy_move_bps": [25.0, -25.0],
            }
        )

        summary = term_frequency_summary(frequencies)
        with tempfile.TemporaryDirectory() as tmp_dir:
            chart_path = Path(tmp_dir) / "speeches_terms.png"
            render_speeches_chart(frequencies, moves, chart_path)

            self.assertEqual(summary.loc[summary["term"].eq("inflation"), "mentions"].iloc[0], 3)
            self.assertTrue(chart_path.exists())
            self.assertGreater(chart_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
