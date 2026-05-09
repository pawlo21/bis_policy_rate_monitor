from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from bis_prates.speech_transformer import TransformerSpeechClassifier


class SpeechTransformerTest(unittest.TestCase):
    def test_analyze_classifies_policy_sentences_and_writes_chart(self) -> None:
        speeches = pd.DataFrame(
            {
                "date": ["2024-01-15", "2024-02-15"],
                "text": [
                    "Welcome to the conference. Inflation remains elevated. Further tightening may be warranted.",
                    "Lower rates may support growth as disinflation continues.",
                ],
            }
        )
        classifier = TransformerSpeechClassifier(
            pipeline_factory=lambda _model_name: _FakePipeline(),
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            chart_path = Path(tmp_dir) / "speeches_transformer.png"
            analysis = classifier.analyze(speeches, chart_path)

            self.assertIsNotNone(analysis)
            assert analysis is not None
            self.assertEqual(analysis.model_name, "brjoey/CBSI-CentralBank-BERT")
            self.assertTrue(chart_path.exists())
            self.assertGreater(chart_path.stat().st_size, 0)

            january = analysis.monthly_stance[
                analysis.monthly_stance["month"].eq(pd.Timestamp("2024-01-01"))
            ].iloc[0]
            february = analysis.monthly_stance[
                analysis.monthly_stance["month"].eq(pd.Timestamp("2024-02-01"))
            ].iloc[0]
            self.assertGreater(january["hawkish_sentences"], 0)
            self.assertGreater(february["dovish_sentences"], 0)


class _FakePipeline:
    def __call__(
        self,
        texts: list[str],
        batch_size: int = 16,
        truncation: bool = True,
    ) -> list[dict[str, object]]:
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
