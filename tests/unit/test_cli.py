"""Unit tests for the `bis-prates` CLI argument parser."""

from __future__ import annotations

import unittest

from bis_prates.cli import build_parser


class CliTest(unittest.TestCase):
    """CLI argument parsing."""

    def test_report_speeches_flag_defaults_to_false(self) -> None:
        """`--speeches` defaults to false when omitted."""
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
        """`--speeches=true` enables the speeches extension."""
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

    def test_report_assess_sentiment_flag_accepts_true(self) -> None:
        """`--assess-sentiment` enables transformer speech assessment."""
        args = build_parser().parse_args(
            [
                "report",
                "--countries",
                "US,EA",
                "--start",
                "2015-01-01",
                "--speeches=true",
                "--assess-sentiment",
            ]
        )

        self.assertTrue(args.assess_sentiment)

    def test_report_sentiment_speed_options_are_parsed(self) -> None:
        """Transformer sentence limit and batch size are configurable."""
        args = build_parser().parse_args(
            [
                "report",
                "--countries",
                "US,EA",
                "--start",
                "2015-01-01",
                "--speeches=true",
                "--assess-sentiment",
                "--sentiment-sentences-per-speech",
                "12",
                "--sentiment-batch-size",
                "64",
            ]
        )

        self.assertEqual(args.sentiment_sentences_per_speech, 12)
        self.assertEqual(args.sentiment_batch_size, 64)


if __name__ == "__main__":
    unittest.main()
