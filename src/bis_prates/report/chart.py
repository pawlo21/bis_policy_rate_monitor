"""Matplotlib chart rendering for the policy-rate report."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# MPLCONFIGDIR and ARROW_USER_SIMD_LEVEL must be set before matplotlib is
# imported, so the imports below intentionally appear after the env setup.
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

import matplotlib  # noqa: E402  # pylint: disable=wrong-import-position

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  # pylint: disable=wrong-import-position
import pandas as pd  # noqa: E402  # pylint: disable=wrong-import-position


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
