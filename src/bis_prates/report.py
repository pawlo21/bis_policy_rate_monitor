"""Generate policy-rate summaries, charts, and HTML reports."""

from __future__ import annotations

import base64
import contextlib
import html
import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# MPLCONFIGDIR and ARROW_USER_SIMD_LEVEL must be set before matplotlib/pyarrow
# are imported, so the imports below intentionally appear after the env setup.
# E402 (module-level imports not at top) is therefore suppressed for them.
# `tempfile.gettempdir()` resolves to the platform-appropriate temp dir
# (`/tmp` on Linux, `/var/folders/...` on macOS) so CI runners on either
# platform can create the matplotlib cache without permission errors.
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "bis_prates_matplotlib"),
)
os.environ.setdefault("ARROW_USER_SIMD_LEVEL", "NONE")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from bis_prates.metadata import (  # noqa: E402
    COUNTRY_ALIASES,
    fetch_reference_area_codes,
    validate_country_codes,
)
from bis_prates.speeches import (  # noqa: E402
    SpeechesAnalysis,
    term_frequency_summary,
)

log = logging.getLogger(__name__)

DEFAULT_TIDY_DATA_PATH = Path("data/processed/policy_rates_tidy.parquet")
DEFAULT_OUTPUT_DIR = Path("out")
SUMMARY_CSV_NAME = "summary.csv"
SUMMARY_JSON_NAME = "summary.json"
CHART_NAME = "policy_rates.png"
SPEECHES_CHART_NAME = "speeches_terms.png"
REPORT_HTML_NAME = "report.html"
PREFERRED_FREQUENCY = "D"
REPORT_COLUMNS = [
    "requested_code",
    "ref_area_code",
    "ref_area",
    "frequency",
    "latest_date",
    "latest_rate",
    "previous_date",
    "previous_rate",
    "change_from_previous",
    "unit_measure",
    "unit_mult",
    "decimals",
    "title",
    "source_ref",
    "compilation",
    "obs_status_code",
    "obs_status",
]


@dataclass(frozen=True)
class ReportResult:
    """Paths and counts produced by `PolicyRateReporter.report()`."""

    summary_csv_path: Path
    summary_json_path: Path
    chart_path: Path
    report_html_path: Path
    countries: list[str]
    rows_written: int
    speeches_chart_path: Path | None = None


class PolicyRateReporter:
    """Create the report outputs required by the exercise."""

    def __init__(
        self,
        tidy_data_path: Path = DEFAULT_TIDY_DATA_PATH,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        preferred_frequency: str = PREFERRED_FREQUENCY,
        metadata_provider: Callable[[], Mapping[str, str] | None] = (fetch_reference_area_codes),
        speeches_provider: Callable[[pd.DataFrame, Path], SpeechesAnalysis | None] | None = None,
    ) -> None:
        """Configure paths and the metadata/speeches providers (injected for tests)."""
        self.tidy_data_path = Path(tidy_data_path)
        self.output_dir = Path(output_dir)
        self.preferred_frequency = preferred_frequency
        self.metadata_provider = metadata_provider
        self.speeches_provider = speeches_provider
        self.summary_csv_path = self.output_dir / SUMMARY_CSV_NAME
        self.summary_json_path = self.output_dir / SUMMARY_JSON_NAME
        self.chart_path = self.output_dir / CHART_NAME
        self.speeches_chart_path = self.output_dir / SPEECHES_CHART_NAME
        self.report_html_path = self.output_dir / REPORT_HTML_NAME

    def report(self, countries: Iterable[str], start: str) -> ReportResult:
        """Generate every report artefact (CSV, JSON, chart, HTML).

        Args:
            countries: Comma-separated string or iterable of BIS country codes.
            start: ISO start date for the chart range.

        """
        requested_codes = parse_country_codes(countries)
        if not requested_codes:
            raise ValueError("At least one country code is required.")

        start_date = pd.Timestamp(start)
        metadata_codes = self.metadata_provider()
        data = load_tidy_data(self.tidy_data_path)
        resolved_codes = resolve_country_codes(
            requested_codes,
            data,
            metadata_codes=metadata_codes,
        )
        report_data = select_report_data(
            data=data,
            requested_codes=requested_codes,
            resolved_codes=resolved_codes,
            preferred_frequency=self.preferred_frequency,
        )
        chart_data = report_data[report_data["period_start"] >= start_date].copy()
        summary = compute_latest_snapshot(report_data, requested_codes, resolved_codes)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        speeches_analysis = self._build_speeches_analysis(report_data)
        summary.to_csv(self.summary_csv_path, index=False)
        write_summary_json(
            summary=summary,
            path=self.summary_json_path,
            requested_codes=requested_codes,
            resolved_codes=resolved_codes,
            start=start,
            source_path=self.tidy_data_path,
            speeches_analysis=speeches_analysis,
        )
        write_policy_rate_chart(chart_data, self.chart_path, start)
        write_html_report(
            summary=summary,
            chart_path=self.chart_path,
            report_path=self.report_html_path,
            requested_codes=requested_codes,
            resolved_codes=resolved_codes,
            start=start,
            speeches_analysis=speeches_analysis,
        )

        return ReportResult(
            summary_csv_path=self.summary_csv_path,
            summary_json_path=self.summary_json_path,
            chart_path=self.chart_path,
            report_html_path=self.report_html_path,
            countries=requested_codes,
            rows_written=len(summary),
            speeches_chart_path=(
                speeches_analysis.chart_path if speeches_analysis is not None else None
            ),
        )

    def _build_speeches_analysis(
        self,
        report_data: pd.DataFrame,
    ) -> SpeechesAnalysis | None:
        if self.speeches_provider is None:
            self.speeches_chart_path.unlink(missing_ok=True)
            return None

        try:
            speeches_analysis = self.speeches_provider(report_data, self.speeches_chart_path)
        except Exception as error:
            log.warning("Skipping speeches extension: %s", error)
            self.speeches_chart_path.unlink(missing_ok=True)
            return None

        if speeches_analysis is None:
            self.speeches_chart_path.unlink(missing_ok=True)
        return speeches_analysis


