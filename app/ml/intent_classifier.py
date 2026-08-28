from dataclasses import dataclass
import asyncio
import re
from typing import Dict

import numpy as np

from app.ml.loader import model_loader
from app.models.schemas import IntentType
from app.utils.logger import logger


@dataclass
class IntentPrediction:
    """
    Result of intent classification.
    """

    intent: IntentType
    confidence: float
    all_scores: dict


class IntentClassifier:
    """
    Classifies user messages using the trained ML model.

    The classifier uses a confidence threshold and a confidence
    margin so a weak ML prediction is not treated as a definite
    intent.

    If the ML model is uncertain, deterministic keyword rules are
    used as a fallback.
    """

    # ---------------------------------------------------------
    # ML confidence controls
    # ---------------------------------------------------------

    INTENT_CONFIDENCE_THRESHOLD = 0.50
    INTENT_MARGIN_THRESHOLD = 0.10

    # ---------------------------------------------------------
    # Deterministic keyword fallback
    # ---------------------------------------------------------

    INTENT_KEYWORDS = {
        IntentType.GREETING: [
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
            "namaste",
            "howdy",
        ],

        IntentType.PRODUCT_SEARCH: [
            "need",
            "want",
            "looking for",
            "search",
            "find",
            "show me",
            "i want",
            "i need",
            "buy",
            "purchase",
            "looking",
            "browse",
            "looking to buy",
        ],

        IntentType.PRODUCT_INQUIRY: [
            "tell me about",
            "details",
            "specs",
            "material",
            "fabric",
            "how is",
            "describe",
            "features",
            "care instruction",
            "machine washable",
            "pockets",
            "fit like",
        ],

        IntentType.AVAILABILITY: [
            "available",
            "in stock",
            "stock",
            "have",
            "do you have",
            "is it available",
            "is this available",
            "sold out",
        ],

        IntentType.ORDER_STATUS: [
            "order",
            "track",
            "where is my order",
            "where is order",
            "delivered",
            "shipped",
            "status",
            "tracking",
            "order id",
        ],

        IntentType.CANCEL_ORDER: [
            "cancel",
            "cancel order",
            "refund",
            "don't want",
            "do not want",
            "change my mind",
        ],

        IntentType.RETURN_REQUEST: [
            "return",
            "exchange",
            "replace",
            "wrong size",
            "defective",
            "return policy",
        ],

        IntentType.COMPLAINT: [
            "complaint",
            "issue",
            "problem",
            "wrong",
            "bad",
            "poor",
            "disappointed",
            "angry",
            "terrible",
            "unhappy",
        ],

        IntentType.THANKS: [
            "thanks",
            "thank you",
            "thx",
            "ty",
            "appreciate",
            "grateful",
        ],
    }

    def __init__(self) -> None:
        self._confidence_threshold = (
            self.INTENT_CONFIDENCE_THRESHOLD
        )

        self._margin_threshold = (
            self.INTENT_MARGIN_THRESHOLD
        )

    async def predict_async(
        self,
        text: str,
    ) -> IntentPrediction:
        """
        Run intent prediction without blocking the FastAPI
        event loop.
        """

        return await asyncio.to_thread(
            self.predict,
            text,
        )

    def predict(
        self,
        text: str,
    ) -> IntentPrediction:
        """
        Synchronous intent prediction.

        Async callers should use predict_async().
        """

        if not text or not text.strip():
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
            )

        text_clean = self._clean_text(text)

        if not text_clean:
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
            )

        # -----------------------------------------------------
        # Exact greetings
        # -----------------------------------------------------

        if text_clean in {
            "hi",
            "hello",
            "hey",
            "hii",
            "helo",
            "namaste",
            "good morning",
            "good afternoon",
            "good evening",
            "howdy",
        }:
            return IntentPrediction(
                intent=IntentType.GREETING,
                confidence=0.99,
                all_scores={
                    IntentType.GREETING.value: 0.99,
                },
            )

        # -----------------------------------------------------
        # ML prediction
        # -----------------------------------------------------

        if (
            model_loader.intent_model is not None
            and model_loader.intent_vectorizer is not None
        ):
            ml_prediction = self._predict_ml(
                text_clean
            )

            if (
                ml_prediction.intent
                != IntentType.UNKNOWN
            ):
                return ml_prediction

            # ML is uncertain.
            #
            # Do NOT blindly return the weak ML prediction.
            # Try deterministic rules instead.
            keyword_prediction = (
                self._predict_keywords(
                    text_clean
                )
            )

            if (
                keyword_prediction.intent
                != IntentType.UNKNOWN
            ):
                return keyword_prediction

            return ml_prediction

        logger.warning(
            "Intent model not loaded; "
            "using keyword fallback"
        )

        return self._predict_keywords(
            text_clean
        )

    def _predict_ml(
        self,
        text: str,
    ) -> IntentPrediction:
        """
        Run ML inference and reject weak predictions.
        """

        if (
            model_loader.intent_vectorizer is None
            or model_loader.intent_model is None
        ):
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
            )

        try:
            vectorized = (
                model_loader.intent_vectorizer.transform(
                    [text]
                )
            )

            probabilities = (
                model_loader.intent_model
                .predict_proba(vectorized)[0]
            )

            classes = (
                model_loader.intent_model.classes_
            )

            if len(probabilities) == 0:
                return IntentPrediction(
                    intent=IntentType.UNKNOWN,
                    confidence=0.0,
                    all_scores={},
                )

            sorted_indices = np.argsort(
                probabilities
            )[::-1]

            best_index = int(
                sorted_indices[0]
            )

            second_index = (
                int(sorted_indices[1])
                if len(sorted_indices) > 1
                else best_index
            )

            confidence = float(
                probabilities[best_index]
            )

            second_confidence = float(
                probabilities[second_index]
            )

            margin = (
                confidence
                - second_confidence
            )

            predicted_intent_str = str(
                classes[best_index]
            )

            intent = (
                self._map_to_intent_type(
                    predicted_intent_str
                )
            )

            all_scores = {
                self._map_to_intent_type(
                    str(cls)
                ).value: float(prob)
                for cls, prob in zip(
                    classes,
                    probabilities,
                )
            }

            logger.info(
                "Intent ML prediction: %s "
                "(confidence: %.3f, margin: %.3f)",
                intent.value,
                confidence,
                margin,
            )

            # -------------------------------------------------
            # Confidence gate
            # -------------------------------------------------

            if (
                confidence
                < self._confidence_threshold
            ):
                logger.warning(
                    "Rejecting ML intent '%s': "
                    "confidence %.3f < threshold %.3f",
                    intent.value,
                    confidence,
                    self._confidence_threshold,
                )

                return IntentPrediction(
                    intent=IntentType.UNKNOWN,
                    confidence=confidence,
                    all_scores=all_scores,
                )

            # -------------------------------------------------
            # Margin gate
            # -------------------------------------------------

            if (
                len(probabilities) > 1
                and margin
                < self._margin_threshold
            ):
                logger.warning(
                    "Rejecting ambiguous ML intent '%s': "
                    "margin %.3f < threshold %.3f",
                    intent.value,
                    margin,
                    self._margin_threshold,
                )

                return IntentPrediction(
                    intent=IntentType.UNKNOWN,
                    confidence=confidence,
                    all_scores=all_scores,
                )

            return IntentPrediction(
                intent=intent,
                confidence=confidence,
                all_scores=all_scores,
            )

        except Exception as exc:
            logger.exception(
                "ML intent prediction failed: %s",
                exc,
            )

            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
            )

    def _predict_keywords(
        self,
        text: str,
    ) -> IntentPrediction:
        """
        Deterministic fallback classifier.

        This is intentionally used when the ML model is
        uncertain.
        """

        text_lower = text.lower()

        scores: Dict[str, int] = {}

        for (
            intent_enum,
            keywords,
        ) in self.INTENT_KEYWORDS.items():

            score = 0

            for keyword in keywords:
                keyword_lower = (
                    keyword.lower()
                )

                if " " in keyword_lower:
                    if keyword_lower in text_lower:
                        score += 2
                    continue

                if re.search(
                    rf"\b{re.escape(keyword_lower)}\b",
                    text_lower,
                ):
                    score += 1

            scores[
                intent_enum.value
            ] = score

        if not scores:
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
            )

        ranked = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        best_intent_value = ranked[0][0]
        best_score = ranked[0][1]

        second_score = (
            ranked[1][1]
            if len(ranked) > 1
            else 0
        )

        if best_score <= 0:
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores=scores,
            )

        # Convert deterministic rule score into a bounded
        # confidence value.
        confidence = min(
            0.60
            + (best_score * 0.10),
            0.95,
        )

        # Avoid choosing an intent when two categories have
        # exactly the same evidence.
        if (
            len(ranked) > 1
            and best_score == second_score
            and best_score > 0
        ):
            logger.warning(
                "Keyword intent is ambiguous: %s",
                ranked[:3],
            )

            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores=scores,
            )

        intent = IntentType(
            best_intent_value
        )

        logger.info(
            "Intent keyword prediction: %s "
            "(confidence: %.3f)",
            intent.value,
            confidence,
        )

        return IntentPrediction(
            intent=intent,
            confidence=confidence,
            all_scores=scores,
        )

    @staticmethod
    def _clean_text(
        text: str,
    ) -> str:
        """
        Apply the same basic text normalization expected
        by the trained TF-IDF model.
        """

        text = text.lower()

        text = re.sub(
            r"[^\w\s]",
            " ",
            text,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    def _map_to_intent_type(
        self,
        intent_str: str,
    ) -> IntentType:
        """
        Normalize model labels to IntentType.
        """

        intent_lower = (
            intent_str.lower()
            .strip()
        )

        aliases = {
            "product_availability":
                IntentType.AVAILABILITY.value,

            "cancel_request":
                IntentType.CANCEL_ORDER.value,
        }

        normalized_intent = aliases.get(
            intent_lower,
            intent_lower,
        )

        try:
            return IntentType(
                normalized_intent
            )
        except ValueError:

            for intent in IntentType:

                if (
                    intent.value
                    in intent_lower
                    or intent_lower
                    in intent.value
                ):
                    return intent

            return IntentType.UNKNOWN


intent_classifier = IntentClassifier()