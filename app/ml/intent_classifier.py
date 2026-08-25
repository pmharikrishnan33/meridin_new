from dataclasses import dataclass
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
    Classifies user message intent using trained ML model.
    Falls back to keyword-based classification if model unavailable.
    """

    # Fallback keywords for each intent (used when model not available)
    INTENT_KEYWORDS = {
        IntentType.GREETING: ["hi", "hello", "hey", "good morning", "good evening", "namaste"],
        IntentType.PRODUCT_SEARCH: ["need", "want", "looking for", "search", "find", "show me", "buy", "purchase"],
        IntentType.PRODUCT_INQUIRY: ["tell me about", "details", "specs", "material", "fabric", "how is", "describe"],
        IntentType.AVAILABILITY: ["available", "in stock", "stock", "have", "size", "xl", "xxl"],
        IntentType.ORDER_STATUS: ["order", "track", "where is", "delivered", "shipped", "status", "order id"],
        IntentType.CANCEL_ORDER: ["cancel", "return", "refund", "don't want", "change mind"],
        IntentType.RETURN_REQUEST: ["return", "exchange", "replace", "wrong size", "defective"],
        IntentType.COMPLAINT: ["complaint", "issue", "problem", "wrong", "bad", "poor", "disappointed", "angry"],
        IntentType.THANKS: ["thanks", "thank you", "thx", "ty", "appreciate"],
    }

    def __init__(self):
        self._confidence_threshold = 0.25

    def predict(
        self,
        text: str,
    ) -> IntentPrediction:
        """
        Predict intent only.

        Entity extraction is handled separately
        by EntityExtractor.
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

        # Deterministic greetings.
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
                    IntentType.GREETING.value: 0.95
                },
            )

        # Use ML when available.
        if (
            model_loader.intent_model is not None
            and model_loader.intent_vectorizer is not None
        ):
            return self._predict_ml(
                text_clean
            )

        # Safe keyword fallback.
        logger.warning(
            "Intent model not loaded; "
            "using keyword fallback"
        )

        return self._predict_keywords(
            text_clean
        )
    
    def _predict_ml(self, text: str) -> IntentPrediction:
        """
        Predict using trained ML model.
        """
        if model_loader.intent_vectorizer is None or model_loader.intent_model is None:
            return self._predict_keywords(text)

        try:
            # Vectorize text
            vectorized = model_loader.intent_vectorizer.transform([text])

            # Get prediction probabilities
            probabilities = model_loader.intent_model.predict_proba(vectorized)[0]
            classes = model_loader.intent_model.classes_

            # Get top prediction
            max_idx = np.argmax(probabilities)
            predicted_intent_str = str(classes[max_idx])
            confidence = float(probabilities[max_idx])

            # Map to IntentType enum
            intent = self._map_to_intent_type(predicted_intent_str)

            # Build all scores dict
            all_scores = {
                self._map_to_intent_type(str(cls)).value: float(prob)
                for cls, prob in zip(classes, probabilities)
            }

            logger.debug(
                f"Intent ML prediction: {intent.value} "
                f"(confidence: {confidence:.3f})"
            )

            return IntentPrediction(
                intent=intent,
                confidence=confidence,
                all_scores=all_scores
            )

        except Exception as e:
            logger.exception(f"ML intent prediction failed: {e}")
            return self._predict_keywords(text)

    def _predict_keywords(self, text: str) -> IntentPrediction:
        """
        Keyword-based intent classification fallback.
        """

        import re
        text_lower = text.lower()
        scores: Dict[str, int] = {}

        for intent_enum, keywords in self.INTENT_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                # Use word-boundary matching so short keywords like "hi"
                # don't match inside larger words (e.g. "history").
                if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                    score += 1
            scores[intent_enum.value] = score

        # Find best match
        if scores:
            best_intent = max(scores, key=lambda k: scores[k])
            best_score = scores[best_intent]

            # Normalize confidence (0-1)
            confidence = min(best_score / 3.0, 1.0) if best_score > 0 else 0.1

            if best_score > 0:
                intent = IntentType(best_intent)
            else:
                intent = IntentType.UNKNOWN
                confidence = 0.1
        else:
            intent = IntentType.UNKNOWN
            confidence = 0.1

        logger.debug(f"Intent keyword prediction: {intent.value} (confidence: {confidence:.3f})")

        return IntentPrediction(
            intent=intent,
            confidence=confidence,
            all_scores=scores
        )

    def _map_to_intent_type(self, intent_str: str) -> IntentType:
        """
        Map model class string to IntentType enum.
        """

        intent_lower = intent_str.lower()
        aliases = {
            "product_availability": IntentType.AVAILABILITY.value,
            "cancel_request": IntentType.CANCEL_ORDER.value,
        }
        normalized_intent = aliases.get(intent_lower, intent_lower)

        try:
            return IntentType(normalized_intent)
        except ValueError:
            # Try fuzzy matching
            for intent in IntentType:
                if intent.value in intent_lower or intent_lower in intent.value:
                    return intent
            return IntentType.UNKNOWN


intent_classifier = IntentClassifier()
