"""HTML report rendering (self-contained document with the chart embedded as base64)."""

from __future__ import annotations

import base64
import html
from pathlib import Path

import pandas as pd

from bis_prates.report.json_writer import utc_now
from bis_prates.speeches import SpeechesAnalysis, term_frequency_summary


def write_html_report(
    *,
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
  <p class="meta">Countries: {html.escape(country_label)} | Chart start: {html.escape(start)} | Generated: {html.escape(utc_now())}</p>
  <img src="data:image/png;base64,{chart_b64}" alt="Policy-rate chart">
  <h2>Latest Snapshot</h2>
  {table_html}
  <p class="meta">
    <em>change_from_previous</em> is the delta between the two latest valid
    observations of the selected frequency, not a fixed period-over-period
    change. See <em>latest_date</em> vs the underlying <code>previous_date</code>
    column in the CSV/JSON for the actual gap.
  </p>
  {speeches_html}
</body>
</html>
"""
    report_path.write_text(document, encoding="utf-8")


def _summary_table_html(summary: pd.DataFrame) -> str:
    columns = [
        "requested_code",
        "ref_area",
        "frequency",
        "latest_date",
        "latest_rate",
        "days_since_latest",
        "change_from_previous",
        "unit_measure",
        "decimals",
        "title",
    ]
    numeric_columns = {"latest_rate", "change_from_previous", "days_since_latest"}
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
            elif column == "days_since_latest":
                rendered = str(int(value))
            else:
                rendered = str(value)
            css_class = ' class="numeric"' if column in numeric_columns else ""
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
    sentiment_html = _speech_sentiment_html(speeches_analysis)

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
  {sentiment_html}
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


def _speech_sentiment_html(speeches_analysis: SpeechesAnalysis) -> str:
    sentiment = speeches_analysis.sentiment_analysis
    if sentiment is None or sentiment.speech_scores.empty:
        return ""

    chart_b64 = base64.b64encode(sentiment.chart_path.read_bytes()).decode("ascii")
    monthly_table = _sentiment_monthly_table_html(sentiment.monthly_scores)
    speech_table = _sentiment_speech_table_html(sentiment.speech_scores)
    return f"""
  <h2>Transformer speech sentiment assessment</h2>
  <p>
    Policy-relevant sentences were classified with
    <code>{html.escape(sentiment.model_name)}</code>. The score is
    <code>(hawkish sentences - dovish sentences) / classified sentences</code>,
    so positive values are more hawkish and negative values are more dovish.
    Monthly values average the per-speech scores, so long speeches do not dominate.
  </p>
  <img src="data:image/png;base64,{chart_b64}" alt="Transformer speech sentiment chart">
  <h3>Monthly transformer score</h3>
  {monthly_table}
  <h3>Recent speech scores</h3>
  {speech_table}
"""


def _sentiment_monthly_table_html(monthly_scores: pd.DataFrame) -> str:
    columns = [
        "month",
        "speech_count",
        "sentence_count",
        "net_hawkish_score",
        "hawkish_share",
        "dovish_share",
        "average_confidence",
    ]
    numeric_columns = set(columns) - {"month"}
    rows = []
    for _, row in monthly_scores.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            if column == "month":
                rendered = pd.to_datetime(value).strftime("%Y-%m")
            elif column in {"speech_count", "sentence_count"}:
                rendered = str(int(value))
            else:
                rendered = f"{float(value):.2f}"
            css_class = ' class="numeric"' if column in numeric_columns else ""
            cells.append(f"<td{css_class}>{html.escape(rendered)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _sentiment_speech_table_html(speech_scores: pd.DataFrame, limit: int = 12) -> str:
    columns = [
        "date",
        "title",
        "dominant_stance",
        "net_hawkish_score",
        "hawkish_share",
        "dovish_share",
        "sentence_count",
    ]
    numeric_columns = {"net_hawkish_score", "hawkish_share", "dovish_share", "sentence_count"}
    rows = []
    recent = speech_scores.sort_values("date", ascending=False).head(limit)
    for _, row in recent.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            if column == "date":
                rendered = pd.to_datetime(value).date().isoformat()
            elif column == "title":
                rendered = _short_text(str(value), 90)
            elif column == "sentence_count":
                rendered = str(int(value))
            elif column in numeric_columns:
                rendered = f"{float(value):.2f}"
            else:
                rendered = str(value)
            css_class = ' class="numeric"' if column in numeric_columns else ""
            cells.append(f"<td{css_class}>{html.escape(rendered)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _short_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
