"""Data-pipeline helpers for the policy-rate report (load/resolve/select/compute)."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator, Mapping
from pathlib import Path

import pandas as pd

from bis_prates.metadata import COUNTRY_ALIASES, validate_country_codes

log = logging.getLogger(__name__)

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
