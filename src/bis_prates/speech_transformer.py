"""Transformer-based hawkish/dovish classification for BIS speeches."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import matplotlib.pyplot as plt
import pandas as pd


log = logging.getLogger(__name__)

# The ready-made model requested for this project. Its labels are:
# LABEL_0 = neutral, LABEL_1 = dovish, LABEL_2 = hawkish.
DEFAULT_TRANSFORMER_MODEL = "brjoey/CBSI-CentralBank-BERT"
LABEL_MAP = {
    "LABEL_0": "neutral",
    "LABEL_1": "dovish",
    "LABEL_2": "hawkish",
}

# We do not classify every sentence in a speech. Many BIS speeches contain
# greetings, biographies, conference context, or broad institutional material.
# This simple filter keeps only sentences likely to carry monetary-policy tone.
POLICY_SENTENCE_PATTERN = re.compile(
    r"\b("
    r"inflation|inflationary|price stability|consumer prices?|cpi|"
    r"policy rates?|interest rates?|monetary policy|policy stance|"
    r"tighten(?:ing|ed|s)?|tighter|hik(?:e|es|ed|ing)|restrictive|"
    r"eas(?:e|es|ed|ing)|accommodative|stimulus|rate cuts?|lower rates?|"
    r"disinflation|downside risks?|slack"
    r")\b",
    flags=re.IGNORECASE,
)
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass(frozen=True)
class TransformerSpeechAnalysis:
    chart_path: Path
    model_name: str
    monthly_stance: pd.DataFrame


class TransformerSpeechClassifier:
    """Small wrapper around a Hugging Face text-classification model.

    The class intentionally keeps the workflow plain:
    1. split speeches into sentence-like chunks,
    2. keep only policy-relevant sentences,
    3. classify each sentence as neutral/dovish/hawkish,
    4. aggregate the sentence labels by month.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_TRANSFORMER_MODEL,
        batch_size: int = 8,
        max_sentences_per_speech: Optional[int] = None,
        pipeline_factory: Optional[Callable[[str], object]] = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_sentences_per_speech = max_sentences_per_speech
        self.pipeline_factory = pipeline_factory

    def analyze(
        self,
        speeches: pd.DataFrame,
        chart_path: Path,
    ) -> Optional[TransformerSpeechAnalysis]:
        """Classify speeches and render the transformer chart."""
        sentence_frame = self.extract_policy_sentences(speeches)
        if sentence_frame.empty:
            log.warning("No policy-relevant speech sentences found for transformer analysis.")
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

        monthly_stance = self.summarise_by_month(classified)
        if monthly_stance.empty:
            log.warning("No transformer stance output was produced.")
            return None

        self.render_chart(monthly_stance, chart_path)
        return TransformerSpeechAnalysis(
            chart_path=chart_path,
            model_name=self.model_name,
            monthly_stance=monthly_stance,
        )

    def extract_policy_sentences(self, speeches: pd.DataFrame) -> pd.DataFrame:
        """Split speeches and keep sentences that look relevant to policy tone."""
        columns = ["speech_id", "date", "month", "sentence"]
        if speeches.empty:
            return pd.DataFrame(columns=columns)

        data = speeches.copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data["text"] = data["text"].fillna("").astype(str)
        data = data.dropna(subset=["date"])

        rows = []
        for speech_id, speech in data.reset_index(drop=True).iterrows():
            sentences = self._split_text(str(speech["text"]))
            policy_sentences = [
                sentence
                for sentence in sentences
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
                        "sentence": sentence,
                    }
                )

        return pd.DataFrame(rows, columns=columns)

    def classify_sentences(self, sentences: Sequence[str]) -> List[dict[str, object]]:
        """Run the transformer and normalise model labels into readable labels."""
        classifier = self._load_pipeline()
        raw_predictions = []
        sentence_list = list(sentences)

        # Process explicit small batches so the CLI can report progress. This is
        # slower than one huge call, but much easier to monitor on a laptop.
        for start in range(0, len(sentence_list), self.batch_size):
            end = min(start + self.batch_size, len(sentence_list))
            log.info(
                "Transformer batch %d-%d of %d.",
                start + 1,
                end,
                len(sentence_list),
            )
            batch_predictions = classifier(
                sentence_list[start:end],
                batch_size=self.batch_size,
                truncation=True,
            )
            raw_predictions.extend(batch_predictions)

        predictions = []
        for raw_prediction in raw_predictions:
            # Hugging Face usually returns one dict per text. Some pipelines can
            # return a one-item list, so this keeps the rest of the code stable.
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

    def summarise_by_month(self, classified_sentences: pd.DataFrame) -> pd.DataFrame:
        """Aggregate sentence classifications into monthly shares."""
        if classified_sentences.empty:
            return _empty_monthly_stance()

        data = classified_sentences.copy()
        data["month"] = pd.to_datetime(data["month"], errors="coerce")
        data["score"] = pd.to_numeric(data["score"], errors="coerce")
        data = data.dropna(subset=["month", "label"])
        if data.empty:
            return _empty_monthly_stance()

        counts = (
            data.pivot_table(
                index="month",
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

        speech_counts = (
            data.groupby("month", as_index=False)["speech_id"]
            .nunique()
            .rename(columns={"speech_id": "speech_count"})
        )
        confidence = (
            data.groupby("month", as_index=False)["score"]
            .mean()
            .rename(columns={"score": "average_confidence"})
        )

        monthly = counts.merge(speech_counts, on="month", how="left").merge(
            confidence,
            on="month",
            how="left",
        )
        monthly = monthly.rename(
            columns={
                "hawkish": "hawkish_sentences",
                "dovish": "dovish_sentences",
                "neutral": "neutral_sentences",
            }
        )
        monthly["sentence_count"] = monthly[
            ["hawkish_sentences", "dovish_sentences", "neutral_sentences"]
        ].sum(axis=1)
        for label in ("hawkish", "dovish", "neutral"):
            monthly[f"{label}_share"] = (
                monthly[f"{label}_sentences"]
                / monthly["sentence_count"].where(monthly["sentence_count"].ne(0), pd.NA)
            ).fillna(0.0)
        monthly["net_hawkish_share"] = (
            (monthly["hawkish_sentences"] - monthly["dovish_sentences"])
            / monthly["sentence_count"].where(monthly["sentence_count"].ne(0), pd.NA)
        ).fillna(0.0)

        return monthly[_monthly_columns()].sort_values("month").reset_index(drop=True)

    def render_chart(self, monthly_stance: pd.DataFrame, chart_path: Path) -> None:
        """Save a simple line chart for the report."""
        chart_path.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(10, 4.8))

        if monthly_stance.empty:
            ax.text(0.5, 0.5, "No transformer stance data", ha="center")
            ax.set_axis_off()
        else:
            data = monthly_stance.copy()
            data["month"] = pd.to_datetime(data["month"], errors="coerce")
            data = data.dropna(subset=["month"]).sort_values("month")

            ax.plot(data["month"], data["hawkish_share"], marker="o", label="hawkish")
            ax.plot(data["month"], data["dovish_share"], marker="o", label="dovish")
            ax.plot(
                data["month"],
                data["net_hawkish_share"],
                linestyle="--",
                color="#52606d",
                label="net hawkish",
            )
            ax.axhline(0, color="#9aa5b1", linewidth=0.8)
            ax.set_ylim(-1.05, 1.05)
            ax.set_title("BIS speeches: transformer hawkish/dovish stance")
            ax.set_ylabel("Share of classified sentences")
            ax.grid(True, alpha=0.3)
            ax.legend(loc="best", fontsize=8)

        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(chart_path, dpi=160)
        plt.close(fig)

    def _load_pipeline(self) -> object:
        if self.pipeline_factory is not None:
            return self.pipeline_factory(self.model_name)

        try:
            from transformers import pipeline
        except ImportError as error:
            raise RuntimeError(
                "Install transformer support first: "
                'python -m pip install -e ".[transformer]"'
            ) from error

        return pipeline("text-classification", model=self.model_name, tokenizer=self.model_name)

    def _split_text(self, text: str) -> List[str]:
        clean_text = re.sub(r"\s+", " ", text).strip()
        if not clean_text:
            return []

        sentences = []
        for sentence in SENTENCE_SPLIT_PATTERN.split(clean_text):
            clean_sentence = sentence.strip()
            # Very short fragments are usually headings or parsing noise.
            if len(clean_sentence) >= 30:
                sentences.append(clean_sentence[:2000])
        return sentences


def _monthly_columns() -> List[str]:
    return [
        "month",
        "speech_count",
        "sentence_count",
        "hawkish_sentences",
        "dovish_sentences",
        "neutral_sentences",
        "hawkish_share",
        "dovish_share",
        "neutral_share",
        "net_hawkish_share",
        "average_confidence",
    ]


def _empty_monthly_stance() -> pd.DataFrame:
    return pd.DataFrame(columns=_monthly_columns())
