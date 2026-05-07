"""Command line interface for BIS Policy Rate Monitor."""

from __future__ import annotations

import argparse
from typing import Optional, Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bis-prates")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.set_defaults(func=_fetch)

    transform_parser = subparsers.add_parser("transform")
    transform_parser.set_defaults(func=_transform)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--countries", required=True)
    report_parser.add_argument("--start", required=True)
    report_parser.set_defaults(func=_report)

    return parser


def _fetch(args: argparse.Namespace) -> int:
    return 0


def _transform(args: argparse.Namespace) -> int:
    return 0


def _report(args: argparse.Namespace) -> int:
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
