"""Unit tests for `PolicyRateReporter` and the report helper functions."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from bis_prates.report import (
    PolicyRateReporter,
    compute_latest_snapshot,
    load_tidy_data,
    parse_country_codes,
    resolve_country_codes,
    select_report_data,
)
from bis_prates.speeches import SpeechesAnalysis, render_speeches_chart


class ReportTest(unittest.TestCase):
    """Country-code parsing/resolution and end-to-end report writing."""

    def test_parse_country_codes_and_resolve_euro_area_alias(self) -> None:
        """Comma-separated codes are parsed and `EA` resolves to `XM` via the alias."""
        data = pd.DataFrame(
            {
                "ref_area_code": ["US", "XM"],
            }
        )

        requested = parse_country_codes("US, ea, GB")
        resolved = resolve_country_codes(
            ["US", "EA"],
            data,
            metadata_codes={"US": "United States", "XM": "Euro area"},
        )

        self.assertEqual(requested, ["US", "EA", "GB"])
        self.assertEqual(resolved, {"US": "US", "EA": "XM"})

    def test_resolve_country_codes_uses_local_validation_without_sdmx(self) -> None:
        """Local-dataset validation kicks in when SDMX metadata is `None`."""
        data = pd.DataFrame(
            {
                "ref_area_code": ["US", "XM"],
            }
        )

        with self.assertLogs("bis_prates.report", level="WARNING") as logs:
            resolved = resolve_country_codes(["US", "EA"], data, metadata_codes=None)

        self.assertEqual(resolved, {"US": "US", "EA": "XM"})
        self.assertIn("falling back to local dataset code validation", "\n".join(logs.output))

    def test_report_writes_summary_chart_and_html(self) -> None:
        """A full report run writes summary CSV/JSON, chart PNG, and HTML."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tidy_path = root / "policy_rates_tidy.parquet"
            output_dir = root / "out"
            _write_tidy_fixture(tidy_path)

            result = PolicyRateReporter(
                tidy_data_path=tidy_path,
                output_dir=output_dir,
                metadata_provider=lambda: {
                    "US": "United States",
                    "XM": "Euro area",
                },
                speeches_provider=None,
            ).report(countries="US,EA", start="2024-01-01")

            summary = pd.read_csv(result.summary_csv_path)
            payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
            report_html = result.report_html_path.read_text(encoding="utf-8")

            us_row = summary[summary["requested_code"].eq("US")].iloc[0]
            ea_row = summary[summary["requested_code"].eq("EA")].iloc[0]

            self.assertEqual(result.rows_written, 2)
            self.assertTrue(result.chart_path.exists())
            self.assertGreater(result.chart_path.stat().st_size, 0)
            self.assertIn("data:image/png;base64", report_html)
            self.assertEqual(payload["resolved_countries"]["EA"], "XM")
            self.assertEqual(len(payload["rows"]), 2)
            self.assertEqual(us_row["latest_date"], "2024-01-03")
            self.assertEqual(us_row["latest_rate"], 5.25)
            self.assertEqual(us_row["previous_rate"], 5.0)
            self.assertEqual(round(us_row["change_from_previous"], 2), 0.25)
            self.assertEqual(ea_row["ref_area_code"], "XM")

    def test_report_includes_speeches_extension_when_available(self) -> None:
        """When a speeches provider is supplied, its outputs land in JSON and HTML."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tidy_path = root / "policy_rates_tidy.parquet"
            output_dir = root / "out"
            _write_tidy_fixture(tidy_path)

            result = PolicyRateReporter(
                tidy_data_path=tidy_path,
                output_dir=output_dir,
                metadata_provider=lambda: {"US": "United States"},
                speeches_provider=_fake_speeches_provider,
            ).report(countries="US", start="2024-01-01")

            payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
            report_html = result.report_html_path.read_text(encoding="utf-8")

            assert result.speeches_chart_path is not None
            self.assertTrue(result.speeches_chart_path.exists())
            self.assertIn("speeches_extension", payload)
            self.assertIn("Speeches terms vs policy-rate moves", report_html)

    def test_report_without_speeches_removes_stale_speeches_chart(self) -> None:
        """Stale `speeches_terms.png` from prior runs is removed when speeches are off."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tidy_path = root / "policy_rates_tidy.parquet"
            output_dir = root / "out"
            stale_chart = output_dir / "speeches_terms.png"
            _write_tidy_fixture(tidy_path)
            output_dir.mkdir()
            stale_chart.write_bytes(b"stale")

            result = PolicyRateReporter(
                tidy_data_path=tidy_path,
                output_dir=output_dir,
                metadata_provider=lambda: {"US": "United States"},
            ).report(countries="US", start="2024-01-01")

            payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
            report_html = result.report_html_path.read_text(encoding="utf-8")

            self.assertIsNone(result.speeches_chart_path)
            self.assertFalse(stale_chart.exists())
            self.assertNotIn("speeches_extension", payload)
            self.assertNotIn("Speeches terms vs policy-rate moves", report_html)

    def test_report_continues_when_sdmx_metadata_is_unavailable(self) -> None:
        """The report still runs when the metadata provider returns `None`."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tidy_path = root / "policy_rates_tidy.parquet"
            output_dir = root / "out"
            _write_tidy_fixture(tidy_path)

            with self.assertLogs("bis_prates.report", level="WARNING") as logs:
                result = PolicyRateReporter(
                    tidy_data_path=tidy_path,
                    output_dir=output_dir,
                    metadata_provider=lambda: None,
                    speeches_provider=None,
                ).report(countries="EA", start="2024-01-01")

            self.assertEqual(result.rows_written, 1)
            self.assertTrue(result.report_html_path.exists())
            self.assertIn(
                "falling back to local dataset code validation",
                "\n".join(logs.output),
            )

    def test_compute_latest_snapshot_includes_days_since_latest(self) -> None:
        """`days_since_latest` is the calendar-day age of the latest obs vs `as_of`."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tidy_path = Path(tmp_dir) / "policy_rates_tidy.parquet"
            _write_tidy_fixture(tidy_path)
            data = load_tidy_data(tidy_path)
            report_data = select_report_data(
                data=data,
                requested_codes=["US"],
                resolved_codes={"US": "US"},
                preferred_frequency="D",
            )

            summary = compute_latest_snapshot(
                report_data,
                ["US"],
                {"US": "US"},
                as_of=pd.Timestamp("2024-01-10"),
            )

            self.assertEqual(int(summary.iloc[0]["days_since_latest"]), 7)


