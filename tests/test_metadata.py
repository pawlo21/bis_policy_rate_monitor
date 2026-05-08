from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bis_prates.metadata import (
    CountryCodeValidationError,
    fetch_reference_area_codes,
    discover_dataflow_reference_from_csv,
    validate_country_codes,
)


class MetadataTest(unittest.TestCase):
    def test_discover_dataflow_reference_from_downloaded_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = Path(tmp_dir) / "bulk.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "WS_CBPOL_csv_flat.csv",
                    "STRUCTURE,STRUCTURE_ID,ACTION\n"
                    "dataflow,BIS:WS_CBPOL(1.0): Central bank policy rates,I\n",
                )

            reference = discover_dataflow_reference_from_csv(archive_path)

        self.assertEqual(reference.agency, "BIS")
        self.assertEqual(reference.dataflow_id, "WS_CBPOL")
        self.assertEqual(reference.version, "1.0")

    def test_fetch_reference_area_codes_falls_back_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "sdmx_ref_area_codes.json"
            cache_path.write_text(
                json.dumps({"codes": {"US": "United States", "XM": "Euro area"}}),
                encoding="utf-8",
            )

            with self.assertLogs("bis_prates.metadata", level="INFO") as logs, patch(
                "bis_prates.metadata.discover_dataflow_reference_from_csv",
                side_effect=TimeoutError("metadata timeout"),
            ) as discover:
                codes = fetch_reference_area_codes(
                    archive_path=Path(tmp_dir) / "missing.zip",
                    cache_path=cache_path,
                    attempts=2,
                    retry_delay_seconds=0,
                )

        self.assertEqual(codes["US"], "United States")
        self.assertEqual(codes["XM"], "Euro area")
        self.assertEqual(discover.call_count, 2)
        self.assertIn("Using cached BIS SDMX reference-area codes", "\n".join(logs.output))

    def test_fetch_reference_area_codes_returns_none_without_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "missing_cache.json"

            with self.assertLogs("bis_prates.metadata", level="WARNING") as logs, patch(
                "bis_prates.metadata.discover_dataflow_reference_from_csv",
                side_effect=TimeoutError("metadata timeout"),
            ) as discover:
                codes = fetch_reference_area_codes(
                    archive_path=Path(tmp_dir) / "missing.zip",
                    cache_path=cache_path,
                    attempts=2,
                    retry_delay_seconds=0,
                )

        self.assertIsNone(codes)
        self.assertEqual(discover.call_count, 2)
        self.assertIn("Skipping BIS SDMX validation", "\n".join(logs.output))

    def test_validate_country_codes_accepts_euro_area_alias(self) -> None:
        resolved = validate_country_codes(
            ["US", "EA"],
            {
                "US": "United States",
                "XM": "Euro area",
            },
        )

        self.assertEqual(resolved, {"US": "US", "EA": "XM"})

    def test_validate_country_codes_suggests_common_alternative(self) -> None:
        with self.assertRaises(CountryCodeValidationError) as ctx:
            validate_country_codes(
                ["UK"],
                {
                    "GB": "United Kingdom",
                    "US": "United States",
                    "XM": "Euro area",
                },
            )

        self.assertEqual(ctx.exception.invalid_codes[0].code, "UK")
        self.assertIn("GB", ctx.exception.invalid_codes[0].suggestions)


if __name__ == "__main__":
    unittest.main()
