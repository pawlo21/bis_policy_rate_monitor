"""Transformer-based hawkish/dovish assessment for BIS speeches.

The model used here is a ready Hugging Face classifier. It is not trained by
this project. "Sentiment" is used as a CLI-friendly word, but the labels are
really monetary-policy stance labels: hawkish, dovish, and neutral.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

log = logging.getLogger(__name__)

# Requested ready-made model. Its model card maps:
# LABEL_0 = neutral, LABEL_1 = dovish, LABEL_2 = hawkish.
DEFAULT_SENTIMENT_MODEL = "brjoey/CBSI-CentralBank-BERT"
LABEL_MAP = {
    "LABEL_0": "neutral",
    "LABEL_1": "dovish",
    "LABEL_2": "hawkish",
}

# The transformer should score monetary-policy sentences, not greetings or
# conference logistics. This keeps the result faster and less diluted by
# irrelevant neutral text.
POLICY_SENTENCE_PATTERN = re.compile(
    r"\b("
    r"inflation|inflationary|price stability|consumer prices?|cpi|"
    r"policy rates?|interest rates?|bank rates?|monetary policy|policy stance|"
    r"tighten(?:ing|ed|s)?|tighter|hik(?:e|es|ed|ing)|restrictive|"
    r"eas(?:e|es|ed|ing)|accommodative|stimulus|rate cuts?|lower rates?|"
    r"disinflation|downside risks?|slack"
    r")\b",
    flags=re.IGNORECASE,
)
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass(frozen=True)
class SpeechSentimentAnalysis:
    """Transformer output used by JSON and HTML report writers."""

    chart_path: Path
    model_name: str
    speech_scores: pd.DataFrame
    monthly_scores: pd.DataFrame


class SpeechSentimentAssessor:
    """Assess hawkish/dovish stance of BIS speeches with a transformer.

    Workflow:
    1. split each speech into sentences,
    2. keep only sentences that look monetary-policy related,
    3. classify those sentences with the transformer,
    4. aggregate sentence labels to one score per speech,
    5. aggregate speech scores to a monthly series for the chart.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_SENTIMENT_MODEL,
        batch_size: int = 16,
        max_sentences_per_speech: int | None = None,
        pipeline_factory: Callable[[str], object] | None = None,
    ) -> None:
        """Configure the model and batching used for local inference."""
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_sentences_per_speech = max_sentences_per_speech
        self.pipeline_factory = pipeline_factory

    def analyze(
        self,
        speeches: pd.DataFrame,
        chart_path: Path,
    ) -> SpeechSentimentAnalysis | None:
        """Classify speeches, build score tables, and render the sentiment chart."""
        sentence_frame = self.extract_policy_sentences(speeches)
        if sentence_frame.empty:
            log.warning("No policy-relevant speech sentences found for sentiment assessment.")
            return None

        log.info(
            "Classifying %d policy-relevant speech sentences with %s.",
            len(sentence_frame),
            self.model_name,
        )
        predictions = self.classify_sentences(sentence_frame["sentence"].tolist())
        classified = sentence_frame.copy()
        classified["label"] = [prediction["label"] for prediction in predictions]
        classified["score"] = [prediction["score"] for prediction in predictions]

        speech_scores = self.score_speeches(classified)
        monthly_scores = self.score_months(speech_scores)
        if speech_scores.empty or monthly_scores.empty:
            log.warning("No transformer speech sentiment scores were produced.")
            return None

        self.render_chart(speech_scores, monthly_scores, chart_path)
        return SpeechSentimentAnalysis(
            chart_path=chart_path,
            model_name=self.model_name,
            speech_scores=speech_scores,
            monthly_scores=monthly_scores,
        )

    def extract_policy_sentences(self, speeches: pd.DataFrame) -> pd.DataFrame:
        """Return one row per policy-relevant sentence."""
        columns = ["speech_id", "date", "month", "title", "author", "url", "sentence"]
        if speeches.empty:
            return pd.DataFrame(columns=columns)

        data = speeches.copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data["text"] = data["text"].fillna("").astype(str)
        for optional_column in ("title", "author", "url"):
            if optional_column not in data:
                data[optional_column] = ""
            data[optional_column] = data[optional_column].fillna("").astype(str)
        data = data.dropna(subset=["date"])

        rows = []
        for speech_id, speech in data.reset_index(drop=True).iterrows():
            policy_sentences = [
                sentence
                for sentence in self._split_text(str(speech["text"]))
                if POLICY_SENTENCE_PATTERN.search(sentence)
            ]
            if self.max_sentences_per_speech is not None:
                policy_sentences = policy_sentences[: self.max_sentences_per_speech]

            for sentence in policy_sentences:
                rows.append(
                    {
                        "speech_id": speech_id,
                        "date": speech["date"],
                        "month": speech["date"].to_period("M").to_timestamp(),
                        "title": speech["title"],
                        "author": speech["author"],
                        "url": speech["url"],
                        "sentence": sentence,
                    }
                )

        return pd.DataFrame(rows, columns=columns)

    def classify_sentences(self, sentences: Sequence[str]) -> list[dict[str, object]]:
        """Run the transformer in batches and return readable labels."""
        classifier = self._load_pipeline()
        sentence_list = list(sentences)
        raw_predictions = []

        # Batching avoids sending thousands of sentences to the model at once.
        # The INFO logs also make long local runs visibly progress.
        for start in range(0, len(sentence_list), self.batch_size):
            end = min(start + self.batch_size, len(sentence_list))
            log.info("Transformer batch %d-%d of %d.", start + 1, end, len(sentence_list))
            batch_predictions = classifier(
                sentence_list[start:end],
                batch_size=self.batch_size,
                truncation=True,
            )
            raw_predictions.extend(batch_predictions)

        predictions = []
        for raw_prediction in raw_predictions:
            if isinstance(raw_prediction, list):
                raw_prediction = raw_prediction[0] if raw_prediction else {}

            raw_label = str(raw_prediction.get("label", ""))
            predictions.append(
                {
                    "label": LABEL_MAP.get(raw_label, raw_label.lower() or "unknown"),
                    "score": float(raw_prediction.get("score", 0.0)),
                }
            )
        return predictions

    def score_speeches(self, classified_sentences: pd.DataFrame) -> pd.DataFrame:
        """Aggregate classified sentences into one score per speech."""
        if classified_sentences.empty:
            return _empty_speech_scores()

        data = classified_sentences.copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data["score"] = pd.to_numeric(data["score"], errors="coerce")
        data = data.dropna(subset=["speech_id", "date", "label"])
        if data.empty:
            return _empty_speech_scores()

        index_columns = ["speech_id", "date", "month", "title", "author", "url"]
        counts = (
            data.pivot_table(
                index=index_columns,
                columns="label",
                values="sentence",
                aggfunc="count",
                fill_value=0,
            )
            .reset_index()
            .rename_axis(None, axis=1)
        )
        for label in ("hawkish", "dovish", "neutral"):
            if label not in counts:
                counts[label] = 0

        confidence = (
            data.groupby(index_columns, as_index=False)["score"]
            .mean()
            .rename(columns={"score": "average_confidence"})
        )
        speech_scores = counts.merge(confidence, on=index_columns, how="left").rename(
            columns={
                "hawkish": "hawkish_sentences",
                "dovish": "dovish_sentences",
                "neutral": "neutral_sentences",
            }
        )
        speech_scores["sentence_count"] = speech_scores[
            ["hawkish_sentences", "dovish_sentences", "neutral_sentences"]
        ].sum(axis=1)

        for label in ("hawkish", "dovish", "neutral"):
            speech_scores[f"{label}_share"] = (
                speech_scores[f"{label}_sentences"]
                / speech_scores["sentence_count"].where(speech_scores["sentence_count"].ne(0))
            ).fillna(0.0)
        speech_scores["net_hawkish_score"] = (
            (speech_scores["hawkish_sentences"] - speech_scores["dovish_sentences"])
            / speech_scores["sentence_count"].where(speech_scores["sentence_count"].ne(0))
        ).fillna(0.0)
        speech_scores["dominant_stance"] = speech_scores.apply(_dominant_stance, axis=1)

        return (
            speech_scores[_speech_score_columns()]
            .sort_values(["date", "speech_id"])
            .reset_index(drop=True)
        )

    def score_months(self, speech_scores: pd.DataFrame) -> pd.DataFrame:
        """Average speech-level scores by month.

        Each speech gets equal weight. That is deliberate: one long speech should
        not dominate the monthly score just because it has more sentences.
        """
        if speech_scores.empty:
            return _empty_monthly_scores()

        data = speech_scores.copy()
        data["month"] = pd.to_datetime(data["month"], errors="coerce")
        data = data.dropna(subset=["month"])
        if data.empty:
            return _empty_monthly_scores()

        monthly = (
            data.groupby("month", as_index=False)
            .agg(
                speech_count=("speech_id", "nunique"),
                sentence_count=("sentence_count", "sum"),
                hawkish_share=("hawkish_share", "mean"),
                dovish_share=("dovish_share", "mean"),
                neutral_share=("neutral_share", "mean"),
                net_hawkish_score=("net_hawkish_score", "mean"),
                average_confidence=("average_confidence", "mean"),
            )
            .sort_values("month")
            .reset_index(drop=True)
        )
        return monthly[_monthly_score_columns()]

    def render_chart(
        self,
        speech_scores: pd.DataFrame,
        monthly_scores: pd.DataFrame,
        chart_path: Path,
    ) -> None:
        """Render speech-level dots plus monthly average stance."""
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        fig, (score_ax, share_ax) = plt.subplots(2, 1, figsize=(10, 6.2), sharex=True)

        if monthly_scores.empty:
            score_ax.text(0.5, 0.5, "No transformer sentiment data", ha="center")
            score_ax.set_axis_off()
            share_ax.set_axis_off()
        else:
            speech_data = speech_scores.copy()
            speech_data["date"] = pd.to_datetime(speech_data["date"], errors="coerce")
            speech_data = speech_data.dropna(subset=["date"]).sort_values("date")
            monthly_data = monthly_scores.copy()
            monthly_data["month"] = pd.to_datetime(monthly_data["month"], errors="coerce")
            monthly_data = monthly_data.dropna(subset=["month"]).sort_values("month")

            score_ax.scatter(
                speech_data["date"],
                speech_data["net_hawkish_score"],
                alpha=0.35,
                s=18,
                label="individual speech",
            )
            score_ax.plot(
                monthly_data["month"],
                monthly_data["net_hawkish_score"],
                marker="o",
                linewidth=1.8,
                color="#1f77b4",
                label="monthly average",
            )
            score_ax.axhline(0, color="#9aa5b1", linewidth=0.8)
            score_ax.set_ylim(-1.05, 1.05)
            score_ax.set_title("BIS speeches: transformer hawkish/dovish assessment")
            score_ax.set_ylabel("Net hawkish score")
            score_ax.grid(True, alpha=0.3)
            score_ax.legend(loc="best", fontsize=8)

            share_ax.plot(
                monthly_data["month"],
                monthly_data["hawkish_share"],
                marker="o",
                label="hawkish share",
            )
            share_ax.plot(
                monthly_data["month"],
                monthly_data["dovish_share"],
                marker="o",
                label="dovish share",
            )
            share_ax.set_ylim(0, 1.05)
            share_ax.set_ylabel("Average speech share")
            share_ax.grid(True, alpha=0.3)
            share_ax.legend(loc="best", fontsize=8)

        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(chart_path, dpi=160)
        plt.close(fig)

    def _load_pipeline(self) -> object:
        if self.pipeline_factory is not None:
            return self.pipeline_factory(self.model_name)

        try:
            from transformers import pipeline  # pylint: disable=import-outside-toplevel
        except ImportError as error:
            raise RuntimeError(
                "Install transformer support first: "
                'python -m pip install -e ".[transformer]"'
            ) from error

        return pipeline("text-classification", model=self.model_name, tokenizer=self.model_name)

    def _split_text(self, text: str) -> list[str]:
        clean_text = re.sub(r"\s+", " ", text).strip()
        if not clean_text:
            return []

        sentences = []
        for sentence in SENTENCE_SPLIT_PATTERN.split(clean_text):
            clean_sentence = sentence.strip()
            if len(clean_sentence) >= 30:
                sentences.append(clean_sentence[:2000])
        return sentences


def _dominant_stance(row: pd.Series) -> str:
    counts = {
        "hawkish": int(row["hawkish_sentences"]),
        "dovish": int(row["dovish_sentences"]),
        "neutral": int(row["neutral_sentences"]),
    }
    if sum(counts.values()) == 0:
        return "unknown"
    return max(counts, key=counts.get)


def _speech_score_columns() -> list[str]:
    return [
        "speech_id",
        "date",
        "month",
        "title",
        "author",
        "url",
        "sentence_count",
        "hawkish_sentences",
        "dovish_sentences",
        "neutral_sentences",
        "hawkish_share",
        "dovish_share",
        "neutral_share",
        "net_hawkish_score",
        "dominant_stance",
        "average_confidence",
    ]


def _monthly_score_columns() -> list[str]:
    return [
        "month",
        "speech_count",
        "sentence_count",
        "hawkish_share",
        "dovish_share",
        "neutral_share",
        "net_hawkish_score",
        "average_confidence",
    ]


def _empty_speech_scores() -> pd.DataFrame:
    return pd.DataFrame(columns=_speech_score_columns())


def _empty_monthly_scores() -> pd.DataFrame:
    return pd.DataFrame(columns=_monthly_score_columns())
