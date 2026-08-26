from dataclasses import dataclass
import asyncio
import numpy as np
from typing import Dict

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

    Synchronous prediction remains available for internal synchronous
    callers.

    Async callers should use predict_async() so scikit-learn inference
    never blocks the FastAPI event loop.
    """

    INTENT_KEYWORDS = {
        IntentType.GREETING: [
            "hi",
            "hello",
            "hey",
            "good morning",
            "good evening",
            "namaste",
        ],
        IntentType.PRODUCT_SEARCH: [
            "need",
            "want",
            "looking for",
            "search",
            "find",
            "show me",
            "buy",
            "purchase",
        ],
        IntentType.PRODUCT_INQUIRY: [
            "tell me about",
            "details",
            "specs",
            "material",
            "fabric",
            "how is",
            "describe",
        ],
        IntentType.AVAILABILITY: [
            "available",
            "in stock",
            "stock",
            "have",
            "size",
            "xl",
            "xxl",
        ],
        IntentType.ORDER_STATUS: [
            "order",
            "track",
            "where is",
            "delivered",
            "shipped",
            "status",
            "order id",
        ],
        IntentType.CANCEL_ORDER: [
            "cancel",
            "return",
            "refund",
            "don't want",
            "change mind",
        ],
        IntentType.RETURN_REQUEST: [
            "return",
            "exchange",
            "replace",
            "wrong size",
            "defective",
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
        ],
        IntentType.THANKS: [
            "thanks",
            "thank you",
            "thx",
            "ty",
            "appreciate",
        ],
    }

    def __init__(self) -> None:
        self._confidence_threshold = 0.25

    async def predict_async(
        self,
        text: str,
    ) -> IntentPrediction:
        """
        Run intent prediction without blocking the FastAPI
        event loop.

        All synchronous model loading/vectorization/inference is
        executed inside a worker thread.
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

        Do not call this directly from an async FastAPI request
        handler. Use predict_async() instead.
        """

        import re

        if not text or not text.strip():
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
            )

        text_clean = re.sub(
            r"[^\w\s]",
            "",
            text,
        ).strip().lower()

        if text_clean in {
            "hi",
            "hello",
            "hey",
            "hii",
            "namaste",
            "good morning",
            "good evening",
        }:
            return IntentPrediction(
                intent=IntentType.GREETING,
                confidence=0.95,
                all_scores={
                    IntentType.GREETING.value: 0.95,
                },
            )

        if (
            model_loader.intent_model is not None
            and model_loader.intent_vectorizer is not None
        ):
            return self._predict_ml(
                text_clean
            )

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

        if (
            model_loader.intent_vectorizer is None
            or model_loader.intent_model is None
        ):
            return self._predict_keywords(text)

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

            max_idx = int(
                np.argmax(probabilities)
            )

            predicted_intent_str = str(
                classes[max_idx]
            )

            confidence = float(
                probabilities[max_idx]
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

            logger.debug(
                "Intent ML prediction: %s "
                "(confidence: %.3f)",
                intent.value,
                confidence,
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

            return self._predict_keywords(
                text
            )

    def _predict_keywords(
        self,
        text: str,
    ) -> IntentPrediction:

        import re

        text_lower = text.lower()

        scores: Dict[str, int] = {}

        for intent_enum, keywords in (
            self.INTENT_KEYWORDS.items()
        ):
            score = 0

            for keyword in keywords:
                if re.search(
                    rf"\b{re.escape(keyword)}\b",
                    text_lower,
                ):
                    score += 1

            scores[
                intent_enum.value
            ] = score

        if scores:

            best_intent = max(
                scores,
                key=scores.get,
            )

            best_score = scores[
                best_intent
            ]

            confidence = (
                min(
                    best_score / 3.0,
                    1.0,
                )
                if best_score > 0
                else 0.1
            )

            if best_score > 0:
                intent = IntentType(
                    best_intent
                )
            else:
                intent = IntentType.UNKNOWN
                confidence = 0.1

        else:

            intent = IntentType.UNKNOWN
            confidence = 0.1

        logger.debug(
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

    def _map_to_intent_type(
        self,
        intent_str: str,
    ) -> IntentType:

        intent_lower = (
            intent_str.lower()
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