"""Unit tests for the BIS policy-rate tidy transformation."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from bis_prates.transform import (
    RAW_COLUMNS,
    RAW_CSV_NAME,
    PolicyRateTransformer,
    find_missing_observations,
    period_to_start_date,
    split_code_label,
    tidy_policy_rate_frame,
    tidy_policy_rate_row,
)


def sample_raw_row(**overrides: str) -> dict[str, str]:
    """Return a complete raw BIS row with default values, applying any overrides."""
    row = {
        RAW_COLUMNS["structure"]: "dataflow",
        RAW_COLUMNS["structure_id"]: "BIS:WS_CBPOL(1.0): Central bank policy rates",
        RAW_COLUMNS["action"]: "I",
        RAW_COLUMNS["frequency"]: "M: Monthly",
        RAW_COLUMNS["ref_area"]: "US: United States",
        RAW_COLUMNS["time_period"]: "2024-01",
        RAW_COLUMNS["obs_value"]: "5.50",
        RAW_COLUMNS["unit_measure"]: "368: Per cent per year",
        RAW_COLUMNS["unit_mult"]: "0: Units",
        RAW_COLUMNS["time_format"]: "",
        RAW_COLUMNS["compilation"]: "Target rate.",
        RAW_COLUMNS["decimals"]: "4: Four",
        RAW_COLUMNS["source_ref"]: "Federal Reserve",
        RAW_COLUMNS["supp_info_breaks"]: "",
        RAW_COLUMNS["title"]: " Central bank policy rates - United States - Monthly ",
        RAW_COLUMNS["obs_status"]: "A: Normal value",
        RAW_COLUMNS["obs_conf"]: "F: Free",
        RAW_COLUMNS["obs_pre_break"]: "",
    }
    row.update(overrides)
    return row


class TransformParsingTest(unittest.TestCase):
    """Pure parsing helpers: code/label splitting, period parsing, missing-obs detection."""

    def test_split_code_label(self) -> None:
        """SDMX `code: label` strings split correctly; non-coded values pass through."""
        self.assertEqual(split_code_label("US: United States"), ("US", "United States"))
        self.assertEqual(split_code_label("Target rate."), ("Target rate.", ""))
        self.assertEqual(split_code_label(""), ("", ""))

    def test_period_to_start_date(self) -> None:
        """Monthly, quarterly, and annual periods all map to the right ISO start date."""
        self.assertEqual(period_to_start_date("2024-01"), "2024-01-01")
        self.assertEqual(period_to_start_date("2024-Q3"), "2024-07-01")
        self.assertEqual(period_to_start_date("2024"), "2024-01-01")

    def test_tidy_policy_rate_row(self) -> None:
        """A single raw BIS row tidies to the expected schema."""
        tidy_row = tidy_policy_rate_row(sample_raw_row())

        self.assertEqual(tidy_row["freq_code"], "M")
        self.assertEqual(tidy_row["frequency"], "Monthly")
        self.assertEqual(tidy_row["ref_area_code"], "US")
        self.assertEqual(tidy_row["ref_area"], "United States")
        self.assertEqual(tidy_row["period_start"], "2024-01-01")
        self.assertEqual(tidy_row["obs_value"], "5.50")
        self.assertEqual(tidy_row["decimals"], "4")

    def test_find_missing_observations(self) -> None:
        """Rows with empty/`NaN` values or status `M` are flagged as missing."""
        raw_rows = [
            sample_raw_row(),
            sample_raw_row(
                **{
                    RAW_COLUMNS["time_period"]: "2024-09-21",
                    RAW_COLUMNS["obs_value"]: "NaN",
                    RAW_COLUMNS["obs_status"]: "M: Missing value; data cannot exist",
                }
            ),
            sample_raw_row(
                **{
                    RAW_COLUMNS["time_period"]: "2024-09-22",
                    RAW_COLUMNS["obs_value"]: "",
                }
            ),
        ]
        tidy_frame = tidy_policy_rate_frame(pd.DataFrame(raw_rows))
        missing_frame = find_missing_observations(tidy_frame)

        self.assertEqual(len(missing_frame), 2)
        self.assertEqual(list(missing_frame["time_period"]), ["2024-09-21", "2024-09-22"])


class PolicyRateTransformerTest(unittest.TestCase):
    """End-to-end ZIP-to-parquet transformation."""

    def test_transform_writes_tidy_parquet_and_deduplicates_rows(self) -> None:
        """Duplicates collapse, missing rows divert to the audit CSV, manifest counts match."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            archive_path = root / "raw.zip"
            output_path = root / "policy_rates_tidy.parquet"
            manifest_path = root / "transform_manifest.json"
            missing_path = root / "missing_observations.csv"

            rows = [
                sample_raw_row(),
                sample_raw_row(),
                sample_raw_row(**{RAW_COLUMNS["time_period"]: "2024-02"}),
                sample_raw_row(
                    **{
                        RAW_COLUMNS["time_period"]: "2024-09-21",
                        RAW_COLUMNS["obs_value"]: "NaN",
                        RAW_COLUMNS["obs_status"]: ("M: Missing value; data cannot exist"),
                    }
                ),
            ]
            _write_zip_csv(archive_path, rows)

            result = PolicyRateTransformer(
                archive_path=archive_path,
                output_path=output_path,
                manifest_path=manifest_path,
                missing_observations_path=missing_path,
            ).transform()

            output_rows = pd.read_parquet(output_path).to_dict("records")
            with missing_path.open("r", encoding="utf-8", newline="") as missing_file:
                missing_rows = list(csv.DictReader(missing_file))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(result.rows_read, 4)
            self.assertEqual(result.rows_written, 3)
            self.assertEqual(result.duplicates_dropped, 1)
            self.assertEqual(result.missing_observation_rows, 1)
            self.assertEqual(len(output_rows), 3)
            self.assertEqual(output_rows[0]["ref_area_code"], "US")
            self.assertEqual(len(missing_rows), 1)
            self.assertEqual(missing_rows[0]["obs_status_code"], "M")
            self.assertEqual(manifest["missing_observation_rows"], 1)
            self.assertEqual(manifest["missing_observations_path"], str(missing_path))
            self.assertTrue(manifest_path.exists())


def _write_zip_csv(path: Path, rows: list[dict[str, str]]) -> None:
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=list(RAW_COLUMNS.values()))
    writer.writeheader()
    writer.writerows(rows)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(RAW_CSV_NAME, csv_buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
