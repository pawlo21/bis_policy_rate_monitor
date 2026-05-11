"""Unit tests for transformer speech sentiment scoring."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from bis_prates.speech_sentiment import SpeechSentimentAssessor


class SpeechSentimentTest(unittest.TestCase):
    """Speech-level and monthly transformer sentiment scoring."""

    def test_analyze_scores_each_speech_and_month(self) -> None:
        """Fake predictions produce speech-level and monthly net scores."""
        speeches = pd.DataFrame(
            {
                "date": ["2024-01-15", "2024-01-20", "2024-02-15"],
                "title": ["Hawkish speech", "Neutral speech", "Dovish speech"],
                "author": ["A", "B", "C"],
                "url": ["https://example.test/a", "", ""],
                "text": [
                    "Inflation remains elevated. Further tightening may be warranted.",
                    "Monetary policy remains data dependent.",
                    "Lower rates may support growth as disinflation continues.",
                ],
            }
        )
        assessor = SpeechSentimentAssessor(
            batch_size=2,
            pipeline_factory=lambda _model_name: _FakePipeline(),
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            chart_path = Path(tmp_dir) / "speeches_sentiment.png"
            analysis = assessor.analyze(speeches, chart_path)

            assert analysis is not None
            self.assertTrue(chart_path.exists())
            self.assertGreater(chart_path.stat().st_size, 0)

        self.assertEqual(len(analysis.speech_scores), 3)
        january = analysis.monthly_scores[
            analysis.monthly_scores["month"].eq(pd.Timestamp("2024-01-01"))
        ].iloc[0]
        february = analysis.monthly_scores[
            analysis.monthly_scores["month"].eq(pd.Timestamp("2024-02-01"))
        ].iloc[0]
        self.assertEqual(int(january["speech_count"]), 2)
        self.assertGreater(january["net_hawkish_score"], 0)
        self.assertLess(february["net_hawkish_score"], 0)


class _FakePipeline:
    """Minimal fake Hugging Face pipeline used by tests."""

    def __call__(
        self,
        texts: list[str],
        batch_size: int = 16,
        truncation: bool = True,
    ) -> list[dict[str, object]]:
        """Return deterministic labels from keywords."""
        predictions = []
        for text in texts:
            lower_text = text.lower()
            if "lower rates" in lower_text or "disinflation" in lower_text:
                predictions.append({"label": "LABEL_1", "score": 0.91})
            elif "tightening" in lower_text or "elevated" in lower_text:
                predictions.append({"label": "LABEL_2", "score": 0.93})
            else:
                predictions.append({"label": "LABEL_0", "score": 0.8})
        return predictions


if __name__ == "__main__":
    unittest.main()