def _write_tidy_fixture(path: Path) -> None:
    rows = [
        _row("US", "United States", "2024-01-01", "5.00", "A", "Normal value"),
        _row(
            "US",
            "United States",
            "2024-01-02",
            "NaN",
            "M",
            "Missing value; data cannot exist",
        ),
        _row("US", "United States", "2024-01-03", "5.25", "A", "Normal value"),
        _row("XM", "Euro area", "2024-01-01", "4.00", "A", "Normal value"),
        _row("XM", "Euro area", "2024-01-02", "4.50", "A", "Normal value"),
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)


def _row(
    ref_area_code: str,
    ref_area: str,
    period_start: str,
    obs_value: str,
    obs_status_code: str,
    obs_status: str,
) -> dict[str, str]:
    return {
        "structure": "dataflow",
        "structure_id": "BIS:WS_CBPOL(1.0): Central bank policy rates",
        "action": "I",
        "freq_code": "D",
        "frequency": "Daily",
        "ref_area_code": ref_area_code,
        "ref_area": ref_area,
        "time_period": period_start,
        "period_start": period_start,
        "obs_value": obs_value,
        "unit_measure_code": "368",
        "unit_measure": "Per cent per year",
        "unit_mult_code": "0",
        "unit_mult": "Units",
        "decimals": "4",
        "decimals_label": "Four",
        "time_format": "",
        "compilation": "Policy rate.",
        "source_ref": "Central bank",
        "supp_info_breaks": "",
        "title": f"Central bank policy rates - {ref_area} - Daily",
        "obs_status_code": obs_status_code,
        "obs_status": obs_status,
        "obs_conf_code": "F",
        "obs_conf": "Free",
        "obs_pre_break": "",
    }


def _fake_speeches_provider(
    report_data: pd.DataFrame,
    chart_path: Path,
) -> SpeechesAnalysis:
    term_frequencies = pd.DataFrame(
        {
            "month": [pd.Timestamp("2024-01-01")],
            "speech_count": [1],
            "inflation": [2],
            "rate": [1],
            "tightening": [0],
            "total_term_hits": [3],
        }
    )
    policy_moves = pd.DataFrame(
        {
            "month": [pd.Timestamp("2024-01-01")],
            "requested_code": ["US"],
            "policy_move_bps": [25.0],
        }
    )
    render_speeches_chart(term_frequencies, policy_moves, chart_path)
    return SpeechesAnalysis(
        chart_path=chart_path,
        term_frequencies=term_frequencies,
        policy_moves=policy_moves,
    )


if __name__ == "__main__":
    unittest.main()
