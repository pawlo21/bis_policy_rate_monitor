"""Transform BIS policy-rate bulk data into a tidy dataset."""

from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# `ARROW_USER_SIMD_LEVEL` must be set before pyarrow is imported anywhere,
# otherwise pyarrow's runtime SIMD detection emits noisy stderr warnings on
# some macOS / older-CPU environments. Same justification as ruff's E402.
os.environ.setdefault("ARROW_USER_SIMD_LEVEL", "NONE")

import pandas as pd  # pylint: disable=wrong-import-position
import pyarrow as pa  # pylint: disable=wrong-import-position
import pyarrow.parquet as pq  # pylint: disable=wrong-import-position

DEFAULT_FETCH_MANIFEST_PATH = Path("data/raw/fetch_manifest.json")
DEFAULT_ARCHIVE_PATH = Path("data/raw/WS_CBPOL_csv_flat.zip")
DEFAULT_OUTPUT_PATH = Path("data/processed/policy_rates_tidy.parquet")
DEFAULT_MANIFEST_PATH = Path("data/processed/transform_manifest.json")
DEFAULT_MISSING_OBSERVATIONS_PATH = Path("data/processed/missing_observations.csv")
RAW_CSV_NAME = "WS_CBPOL_csv_flat.csv"
DEFAULT_CHUNKSIZE = 100_000

RAW_COLUMNS = {
    "structure": "STRUCTURE",
    "structure_id": "STRUCTURE_ID",
    "action": "ACTION",
    "frequency": "FREQ:Frequency",
    "ref_area": "REF_AREA:Reference area",
    "time_period": "TIME_PERIOD:Time period or range",
    "obs_value": "OBS_VALUE:Observation Value",
    "unit_measure": "UNIT_MEASURE:Unit of measure",
    "unit_mult": "UNIT_MULT:Unit Multiplier",
    "time_format": "TIME_FORMAT:Time Format",
    "compilation": "COMPILATION:Compilation",
    "decimals": "DECIMALS:Decimals",
    "source_ref": "SOURCE_REF:Publication Source",
    "supp_info_breaks": "SUPP_INFO_BREAKS:Supplemental information and breaks",
    "title": "TITLE:Title",
    "obs_status": "OBS_STATUS:Observation Status",
    "obs_conf": "OBS_CONF:Observation confidentiality",
    "obs_pre_break": "OBS_PRE_BREAK:Pre-Break Observation",
}

TIDY_COLUMNS = [
    "structure",
    "structure_id",
    "action",
    "freq_code",
    "frequency",
    "ref_area_code",
    "ref_area",
    "time_period",
    "period_start",
    "obs_value",
    "unit_measure_code",
    "unit_measure",
    "unit_mult_code",
    "unit_mult",
    "decimals",
    "decimals_label",
    "time_format",
    "compilation",
    "source_ref",
    "supp_info_breaks",
    "title",
    "obs_status_code",
    "obs_status",
    "obs_conf_code",
    "obs_conf",
    "obs_pre_break",
]

MISSING_OBSERVATION_COLUMNS = [
    "freq_code",
    "frequency",
    "ref_area_code",
    "ref_area",
    "time_period",
    "period_start",
    "obs_value",
    "obs_status_code",
    "obs_status",
    "title",
]


@dataclass(frozen=True)
class TransformResult:
    """Counts and paths summarising a `PolicyRateTransformer.transform()` run."""

    archive_path: Path
    output_path: Path
    manifest_path: Path
    rows_read: int
    rows_written: int
    duplicates_dropped: int
    missing_observation_rows: int