def parse_country_codes(countries: Iterable[str]) -> list[str]:
    """Normalise a comma-separated string or iterable into uppercased codes."""
    raw_codes = countries.split(",") if isinstance(countries, str) else countries

    codes = []
    for code in raw_codes:
        clean_code = str(code).strip().upper()
        if clean_code:
            codes.append(clean_code)
    return codes


def load_tidy_data(path: Path) -> pd.DataFrame:
    """Read the tidy parquet and add helper columns used by the report."""
    if not path.exists():
        raise FileNotFoundError(
            f"Processed tidy dataset not found: {path}. Run 'bis-prates transform' first."
        )

    with _suppress_stderr_fd():
        data = pd.read_parquet(path)
    data["period_start"] = pd.to_datetime(data["period_start"], errors="coerce")
    data["obs_value_numeric"] = pd.to_numeric(data["obs_value"], errors="coerce")
    data["obs_value_clean"] = data["obs_value"].fillna("").astype(str).str.strip()
    return data


def resolve_country_codes(
    requested_codes: list[str],
    data: pd.DataFrame,
    metadata_codes: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Map requested codes to BIS codes, validating against SDMX metadata when available.

    Falls back to local-dataset validation if `metadata_codes` is `None`.
    Raises `ValueError` for codes that don't exist in the local dataset.
    """
    using_sdmx_metadata = metadata_codes is not None
    if metadata_codes is None:
        log.warning(
            "BIS SDMX metadata validation unavailable; falling back to local "
            "dataset code validation."
        )
        resolved = {code: COUNTRY_ALIASES.get(code, code) for code in requested_codes}
    else:
        resolved = validate_country_codes(requested_codes, metadata_codes)

    available_data_codes = set(data["ref_area_code"].dropna().astype(str).str.upper())
    for requested_code, actual_code in resolved.items():
        if actual_code not in available_data_codes:
            available = ", ".join(sorted(available_data_codes))
            if using_sdmx_metadata:
                raise ValueError(
                    f"Country code '{requested_code}' is valid in BIS metadata but has "
                    f"no policy-rate observations in the local dataset. Available "
                    f"local codes: {available}"
                )
            raise ValueError(
                f"Country code '{requested_code}' is not available in the local "
                f"policy-rate dataset. Available local codes: {available}"
            )

    return resolved


def select_report_data(
    data: pd.DataFrame,
    requested_codes: list[str],
    resolved_codes: dict[str, str],
    preferred_frequency: str,
) -> pd.DataFrame:
    """Filter the tidy dataset to the chosen countries and one frequency per country."""
    frames = []
    for requested_code in requested_codes:
        actual_code = resolved_codes[requested_code]
        country_data = data[data["ref_area_code"].eq(actual_code)].copy()
        country_data = country_data[_valid_observation_mask(country_data)]
        if country_data.empty:
            raise ValueError(f"No valid policy-rate observations for {requested_code}.")

        selected_frequency = _select_frequency(country_data, preferred_frequency)
        selected = country_data[country_data["freq_code"].eq(selected_frequency)].copy()
        selected["requested_code"] = requested_code
        selected = selected.sort_values("period_start")
        frames.append(selected)

    return pd.concat(frames, ignore_index=True)


def compute_latest_snapshot(
    report_data: pd.DataFrame,
    requested_codes: list[str],
    resolved_codes: dict[str, str],
) -> pd.DataFrame:
    """Build a per-country latest-observation summary with the change from the previous obs."""
    rows = []
    for requested_code in requested_codes:
        country_data = report_data[report_data["requested_code"].eq(requested_code)]
        if country_data.empty:
            continue

        latest = country_data.iloc[-1]
        previous = country_data.iloc[-2] if len(country_data) > 1 else None
        latest_rate = float(latest["obs_value_numeric"])
        previous_rate = float(previous["obs_value_numeric"]) if previous is not None else None
        change = latest_rate - previous_rate if previous_rate is not None else None

        rows.append(
            {
                "requested_code": requested_code,
                "ref_area_code": resolved_codes[requested_code],
                "ref_area": latest["ref_area"],
                "frequency": latest["frequency"],
                "latest_date": latest["period_start"].date().isoformat(),
                "latest_rate": latest_rate,
                "previous_date": (
                    previous["period_start"].date().isoformat() if previous is not None else ""
                ),
                "previous_rate": previous_rate,
                "change_from_previous": change,
                "unit_measure": latest["unit_measure"],
                "unit_mult": latest["unit_mult"],
                "decimals": latest["decimals"],
                "title": latest["title"],
                "source_ref": latest["source_ref"],
                "compilation": latest["compilation"],
                "obs_status_code": latest["obs_status_code"],
                "obs_status": latest["obs_status"],
            }
        )

    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def write_summary_json(
    summary: pd.DataFrame,
    path: Path,
    requested_codes: list[str],
    resolved_codes: dict[str, str],
    start: str,
    source_path: Path,
    speeches_analysis: SpeechesAnalysis | None = None,
) -> None:
    """Serialise the summary frame plus run metadata to a JSON file."""
    payload = {
        "generated_at_utc": _utc_now(),
        "source_path": str(source_path),
        "start": start,
        "requested_countries": requested_codes,
        "resolved_countries": resolved_codes,
        "rows": _json_records(summary),
    }
    if speeches_analysis is not None:
        payload["speeches_extension"] = {
            "chart_path": str(speeches_analysis.chart_path),
            "term_frequencies": _json_records(speeches_analysis.term_frequencies),
            "policy_moves": _json_records(speeches_analysis.policy_moves),
        }

    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_policy_rate_chart(
    chart_data: pd.DataFrame,
    chart_path: Path,
    start: str,
) -> None:
    """Render a multi-country policy-rate line chart to `chart_path`."""
    fig, ax = plt.subplots(figsize=(10, 5.5))

    if chart_data.empty:
        ax.text(0.5, 0.5, "No policy-rate data for selected period", ha="center")
        ax.set_axis_off()
    else:
        for requested_code, country_data in chart_data.groupby("requested_code"):
            label = f"{requested_code} - {country_data['ref_area'].iloc[0]}"
            ax.plot(
                country_data["period_start"],
                country_data["obs_value_numeric"],
                linewidth=1.8,
                label=label,
            )

        ax.set_title(f"Central bank policy rates since {start}")
        ax.set_xlabel("Date")
        ax.set_ylabel("Policy rate")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=8)

    fig.tight_layout()
    fig.savefig(chart_path, dpi=160)
    plt.close(fig)


def write_html_report(
    summary: pd.DataFrame,
    chart_path: Path,
    report_path: Path,
    requested_codes: list[str],
    resolved_codes: dict[str, str],
    start: str,
    speeches_analysis: SpeechesAnalysis | None = None,
) -> None:
    """Write a self-contained HTML report with the chart embedded as base64."""
    chart_b64 = base64.b64encode(chart_path.read_bytes()).decode("ascii")
    table_html = _summary_table_html(summary)
    speeches_html = _speeches_section_html(speeches_analysis)
    country_label = ", ".join(
        (code if resolved_codes[code] == code else f"{code} ({resolved_codes[code]})")
        for code in requested_codes
    )

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BIS Policy Rate Monitor</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2933; }}
    h1 {{ margin-bottom: 4px; }}
    h3 {{ margin-bottom: 0; }}
    .meta {{ color: #52606d; margin-top: 0; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #d9e2ec; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 24px; font-size: 13px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    td.numeric {{ text-align: right; }}
  </style>
</head>
<body>
  <h1>BIS Policy Rate Monitor</h1>
  <p class="meta">Countries: {html.escape(country_label)} | Chart start: {html.escape(start)} | Generated: {html.escape(_utc_now())}</p>
  <img src="data:image/png;base64,{chart_b64}" alt="Policy-rate chart">
  <h2>Latest Snapshot</h2>
  {table_html}
  {speeches_html}
</body>
</html>
"""
    report_path.write_text(document, encoding="utf-8")


def _valid_observation_mask(data: pd.DataFrame) -> pd.Series:
    return (
        data["obs_value_clean"].notna()
        & ~data["obs_value_clean"].isin(["", "NaN"])
        & data["obs_value_numeric"].notna()
        & ~data["obs_status_code"].eq("M")
    )


def _select_frequency(country_data: pd.DataFrame, preferred_frequency: str) -> str:
    if country_data["freq_code"].eq(preferred_frequency).any():
        return preferred_frequency
    return str(country_data["freq_code"].iloc[0])


def _json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    records = []
    for record in frame.to_dict("records"):
        records.append({key: _json_scalar(value) for key, value in record.items()})
    return records


def _json_scalar(value: object) -> object:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _summary_table_html(summary: pd.DataFrame) -> str:
    columns = [
        "requested_code",
        "ref_area",
        "frequency",
        "latest_date",
        "latest_rate",
        "change_from_previous",
        "unit_measure",
        "decimals",
        "title",
    ]
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    rows = []
    for _, row in summary.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            if pd.isna(value):
                rendered = ""
            elif column in {"latest_rate", "change_from_previous"}:
                rendered = f"{float(value):.4g}"
            else:
                rendered = str(value)
            css_class = (
                ' class="numeric"' if column in {"latest_rate", "change_from_previous"} else ""
            )
            cells.append(f"<td{css_class}>{html.escape(rendered)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _speeches_section_html(
    speeches_analysis: SpeechesAnalysis | None,
) -> str:
    if speeches_analysis is None:
        return ""

    chart_b64 = base64.b64encode(speeches_analysis.chart_path.read_bytes()).decode("ascii")
    term_table = _speech_terms_table_html(speeches_analysis.term_frequencies)
    month_label = _speech_month_label(speeches_analysis.term_frequencies)

    return f"""
  <h2>Speeches terms vs policy-rate moves</h2>
  <p>
    BIS central bankers' speeches for the last two years were scanned for fixed
    terms and aggregated by month. The chart compares those term counts with
    signed monthly policy-rate moves for each requested country.
    This is descriptive text analysis, not a causal model.
  </p>
  <p class="meta">Speech window: {html.escape(month_label)}.</p>
  <img src="data:image/png;base64,{chart_b64}" alt="Speech terms and policy-rate moves chart">
  <h3>Term totals</h3>
  {term_table}
"""


def _speech_terms_table_html(term_frequencies: pd.DataFrame) -> str:
    summary = term_frequency_summary(term_frequencies)
    columns = ["term", "mentions", "mentions_per_speech"]
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    rows = []
    for _, row in summary.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            rendered = f"{float(value):.2f}" if column == "mentions_per_speech" else str(value)
            css_class = ' class="numeric"' if column != "term" else ""
            cells.append(f"<td{css_class}>{html.escape(rendered)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _speech_month_label(term_frequencies: pd.DataFrame) -> str:
    if term_frequencies.empty:
        return "no recent speech data"
    first_month = pd.to_datetime(term_frequencies["month"].min()).strftime("%Y-%m")
    last_month = pd.to_datetime(term_frequencies["month"].max()).strftime("%Y-%m")
    return f"{first_month} to {last_month}"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextlib.contextmanager
def _suppress_stderr_fd() -> Iterator[None]:
    stderr_fd = 2
    saved_stderr_fd = os.dup(stderr_fd)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, stderr_fd)
        yield
    finally:
        os.dup2(saved_stderr_fd, stderr_fd)
        os.close(saved_stderr_fd)
        os.close(devnull_fd)
