"""Mini NLP extension for BIS central bankers' speeches.

The exercise asks for a lightweight comparison between recent BIS speeches and
observed policy-rate moves. This module deliberately keeps the NLP simple:
count a fixed set of terms in the last two years of speeches, aggregate those
counts by month, and plot them next to monthly policy-rate moves.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from bis_prates.speech_sentiment import SpeechSentimentAnalysis, SpeechSentimentAssessor

log = logging.getLogger(__name__)

BIS_SPEECHES_BASE_URL = "https://www.bis.org/speeches/"
GINGADO_CACHE_DIR = Path("data/raw/gingado")
HTTP_TIMEOUT_SECONDS = 30
LOOKBACK_YEARS = 2
MAX_ZIP_BYTES = 50_000_000
MAX_CSV_BYTES = 100_000_000
SPEECH_TERMS = ("inflation", "rate", "tightening")
USER_AGENT = "bis-policy-rate-monitor/0.1"

# Keep the search terms explicit. These are transparent hand-written term
# families, not a semantic model. Multi-word phrases are listed before generic
# words so "policy rate" is counted once, not again as a standalone "rate".
TERM_PATTERNS = {
    "inflation": (
        r"\binflation(?:ary)?\b" r"|\bconsumer prices?\b" r"|\bprice stability\b" r"|\bcpi\b"
    ),
    "rate": (r"\bpolicy rates?\b" r"|\binterest rates?\b" r"|\bbank rates?\b" r"|\brates?\b"),
    "tightening": (
        r"\btighten(?:ing|ed|s)?\b" r"|\btighter\b" r"|\bhik(?:e|es|ed|ing)\b" r"|\brestrictive\b"
    ),
}


@dataclass(frozen=True)
class SpeechesAnalysis:
    """Output of the lexicon-based speeches extension: chart path plus the underlying tables."""

    chart_path: Path
    term_frequencies: pd.DataFrame
    policy_moves: pd.DataFrame
    sentiment_analysis: SpeechSentimentAnalysis | None = None


def build_speeches_analysis(
    policy_rate_data: pd.DataFrame,
    chart_path: Path,
    *,
    today: datetime | None = None,
    assess_sentiment: bool = False,
    sentiment_batch_size: int = 32,
    sentiment_sentences_per_speech: int | None = 12,
) -> SpeechesAnalysis | None:
    """Build the speeches extension output, returning None when no data loads."""
    speeches = load_recent_speeches(today=today)
    if speeches.empty:
        log.warning("Skipping speeches extension because no recent speeches were loaded.")
        return None

    term_frequencies = compute_term_frequencies(speeches)
    if term_frequencies.empty:
        log.warning("Skipping speeches extension because no term frequencies were found.")
        return None

    policy_moves = compute_monthly_policy_moves(
        policy_rate_data,
        start=term_frequencies["month"].min(),
    )
    render_speeches_chart(term_frequencies, policy_moves, chart_path)
    sentiment_analysis = None
    if assess_sentiment:
        try:
            sentiment_analysis = SpeechSentimentAssessor(
                batch_size=sentiment_batch_size,
                max_sentences_per_speech=sentiment_sentences_per_speech,
            ).analyze(
                speeches=speeches,
                chart_path=chart_path.with_name("speeches_sentiment.png"),
            )
        # Transformer dependencies or model downloads should not break the
        # required policy-rate report; the optional section is skipped instead.
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.warning("Skipping transformer speech sentiment assessment: %s", error)

    return SpeechesAnalysis(
        chart_path=chart_path,
        term_frequencies=term_frequencies,
        policy_moves=policy_moves,
        sentiment_analysis=sentiment_analysis,
    )


def load_recent_speeches(
    today: datetime | None = None,
    lookback_years: int = LOOKBACK_YEARS,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    """Load BIS speeches for the last ``lookback_years`` years.

    We prefer gingado because BIS points users to it for programmatic access.
    The installed gingado release does not import under Python 3.9, so this
    function falls back to the same yearly BIS ZIP files that gingado uses.
    """
    today_ts = _normalise_today(today)
    cutoff = today_ts - pd.DateOffset(years=lookback_years)
    years = list(range(cutoff.year, today_ts.year + 1))

    frames: list[pd.DataFrame] = []
    for year in years:
        log.info("Loading BIS speeches for %s.", year)
        try:
            raw = _load_speeches_year(year, timeout=timeout)
        except (URLError, RuntimeError, zipfile.BadZipFile, ValueError) as error:
            log.warning("Could not load BIS speeches for %s: %s", year, error)
            continue

        normalised = normalise_speech_frame(raw)
        if not normalised.empty:
            frames.append(normalised)

    if not frames:
        return _empty_speeches_frame()

    speeches = pd.concat(frames, ignore_index=True)
    speeches = speeches[speeches["date"].between(cutoff, today_ts, inclusive="both")].copy()
    speeches = speeches.sort_values("date").reset_index(drop=True)
    log.info("Loaded %d BIS speeches since %s.", len(speeches), cutoff.date())
    return speeches


def normalise_speech_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a stable speech schema from a BIS/gingado speech frame."""
    if frame.empty:
        return _empty_speeches_frame()

    date_col = _find_column(frame, ["date", "publication_date", "published"])
    text_col = _find_column(frame, ["text", "speech", "content"])
    if date_col is None or text_col is None:
        raise ValueError("Speech data is missing required date/text columns.")

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_col], errors="coerce").dt.tz_localize(None),
            "text": frame[text_col].fillna("").astype(str),
        }
    )
    for optional_col in ["title", "description", "author", "url"]:
        source_col = _find_column(frame, [optional_col])
        if source_col is not None:
            out[optional_col] = frame[source_col].fillna("").astype(str)

    out = out.dropna(subset=["date"])
    out = out[out["text"].str.strip().ne("")]
    return out.reset_index(drop=True)