class PolicyRateTransformer:
    """Parse the cached BIS ZIP and write a tidy policy-rate Parquet dataset."""

    def __init__(
        self,
        *,
        archive_path: Path | None = None,
        output_path: Path = DEFAULT_OUTPUT_PATH,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        missing_observations_path: Path = DEFAULT_MISSING_OBSERVATIONS_PATH,
        fetch_manifest_path: Path = DEFAULT_FETCH_MANIFEST_PATH,
        raw_csv_name: str = RAW_CSV_NAME,
        chunksize: int = DEFAULT_CHUNKSIZE,
    ) -> None:
        """Configure input/output paths and CSV chunk size.

        When `archive_path` is `None` the raw archive path is read from
        `fetch_manifest_path`.
        """
        self.archive_path = archive_path
        self.output_path = Path(output_path)
        self.manifest_path = Path(manifest_path)
        self.missing_observations_path = Path(missing_observations_path)
        self.fetch_manifest_path = Path(fetch_manifest_path)
        self.raw_csv_name = raw_csv_name
        self.chunksize = chunksize

    def transform(self) -> TransformResult:
        """Stream the raw CSV in chunks and write the tidy parquet dataset.

        Deduplicates on `(freq_code, ref_area_code, time_period)`, raising
        if the same key appears with conflicting fingerprints. Rows with
        missing observations are diverted to a separate audit CSV.
        """
        archive_path = self._resolve_archive_path()
        if not archive_path.exists():
            raise FileNotFoundError(
                f"Raw BIS archive not found: {archive_path}. Run 'bis-prates fetch' first."
            )

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        seen_rows: dict[tuple[str, str, str], tuple[str, ...]] = {}
        rows_read = 0
        rows_written = 0
        duplicates_dropped = 0
        missing_observation_rows = 0
        wrote_header = False
        wrote_missing_header = False
        parquet_writer: pq.ParquetWriter | None = None

        try:
            with zipfile.ZipFile(archive_path) as archive:
                if self.raw_csv_name not in archive.namelist():
                    raise FileNotFoundError(
                        f"{self.raw_csv_name} not found in archive: {archive_path}"
                    )

                with archive.open(self.raw_csv_name) as raw_file:
                    reader = pd.read_csv(
                        raw_file,
                        dtype=str,
                        keep_default_na=False,
                        chunksize=self.chunksize,
                        encoding="utf-8-sig",
                    )

                    for raw_chunk in reader:
                        _validate_columns(raw_chunk.columns)
                        rows_read += len(raw_chunk)
                        tidy_chunk = tidy_policy_rate_frame(raw_chunk)
                        keep_mask, chunk_duplicates = _dedupe_chunk(tidy_chunk, seen_rows)
                        output_chunk = tidy_chunk.loc[keep_mask, TIDY_COLUMNS]
                        missing_chunk = find_missing_observations(output_chunk)

                        parquet_writer = _write_parquet_chunk(
                            output_chunk=output_chunk,
                            output_path=self.output_path,
                            parquet_writer=parquet_writer,
                        )

                        wrote_header = True
                        rows_written += len(output_chunk)
                        duplicates_dropped += chunk_duplicates
                        missing_observation_rows += len(missing_chunk)

                        if not missing_chunk.empty:
                            missing_chunk.to_csv(
                                self.missing_observations_path,
                                mode="w" if not wrote_missing_header else "a",
                                header=not wrote_missing_header,
                                index=False,
                            )
                            wrote_missing_header = True
        finally:
            if parquet_writer is not None:
                parquet_writer.close()

        if not wrote_header:
            empty_table = pa.Table.from_pandas(
                pd.DataFrame(columns=TIDY_COLUMNS),
                preserve_index=False,
            )
            pq.write_table(empty_table, self.output_path)

        if not wrote_missing_header:
            pd.DataFrame(columns=MISSING_OBSERVATION_COLUMNS).to_csv(
                self.missing_observations_path, index=False
            )

        self._write_manifest(
            archive_path=archive_path,
            rows_read=rows_read,
            rows_written=rows_written,
            duplicates_dropped=duplicates_dropped,
            missing_observation_rows=missing_observation_rows,
        )

        return TransformResult(
            archive_path=archive_path,
            output_path=self.output_path,
            manifest_path=self.manifest_path,
            rows_read=rows_read,
            rows_written=rows_written,
            duplicates_dropped=duplicates_dropped,
            missing_observation_rows=missing_observation_rows,
        )

    def _resolve_archive_path(self) -> Path:
        if self.archive_path is not None:
            return Path(self.archive_path)

        if self.fetch_manifest_path.exists():
            with self.fetch_manifest_path.open("r", encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
            archive_path = manifest.get("archive_path")
            if archive_path:
                return Path(str(archive_path))

        return DEFAULT_ARCHIVE_PATH

    def _write_manifest(
        self,
        *,
        archive_path: Path,
        rows_read: int,
        rows_written: int,
        duplicates_dropped: int,
        missing_observation_rows: int,
    ) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "source_archive": str(archive_path),
            "source_csv": self.raw_csv_name,
            "output_path": str(self.output_path),
            "rows_read": rows_read,
            "rows_written": rows_written,
            "duplicates_dropped": duplicates_dropped,
            "missing_observation_rows": missing_observation_rows,
            "missing_observations_path": str(self.missing_observations_path),
            "transformed_at_utc": datetime.now(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }

        with self.manifest_path.open("w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, indent=2, sort_keys=True)
            manifest_file.write("\n")


def tidy_policy_rate_row(raw_row: dict[str, str]) -> dict[str, str]:
    """Tidy a single raw BIS row. Mostly useful in tests."""
    raw_frame = pd.DataFrame([raw_row])
    tidy_frame = tidy_policy_rate_frame(raw_frame)
    return tidy_frame.iloc[0].to_dict()


def tidy_policy_rate_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    """Convert a raw BIS chunk into the project's tidy schema.

    Splits SDMX `code:label` columns, cleans text, normalises decimals
    via `Decimal` (no float round-trip), and parses time-period strings
    into `period_start` ISO dates.
    """
    _validate_columns(raw_frame.columns)

    tidy_frame = pd.DataFrame(index=raw_frame.index)
    freq = split_code_label_series(raw_frame[RAW_COLUMNS["frequency"]])
    ref_area = split_code_label_series(raw_frame[RAW_COLUMNS["ref_area"]])
    unit_measure = split_code_label_series(raw_frame[RAW_COLUMNS["unit_measure"]])
    unit_mult = split_code_label_series(raw_frame[RAW_COLUMNS["unit_mult"]])
    decimals = split_code_label_series(raw_frame[RAW_COLUMNS["decimals"]])
    obs_status = split_code_label_series(raw_frame[RAW_COLUMNS["obs_status"]])
    obs_conf = split_code_label_series(raw_frame[RAW_COLUMNS["obs_conf"]])
    time_period = clean_text_series(raw_frame[RAW_COLUMNS["time_period"]])

    tidy_frame["structure"] = clean_text_series(raw_frame[RAW_COLUMNS["structure"]])
    tidy_frame["structure_id"] = clean_text_series(raw_frame[RAW_COLUMNS["structure_id"]])
    tidy_frame["action"] = clean_text_series(raw_frame[RAW_COLUMNS["action"]])
    tidy_frame["freq_code"] = freq["code"]
    tidy_frame["frequency"] = freq["label"]
    tidy_frame["ref_area_code"] = ref_area["code"]
    tidy_frame["ref_area"] = ref_area["label"]
    tidy_frame["time_period"] = time_period
    tidy_frame["period_start"] = time_period.map(period_to_start_date)
    tidy_frame["obs_value"] = raw_frame[RAW_COLUMNS["obs_value"]].map(normalize_decimal)
    tidy_frame["unit_measure_code"] = unit_measure["code"]
    tidy_frame["unit_measure"] = unit_measure["label"]
    tidy_frame["unit_mult_code"] = unit_mult["code"]
    tidy_frame["unit_mult"] = unit_mult["label"]
    tidy_frame["decimals"] = decimals["code"]
    tidy_frame["decimals_label"] = decimals["label"]
    tidy_frame["time_format"] = clean_text_series(raw_frame[RAW_COLUMNS["time_format"]])
    tidy_frame["compilation"] = clean_text_series(raw_frame[RAW_COLUMNS["compilation"]])
    tidy_frame["source_ref"] = clean_text_series(raw_frame[RAW_COLUMNS["source_ref"]])
    tidy_frame["supp_info_breaks"] = clean_text_series(raw_frame[RAW_COLUMNS["supp_info_breaks"]])
    tidy_frame["title"] = clean_text_series(raw_frame[RAW_COLUMNS["title"]])
    tidy_frame["obs_status_code"] = obs_status["code"]
    tidy_frame["obs_status"] = obs_status["label"]
    tidy_frame["obs_conf_code"] = obs_conf["code"]
    tidy_frame["obs_conf"] = obs_conf["label"]
    tidy_frame["obs_pre_break"] = clean_text_series(raw_frame[RAW_COLUMNS["obs_pre_break"]])

    return tidy_frame[TIDY_COLUMNS]


def find_missing_observations(tidy_frame: pd.DataFrame) -> pd.DataFrame:
    """Return the subset of `tidy_frame` whose obs is empty/`NaN` or status `M`."""
    obs_value = clean_text_series(tidy_frame["obs_value"])
    obs_status_code = clean_text_series(tidy_frame["obs_status_code"])
    missing_mask = obs_value.isin(["", "NaN"]) | obs_status_code.eq("M")
    return tidy_frame.loc[missing_mask, MISSING_OBSERVATION_COLUMNS]


def _write_parquet_chunk(
    output_chunk: pd.DataFrame,
    output_path: Path,
    parquet_writer: pq.ParquetWriter | None,
) -> pq.ParquetWriter:
    table = pa.Table.from_pandas(output_chunk, preserve_index=False)

    if parquet_writer is None:
        parquet_writer = pq.ParquetWriter(output_path, table.schema)

    parquet_writer.write_table(table)
    return parquet_writer


def split_code_label(value: str) -> tuple[str, str]:
    """Split an SDMX `code: label` string into `(code, label)` parts."""
    value = clean_text(value)
    if not value:
        return "", ""

    code, separator, label = value.partition(":")
    if not separator:
        return value, ""

    return clean_text(code), clean_text(label)


def split_code_label_series(series: pd.Series) -> pd.DataFrame:
    """Vectorised counterpart of `split_code_label` returning a `code`/`label` frame."""
    cleaned = clean_text_series(series)
    parts = cleaned.str.partition(":")
    has_separator = parts[1].eq(":")

    return pd.DataFrame(
        {
            "code": clean_text_series(parts[0].where(has_separator, cleaned)),
            "label": clean_text_series(parts[2].where(has_separator, "")),
        },
        index=series.index,
    )


def clean_text(value: str | None) -> str:
    """Collapse internal whitespace and strip; return empty string on `None`."""
    if value is None:
        return ""

    return " ".join(str(value).split())


def clean_text_series(series: pd.Series) -> pd.Series:
    """Vectorised `clean_text` for a pandas Series."""
    return series.fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()


def normalize_decimal(value: str) -> str:
    """Render `value` as a decimal string without float round-trip loss.

    Uses `Decimal` parsing so trailing zeros and precision are preserved.
    Empty input returns `""`; non-numeric input raises `ValueError`.
    """
    value = clean_text(value)
    if not value:
        return ""

    try:
        return format(Decimal(value), "f")
    except InvalidOperation as error:
        raise ValueError(f"Invalid numeric observation value: {value}") from error


def period_to_start_date(period: str) -> str:
    """Convert a BIS time-period string to an ISO start date.

    Supports daily (`YYYY-MM-DD`), monthly (`YYYY-MM`), quarterly
    (`YYYY-Q1`..`Q4`), and annual (`YYYY`) periods. Raises `ValueError`
    for unrecognised formats.
    """
    period = clean_text(period)
    if not period:
        return ""

    if len(period) == 10 and period[4] == "-" and period[7] == "-":
        return period

    if len(period) == 7 and period[4] == "-":
        year, month = period.split("-")
        quarter_start_month = {"Q1": "01", "Q2": "04", "Q3": "07", "Q4": "10"}
        if month in quarter_start_month:
            return f"{year}-{quarter_start_month[month]}-01"

        if month.isdigit() and 1 <= int(month) <= 12:
            return f"{year}-{month}-01"

    if len(period) == 4 and period.isdigit():
        return f"{period}-01-01"

    raise ValueError(f"Unsupported time period format: {period}")


def _validate_columns(fieldnames: Iterable[str] | None) -> None:
    if fieldnames is None:
        raise ValueError("Raw BIS CSV has no header row.")

    available_columns = set(fieldnames)
    missing_columns = [column for column in RAW_COLUMNS.values() if column not in available_columns]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"Raw BIS CSV is missing expected columns: {missing}")


def _dedupe_chunk(
    tidy_chunk: pd.DataFrame,
    seen_rows: dict[tuple[str, str, str], tuple[str, ...]],
) -> tuple[list[bool], int]:
    keep_mask = []
    duplicates_dropped = 0

    dedupe_keys = tidy_chunk[["freq_code", "ref_area_code", "time_period"]].itertuples(
        index=False, name=None
    )
    row_fingerprints = tidy_chunk[TIDY_COLUMNS].itertuples(index=False, name=None)

    for dedupe_key, row_fingerprint in zip(dedupe_keys, row_fingerprints, strict=False):
        existing_fingerprint = seen_rows.get(dedupe_key)
        if existing_fingerprint is not None:
            if existing_fingerprint != row_fingerprint:
                raise ValueError(f"Conflicting duplicate observation for {dedupe_key}")

            duplicates_dropped += 1
            keep_mask.append(False)
            continue

        seen_rows[dedupe_key] = row_fingerprint
        keep_mask.append(True)

    return keep_mask, duplicates_dropped
