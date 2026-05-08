"""Command line interface for BIS Policy Rate Monitor."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional, Sequence

from bis_prates.fetch import BisBulkFetcher
from bis_prates.report import PolicyRateReporter
from bis_prates.transform import PolicyRateTransformer


LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bis-prates",
        description=(
            "BIS Policy Rate Monitor: download BIS policy-rate data, "
            "transform it into a tidy dataset, and generate country reports."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="download and cache the latest BIS policy-rate ZIP",
        description=(
            "Discover and download the latest 'Central bank policy rates "
            "(CSV, flat)' ZIP from the BIS Data Portal Bulk downloads page."
        ),
    )
    fetch_parser.set_defaults(func=_fetch)

    transform_parser = subparsers.add_parser(
        "transform",
        help="parse raw BIS data into a tidy dataset",
        description="Parse, clean, deduplicate, and tidy the cached BIS policy-rate data.",
    )
    transform_parser.set_defaults(func=_transform)

    report_parser = subparsers.add_parser(
        "report",
        help="generate summary outputs and an HTML report",
        description=(
            "Generate a latest snapshot summary and report for a comma-separated "
            "list of countries."
        ),
    )
    report_parser.add_argument(
        "--countries",
        required=True,
        metavar="CODES",
        help='comma-separated country or area codes, for example "US,EA,GB,JP,CH"',
    )
    report_parser.add_argument(
        "--start",
        required=True,
        metavar="YYYY-MM-DD",
        help='start date for the report time series, for example "2015-01-01"',
    )
    report_parser.set_defaults(func=_report)

    return parser


def _fetch(args: argparse.Namespace) -> int:
    try:
        result = BisBulkFetcher().fetch()
    except Exception as error:
        print(f"Fetch failed: {error}", file=sys.stderr)
        return 1

    if result.downloaded:
        print(f"Downloaded {result.dataset.label}: {result.archive_path}")
    else:
        print(f"Using cached {result.dataset.label}: {result.archive_path}")

    if result.dataset.release_date:
        print(f"Release date: {result.dataset.release_date}")

    print(f"Source URL: {result.dataset.url}")
    print(f"Cache manifest: {result.manifest_path}")
    return 0


def _transform(args: argparse.Namespace) -> int:
    try:
        result = PolicyRateTransformer().transform()
    except Exception as error:
        print(f"Transform failed: {error}", file=sys.stderr)
        return 1

    print(f"Transformed raw archive: {result.archive_path}")
    print(f"Tidy dataset: {result.output_path}")
    print(f"Transform manifest: {result.manifest_path}")
    print(f"Rows read: {result.rows_read}")
    print(f"Rows written: {result.rows_written}")
    print(f"Duplicates dropped: {result.duplicates_dropped}")
    print(f"Missing observations logged: {result.missing_observation_rows}")
    return 0


def _report(args: argparse.Namespace) -> int:
    try:
        result = PolicyRateReporter().report(
            countries=args.countries,
            start=args.start,
        )
    except Exception as error:
        print(f"Report failed: {error}", file=sys.stderr)
        return 1

    print(f"Summary CSV: {result.summary_csv_path}")
    print(f"Summary JSON: {result.summary_json_path}")
    print(f"Chart: {result.chart_path}")
    print(f"HTML report: {result.report_html_path}")
    print(f"Snapshot rows: {result.rows_written}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    parser = build_parser()
    args_list = list(argv) if argv is not None else sys.argv[1:]

    if not args_list:
        parser.print_help()
        return 0

    args = parser.parse_args(args_list)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