def compute_term_frequencies(
    speeches: pd.DataFrame,
    terms: Sequence[str] = SPEECH_TERMS,
) -> pd.DataFrame:
    """Count fixed speech terms by month."""
    columns = ["month", "speech_count", *terms, "total_term_hits"]
    if speeches.empty:
        return pd.DataFrame(columns=columns)

    data = speeches.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["text"] = data["text"].fillna("").astype(str).str.lower()
    data = data.dropna(subset=["date"])
    if data.empty:
        return pd.DataFrame(columns=columns)

    counts = pd.DataFrame(
        {
            "month": data["date"].dt.to_period("M").dt.to_timestamp(),
            "speech_count": 1,
        }
    )
    for term in terms:
        pattern = TERM_PATTERNS.get(term, rf"\b{re.escape(term)}\b")
        counts[term] = data["text"].str.count(pattern)

    monthly = counts.groupby("month", as_index=False).sum()
    monthly["total_term_hits"] = monthly[list(terms)].sum(axis=1)
    return monthly.sort_values("month").reset_index(drop=True)


def compute_monthly_policy_moves(
    policy_rate_data: pd.DataFrame,
    start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Compute signed monthly policy-rate moves by country in basis points.

    Policy rates are stored as percentages, so a 0.25 percentage-point move is
    multiplied by 100 and reported as 25 basis points. Cuts remain negative.
    """
    columns = ["month", "requested_code", "policy_move_bps"]
    if policy_rate_data.empty:
        return pd.DataFrame(columns=columns)

    data = policy_rate_data[["requested_code", "period_start", "obs_value_numeric"]].copy()
    data["period_start"] = pd.to_datetime(data["period_start"], errors="coerce")
    data["obs_value_numeric"] = pd.to_numeric(data["obs_value_numeric"], errors="coerce")
    data = data.dropna(subset=["requested_code", "period_start", "obs_value_numeric"])
    if start is not None:
        data = data[data["period_start"] >= pd.Timestamp(start)]
    if data.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for requested_code, country_data in data.groupby("requested_code"):
        country_data = country_data.sort_values("period_start")
        monthly_rate = (
            country_data.drop_duplicates("period_start", keep="last")
            .set_index("period_start")["obs_value_numeric"]
            .resample("MS")
            .last()
            .ffill()
        )
        monthly_move_bps = monthly_rate.diff() * 100.0
        for month, move_bps in monthly_move_bps.dropna().items():
            rows.append(
                {
                    "month": month,
                    "requested_code": requested_code,
                    "policy_move_bps": float(move_bps),
                }
            )

    moves = pd.DataFrame(rows)
    if moves.empty:
        return pd.DataFrame(columns=columns)

    return moves.sort_values(["month", "requested_code"]).reset_index(drop=True)


def term_frequency_summary(
    term_frequencies: pd.DataFrame,
    terms: Sequence[str] = SPEECH_TERMS,
) -> pd.DataFrame:
    """Small table of total mentions and mentions per speech."""
    total_speeches = int(term_frequencies.get("speech_count", pd.Series(dtype=int)).sum())
    rows = []
    for term in terms:
        mentions = int(term_frequencies[term].sum()) if term in term_frequencies else 0
        rows.append(
            {
                "term": term,
                "mentions": mentions,
                "mentions_per_speech": (
                    round(mentions / total_speeches, 2) if total_speeches else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def render_speeches_chart(
    term_frequencies: pd.DataFrame,
    policy_moves: pd.DataFrame,
    chart_path: Path,
    terms: Sequence[str] = SPEECH_TERMS,
) -> None:
    """Write a side-by-side chart of speech term counts and policy moves."""
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    fig, (terms_ax, moves_ax) = plt.subplots(
        2,
        1,
        figsize=(10, 6),
        sharex=True,
    )

    if term_frequencies.empty:
        terms_ax.text(0.5, 0.5, "No recent speeches loaded", ha="center")
        terms_ax.set_axis_off()
    else:
        for term in terms:
            if term in term_frequencies:
                terms_ax.plot(
                    term_frequencies["month"],
                    term_frequencies[term],
                    marker="o",
                    linewidth=1.6,
                    label=term,
                )
        terms_ax.set_title("BIS speech term mentions by month")
        terms_ax.set_ylabel("Mentions")
        terms_ax.grid(True, alpha=0.3)
        terms_ax.legend(loc="best", fontsize=8)

    if policy_moves.empty:
        moves_ax.text(0.5, 0.5, "No monthly policy-rate moves", ha="center")
        moves_ax.set_axis_off()
    else:
        moves = policy_moves.copy()
        moves["month"] = pd.to_datetime(moves["month"], errors="coerce")
        moves = moves.dropna(subset=["month", "requested_code", "policy_move_bps"])
        country_codes = sorted(moves["requested_code"].astype(str).unique())
        bar_width_days = 24 / max(len(country_codes), 1)

        for index, country_code in enumerate(country_codes):
            country_moves = moves[moves["requested_code"].eq(country_code)].sort_values("month")
            offset_days = (index - (len(country_codes) - 1) / 2) * bar_width_days
            x_values = mdates.date2num(country_moves["month"]) + offset_days
            moves_ax.bar(
                x_values,
                country_moves["policy_move_bps"],
                width=bar_width_days * 0.85,
                alpha=0.75,
                label=country_code,
            )

        moves_ax.axhline(0, color="#52606d", linewidth=0.8)
        moves_ax.xaxis_date()
        moves_ax.set_title("Monthly policy-rate moves by country")
        moves_ax.set_ylabel("Basis points")
        moves_ax.grid(True, axis="y", alpha=0.3)
        moves_ax.legend(loc="best", fontsize=8)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(chart_path, dpi=160)
    plt.close(fig)


def _load_speeches_year(year: int, timeout: int) -> pd.DataFrame:
    try:
        # gingado is an optional dependency; importing inside the try block
        # lets us fall back to a direct BIS ZIP download when it is missing,
        # without forcing every user to install the heavy ML extras.
        from gingado import datasets as gingado_datasets  # pylint: disable=import-outside-toplevel

        GINGADO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        gingado_datasets.CACHE_DIRECTORY = str(GINGADO_CACHE_DIR)
        return gingado_datasets.load_CB_speeches(year=year, cache=True, timeout=timeout)
    except (ImportError, OSError, AttributeError, RuntimeError, ValueError) as error:
        log.warning(
            "gingado could not load BIS speeches for %s (%s); trying direct BIS ZIP.",
            year,
            error,
        )
    return _download_speeches_year(year, timeout=timeout)


def _download_speeches_year(year: int, timeout: int) -> pd.DataFrame:
    url = f"{BIS_SPEECHES_BASE_URL}speeches_{year}.zip"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - hardcoded https BIS endpoint
        payload = response.read(MAX_ZIP_BYTES + 1)
    if len(payload) > MAX_ZIP_BYTES:
        raise RuntimeError(f"BIS speeches ZIP for {year} exceeds the size limit.")

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_name = _select_speeches_csv(archive, year)
        csv_info = archive.getinfo(csv_name)
        if csv_info.file_size > MAX_CSV_BYTES:
            raise RuntimeError(f"BIS speeches CSV for {year} exceeds the size limit.")
        return _read_speeches_csv(archive, csv_name, year)


def _read_speeches_csv(archive: zipfile.ZipFile, csv_name: str, year: int) -> pd.DataFrame:
    # BIS speech CSVs are usually UTF-8 but occasional translated content has
    # arrived as Latin-1. Re-open for the fallback because pandas may have
    # consumed part of the stream before the decode error surfaced.
    for encoding in ("utf-8", "latin-1"):
        try:
            with archive.open(csv_name) as csv_file:
                return pd.read_csv(csv_file, encoding=encoding)
        except UnicodeDecodeError as error:
            log.warning(
                "Decoding BIS speeches CSV for %s as %s failed: %s",
                year,
                encoding,
                error,
            )
    raise UnicodeDecodeError(
        "utf-8",
        b"",
        0,
        0,
        f"Could not decode BIS speeches CSV for {year} as UTF-8 or Latin-1.",
    )


def _select_speeches_csv(archive: zipfile.ZipFile, year: int) -> str:
    expected_name = f"speeches_{year}.csv"
    names = archive.namelist()
    if expected_name in names:
        return expected_name

    csv_names = [name for name in names if name.lower().endswith(".csv")]
    if not csv_names:
        raise ValueError("BIS speeches ZIP did not contain a CSV file.")
    return max(csv_names, key=lambda name: archive.getinfo(name).file_size)


def _find_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    by_lower = {str(column).strip().lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None


def _normalise_today(today: datetime | None) -> pd.Timestamp:
    value = today if today is not None else datetime.now(UTC)
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    return timestamp.normalize()


def _empty_speeches_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "text", "title", "description", "author", "url"])
