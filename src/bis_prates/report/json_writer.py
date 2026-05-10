"""JSON serialisation of the policy-rate summary plus run metadata."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bis_prates.speeches import SpeechesAnalysis


def write_summary_json(
    *,
    summary: pd.DataFrame,
    path: Path,
    requested_codes: list[str],
    resolved_codes: dict[str, str],
    start: str,
    source_path: Path,
    speeches_analysis: SpeechesAnalysis | None = None,
) -> None:
    """Serialise the summary frame plus run metadata to a JSON file.

    Note: `change_from_previous` in each row is the delta between the last two
    valid observations of the selected frequency. The accompanying
    `previous_date` reveals the actual gap (which may exceed one period when the
    series has missing observations).
    """
    payload = {
        "generated_at_utc": utc_now(),
        "source_path": str(source_path),
        "start": start,
        "requested_countries": requested_codes,
        "resolved_countries": resolved_codes,
        "rows": json_records(summary),
    }
    if speeches_analysis is not None:
        payload["speeches_extension"] = {
            "chart_path": str(speeches_analysis.chart_path),
            "term_frequencies": json_records(speeches_analysis.term_frequencies),
            "policy_moves": json_records(speeches_analysis.policy_moves),
        }

    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Convert a DataFrame to JSON-safe records (NaNs to None, Timestamps to ISO dates)."""
    records = []
    for record in frame.to_dict("records"):
        records.append({key: _json_scalar(value) for key, value in record.items()})
    return records


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string with 'Z' suffix."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_scalar(value: object) -> object:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value
