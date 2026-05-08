from __future__ import annotations

import unittest

from bis_prates.cli import build_parser


class CliTest(unittest.TestCase):
    def test_report_speeches_flag_defaults_to_false(self) -> None:
        args = build_parser().parse_args(
            [
                "report",
                "--countries",
                "US,EA",
                "--start",
                "2015-01-01",
            ]
        )

        self.assertFalse(args.speeches)

    def test_report_speeches_flag_accepts_true(self) -> None:
        args = build_parser().parse_args(
            [
                "report",
                "--countries",
                "US,EA",
                "--start",
                "2015-01-01",
                "--speeches=true",
            ]
        )

        self.assertTrue(args.speeches)


if __name__ == "__main__":
    unittest.main()
