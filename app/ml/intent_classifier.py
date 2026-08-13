from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.core.config import settings
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

    def predict(self, text: str) -> IntentPrediction:
        """
        Predict intent for given text.
        """
        import re

        # --- NEW: Exact match intercept for common greetings ---
        # Strip all punctuation and extra whitespace so "Hi!" or "Hello..." securely match
        text_clean = re.sub(r'[^\w\s]', '', text).strip().lower()
        
        if text_clean in {"hi", "hello", "hey", "namaste", "good morning", "good evening", "hii"}:
            return IntentPrediction(
                intent=IntentType.GREETING,
                confidence=0.95,
                all_scores={IntentType.GREETING.value: 1.0}
            )
        # -------------------------------------------------------

        # Try ML model first
        ACTIVE_NER_INTENTS = {
            "product_search",
        }

        if (
            intent in ACTIVE_NER_INTENTS
            and model_loader.entity_model
            and model_loader.entity_vectorizer
        ):
            ml_entities = self._extract_ml(text)
            entities.extend(ml_entities)

        # Fallback to keyword-based
        logger.warning("Intent model not loaded, using keyword fallback")
        return self._predict_keywords(text)
    
    def _predict_ml(self, text: str) -> IntentPrediction:
        """
        Predict using trained ML model.
        """

        try:
            # Vectorize text
            vectorized = model_loader.intent_vectorizer.transform([text])

            # Get prediction probabilities
            probabilities = model_loader.intent_model.predict_proba(vectorized)[0]
            classes = model_loader.intent_model.classes_

            # Get top prediction
            max_idx = np.argmax(probabilities)
            predicted_intent_str = classes[max_idx]
            confidence = float(probabilities[max_idx])

            # Map to IntentType enum
            intent = self._map_to_intent_type(predicted_intent_str)

            # Build all scores dict
            all_scores = {
                self._map_to_intent_type(cls).value: float(prob)
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
        scores = {}

        for intent, keywords in self.INTENT_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                # Use word-boundary matching so short keywords like "hi"
                # don't match inside larger words (e.g. "history").
                if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                    score += 1
            scores[intent.value] = score

        # Find best match
        if scores:
            best_intent = max(scores, key=scores.get)
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
