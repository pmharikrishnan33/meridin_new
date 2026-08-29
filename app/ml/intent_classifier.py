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
    margin: float = 0.0


class IntentClassifier:
    """
    Classifies user messages using the trained ML model.

    The classifier uses:

    1. Deterministic rules for obvious intents.
    2. TF-IDF + Logistic Regression for general intent detection.
    3. A minimum confidence threshold.
    4. A top-vs-second prediction margin.

    The margin is important because the current model has nine intent
    classes and its raw probabilities are relatively diffuse.
    """

    # ---------------------------------------------------------
    # ML confidence controls
    # ---------------------------------------------------------
    #
    # The diagnostic showed examples such as:
    #
    # product_search = 0.2255
    #
    # Therefore 0.50 would reject many correct predictions.
    #
    # The margin prevents genuinely ambiguous predictions from being
    # accepted merely because they are the highest class.
    # ---------------------------------------------------------

    INTENT_CONFIDENCE_THRESHOLD = 0.18
    INTENT_MARGIN_THRESHOLD = 0.05

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
            "change my mind",
            "stop my order",
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
        Run synchronous prediction in a worker thread.
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
        Predict the user's intent.
        """

        if not text or not text.strip():
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
                margin=0.0,
            )

        text_clean = self._clean_text(text)

        if not text_clean:
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
                margin=0.0,
            )

        # -----------------------------------------------------
        # Exact obvious greetings
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
                margin=0.99,
            )

        # -----------------------------------------------------
        # Exact obvious thanks
        # -----------------------------------------------------

        if text_clean in {
            "thanks",
            "thank you",
            "thankyou",
            "thx",
            "ty",
            "many thanks",
        }:
            return IntentPrediction(
                intent=IntentType.THANKS,
                confidence=0.99,
                all_scores={
                    IntentType.THANKS.value: 0.99,
                },
                margin=0.99,
            )

        # -----------------------------------------------------
        # ML model
        # -----------------------------------------------------

        if (
            model_loader.intent_model is not None
            and model_loader.intent_vectorizer is not None
        ):
            prediction = self._predict_ml(
                text_clean
            )

            if prediction.intent != IntentType.UNKNOWN:
                return prediction

            # If ML is uncertain, use deterministic keywords.
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

            return prediction

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
        Predict intent using the trained ML model.

        Returns UNKNOWN when:

        confidence < minimum confidence

        OR

        top-vs-second margin < minimum margin
        """

        if (
            model_loader.intent_vectorizer is None
            or model_loader.intent_model is None
        ):
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores={},
                margin=0.0,
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
                    margin=0.0,
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

            predicted_intent = (
                self._map_to_intent_type(
                    str(classes[best_index])
                )
            )

            all_scores = {}

            for cls, probability in zip(
                classes,
                probabilities,
            ):
                mapped_intent = (
                    self._map_to_intent_type(
                        str(cls)
                    )
                )

                all_scores[
                    mapped_intent.value
                ] = float(probability)

            logger.info(
                "Intent ML prediction: %s "
                "(confidence: %.3f, "
                "second: %.3f, "
                "margin: %.3f)",
                predicted_intent.value,
                confidence,
                second_confidence,
                margin,
            )

            # -------------------------------------------------
            # Confidence gate
            # -------------------------------------------------

            if (
                confidence
                < self._confidence_threshold
            ):
                logger.info(
                    "ML intent rejected: "
                    "%s confidence %.3f < %.3f",
                    predicted_intent.value,
                    confidence,
                    self._confidence_threshold,
                )

                return IntentPrediction(
                    intent=IntentType.UNKNOWN,
                    confidence=confidence,
                    all_scores=all_scores,
                    margin=margin,
                )

            # -------------------------------------------------
            # Margin gate
            # -------------------------------------------------

            if (
                len(probabilities) > 1
                and margin
                < self._margin_threshold
            ):
                logger.info(
                    "ML intent rejected as ambiguous: "
                    "%s confidence %.3f, "
                    "margin %.3f < %.3f",
                    predicted_intent.value,
                    confidence,
                    margin,
                    self._margin_threshold,
                )

                return IntentPrediction(
                    intent=IntentType.UNKNOWN,
                    confidence=confidence,
                    all_scores=all_scores,
                    margin=margin,
                )

            return IntentPrediction(
                intent=predicted_intent,
                confidence=confidence,
                all_scores=all_scores,
                margin=margin,
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
                margin=0.0,
            )

    def _predict_keywords(
        self,
        text: str,
    ) -> IntentPrediction:
        """
        Deterministic fallback classifier.
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

                elif re.search(
                    rf"\b{re.escape(keyword_lower)}\b",
                    text_lower,
                ):
                    score += 1

            scores[
                intent_enum.value
            ] = score

        ranked = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        if not ranked:
            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores=scores,
                margin=0.0,
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
                margin=0.0,
            )

        margin = float(
            best_score - second_score
        )

        # If two intents have equal keyword evidence,
        # don't guess.
        if (
            best_score == second_score
            and best_score > 0
        ):
            logger.info(
                "Keyword intent ambiguous: %s",
                ranked[:3],
            )

            return IntentPrediction(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                all_scores=scores,
                margin=margin,
            )

        confidence = min(
            0.70
            + (best_score * 0.08),
            0.95,
        )

        intent = IntentType(
            best_intent_value
        )

        logger.info(
            "Keyword fallback prediction: %s "
            "(confidence: %.3f, margin: %.3f)",
            intent.value,
            confidence,
            margin,
        )

        return IntentPrediction(
            intent=intent,
            confidence=confidence,
            all_scores=scores,
            margin=margin,
        )

    @staticmethod
    def _clean_text(
        text: str,
    ) -> str:
        """
        Normalize user text before classification.
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
        Convert model class labels to IntentType.
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
