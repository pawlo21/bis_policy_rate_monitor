"""Top-level orchestrator: `PolicyRateReporter` ties data, JSON, chart, and HTML together."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bis_prates.metadata import fetch_reference_area_codes
from bis_prates.report.chart import write_policy_rate_chart
from bis_prates.report.data import (
    compute_latest_snapshot,
    load_tidy_data,
    resolve_country_codes,
    select_report_data,
)
from bis_prates.report.html_writer import write_html_report
from bis_prates.report.json_writer import write_summary_json
from bis_prates.speeches import SpeechesAnalysis

log = logging.getLogger(__name__)

DEFAULT_TIDY_DATA_PATH = Path("data/processed/policy_rates_tidy.parquet")
DEFAULT_OUTPUT_DIR = Path("out")
SUMMARY_CSV_NAME = "summary.csv"
SUMMARY_JSON_NAME = "summary.json"
CHART_NAME = "policy_rates.png"
SPEECHES_CHART_NAME = "speeches_terms.png"
SPEECH_SENTIMENT_CHART_NAME = "speeches_sentiment.png"
REPORT_HTML_NAME = "report.html"
PREFERRED_FREQUENCY = "D"


@dataclass(frozen=True)
class ReportResult:  # pylint: disable=too-many-instance-attributes
    """Paths and counts produced by `PolicyRateReporter.report()`."""

    summary_csv_path: Path
    summary_json_path: Path
    chart_path: Path
    report_html_path: Path
    countries: list[str]
    rows_written: int
    speeches_chart_path: Path | None = None
    speech_sentiment_chart_path: Path | None = None


@dataclass(frozen=True)
class _OutputPaths:
    """Output filenames derived from the report's `output_dir`.

    Bundled as a small frozen dataclass so `PolicyRateReporter` keeps the
    five derived paths as one logical attribute (`self.paths`) rather than
    five separate ones.
    """

    summary_csv: Path
    summary_json: Path
    chart: Path
    speeches_chart: Path
    speech_sentiment_chart: Path
    report_html: Path

    @classmethod
    def under(cls, output_dir: Path) -> _OutputPaths:
        """Build the path bundle for the given `output_dir`."""
        return cls(
            summary_csv=output_dir / SUMMARY_CSV_NAME,
            summary_json=output_dir / SUMMARY_JSON_NAME,
            chart=output_dir / CHART_NAME,
            speeches_chart=output_dir / SPEECHES_CHART_NAME,
            speech_sentiment_chart=output_dir / SPEECH_SENTIMENT_CHART_NAME,
            report_html=output_dir / REPORT_HTML_NAME,
        )


class PolicyRateReporter:
    """Create the report outputs required by the exercise."""

    def __init__(
        self,
        *,
        tidy_data_path: Path = DEFAULT_TIDY_DATA_PATH,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        preferred_frequency: str = PREFERRED_FREQUENCY,
        metadata_provider: Callable[[], Mapping[str, str] | None] = fetch_reference_area_codes,
        speeches_provider: Callable[[pd.DataFrame, Path], SpeechesAnalysis | None] | None = None,
    ) -> None:
        """Configure paths and the metadata/speeches providers (injected for tests)."""
        self.tidy_data_path = Path(tidy_data_path)
        self.output_dir = Path(output_dir)
        self.preferred_frequency = preferred_frequency
        self.metadata_provider = metadata_provider
        self.speeches_provider = speeches_provider
        self.paths = _OutputPaths.under(self.output_dir)

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
        summary.to_csv(self.paths.summary_csv, index=False)
        write_summary_json(
            summary=summary,
            path=self.paths.summary_json,
            requested_codes=requested_codes,
            resolved_codes=resolved_codes,
            start=start,
            source_path=self.tidy_data_path,
            speeches_analysis=speeches_analysis,
        )
        write_policy_rate_chart(chart_data, self.paths.chart, start)
        write_html_report(
            summary=summary,
            chart_path=self.paths.chart,
            report_path=self.paths.report_html,
            requested_codes=requested_codes,
            resolved_codes=resolved_codes,
            start=start,
            speeches_analysis=speeches_analysis,
        )

        return ReportResult(
            summary_csv_path=self.paths.summary_csv,
            summary_json_path=self.paths.summary_json,
            chart_path=self.paths.chart,
            report_html_path=self.paths.report_html,
            countries=requested_codes,
            rows_written=len(summary),
            speeches_chart_path=(
                speeches_analysis.chart_path if speeches_analysis is not None else None
            ),
            speech_sentiment_chart_path=(
                speeches_analysis.sentiment_analysis.chart_path
                if (
                    speeches_analysis is not None
                    and speeches_analysis.sentiment_analysis is not None
                )
                else None
            ),
        )

    def _build_speeches_analysis(
        self,
        report_data: pd.DataFrame,
    ) -> SpeechesAnalysis | None:
        if self.speeches_provider is None:
            self.paths.speeches_chart.unlink(missing_ok=True)
            self.paths.speech_sentiment_chart.unlink(missing_ok=True)
            return None

        try:
            speeches_analysis = self.speeches_provider(report_data, self.paths.speeches_chart)
        # The speeches provider is an injected callable that may originate
        # from anywhere in user code; treat any failure as "extension skipped"
        # rather than letting a third-party error abort the main report.
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.warning("Skipping speeches extension: %s", error)
            self.paths.speeches_chart.unlink(missing_ok=True)
            self.paths.speech_sentiment_chart.unlink(missing_ok=True)
            return None

        if speeches_analysis is None:
            self.paths.speeches_chart.unlink(missing_ok=True)
            self.paths.speech_sentiment_chart.unlink(missing_ok=True)
        elif speeches_analysis.sentiment_analysis is None:
            self.paths.speech_sentiment_chart.unlink(missing_ok=True)
        return speeches_analysis


def parse_country_codes(countries: Iterable[str]) -> list[str]:
    """Normalise a comma-separated string or iterable into uppercased codes."""
    raw_codes = countries.split(",") if isinstance(countries, str) else countries
    return [clean for clean in (str(code).strip().upper() for code in raw_codes) if clean]
