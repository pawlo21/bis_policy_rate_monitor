"""Command line interface for BIS Policy Rate Monitor."""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from bis_prates.fetch import BisBulkFetcher


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
    return 0


def _report(args: argparse.Namespace) -> int:
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args_list = list(argv) if argv is not None else sys.argv[1:]

    if not args_list:
        parser.print_help()
        return 0

    args = parser.parse_args(args_list)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
