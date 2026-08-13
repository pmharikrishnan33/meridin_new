import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from app.ml.loader import model_loader
from app.models.schemas import EntityType, ExtractedEntity
from app.utils.logger import logger


@dataclass
class EntityExtractionResult:
    """
    Result of entity extraction.
    """
    entities: List[ExtractedEntity]
    extracted_dict: Dict[str, Any]


class EntityExtractor:
    """
    Extracts entities from user message.
    Uses ML model when available, falls back to regex/vocabulary-based extraction.
    """

    # Regex patterns for common entities
    PATTERNS = {
        EntityType.SIZE: [
            r'\b(xs|s|m|l|xl|xxl|3xl|xxxxl)\b',
            r'\b(size\s+)?(xs|s|m|l|xl|xxl|3xl)\b',
        ],
        EntityType.PRICE: [
            r'(?:under|below|less than|max|maximum|budget)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'(?:rs\.?|inr|₹)\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
            r'(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:rs\.?|inr|₹)',
            r'price\s*(?:rs\.?|inr|₹)?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
        ],
        EntityType.ORDER_ID: [
            r'\b(?:order|ord)[\s#:-]*([A-Z0-9]{6,})\b',
            r'\b([A-Z]{2,3}\d{6,})\b',
        ],
    }

    # Color keywords
    COLORS = [
        "black", "white", "blue", "red", "green", "yellow", "pink", "purple",
        "orange", "grey", "gray", "brown", "beige", "navy", "maroon", "teal",
        "olive", "gold", "silver", "cream", "ivory", "charcoal", "khaki"
    ]

    # Fit keywords
    FITS = [
        "regular", "slim", "skinny", "oversized", "loose", "relaxed",
        "tapered", "straight", "bootcut", "flare", "athletic"
    ]

    # Product category keywords
    PRODUCTS = [
        "hoodie", "t-shirt", "tshirt", "shirt", "jeans", "pants", "trousers",
        "shorts", "jacket", "coat", "sweater", "sweatshirt", "cardigan",
        "kurta", "top", "dress", "skirt", "leggings", "joggers", "cargo"
    ]

    # Brand keywords used in search queries and catalog lookups.
    BRANDS = [
        "nike", "puma", "adidas", "levis", "zara", "roadster", "hrx",
        "max", "allen solly", "jockey", "van heusen", "muji", "sparx",
    ]

    def __init__(self):
        pass

    def extract(self, text: str, intent: Optional[str] = None) -> EntityExtractionResult:
        """
        Extract all entities from text.
        """

        entities = []

        # Extract using ML model if available
        if model_loader.entity_model and model_loader.entity_vectorizer:
            ml_entities = self._extract_ml(text)
            entities.extend(ml_entities)

        # Extract using regex patterns (always run as backup)
        regex_entities = self._extract_regex(text)
        entities.extend(regex_entities)

        # Extract using vocabulary/keywords
        keyword_entities = self._extract_keywords(text)
        entities.extend(keyword_entities)

        # Deduplicate entities (keep highest confidence)
        entities = self._deduplicate(entities)

        # Convert to dict for easy access
        extracted_dict = {}
        for entity in entities:
            if entity.entity_type.value not in extracted_dict:
                extracted_dict[entity.entity_type.value] = entity.normalized_value or entity.value

        logger.debug(f"Extracted entities: {extracted_dict}")

        return EntityExtractionResult(
            entities=entities,
            extracted_dict=extracted_dict
        )

    def _extract_ml(self, text: str) -> List[ExtractedEntity]:
        """
        Extract entities using trained ML model (NER).
        """

        try:
            # The shipped NER model is a token-level classifier. Preserve token
            # positions so predictions can be returned as normal entities.
            tokens = list(re.finditer(r"\S+", text))
            if not tokens:
                return []

            token_values = [match.group(0) for match in tokens]
            vectorized = model_loader.entity_vectorizer.transform(token_values)
            labels = model_loader.entity_model.predict(vectorized)
            probabilities = (
                model_loader.entity_model.predict_proba(vectorized)
                if hasattr(model_loader.entity_model, "predict_proba")
                else None
            )

            entities: List[ExtractedEntity] = []
            current_type: Optional[EntityType] = None
            current_tokens: List[str] = []
            current_start: Optional[int] = None
            current_end: Optional[int] = None
            confidences: List[float] = []

            def flush_current() -> None:
                nonlocal current_type, current_tokens, current_start, current_end, confidences
                if current_type is None or current_start is None or current_end is None:
                    return
                value = " ".join(current_tokens)
                entities.append(ExtractedEntity(
                    entity_type=current_type,
                    value=value,
                    confidence=sum(confidences) / len(confidences),
                    start_pos=current_start,
                    end_pos=current_end,
                    normalized_value=self._normalize_value(current_type, value),
                ))
                current_type = None
                current_tokens = []
                current_start = None
                current_end = None
                confidences = []

            for index, (token, label) in enumerate(zip(tokens, labels)):
                label = str(label)
                if label == "O" or "-" not in label:
                    flush_current()
                    continue

                prefix, raw_type = label.split("-", 1)
                try:
                    entity_type = EntityType(raw_type.lower())
                except ValueError:
                    flush_current()
                    continue

                confidence = float(max(probabilities[index])) if probabilities is not None else 1.0

                # An I tag starts a new entity if no matching B tag preceded it.
                if prefix == "B" or entity_type != current_type:
                    flush_current()
                    current_type = entity_type
                    current_tokens = [token.group(0)]
                    current_start = token.start()
                    current_end = token.end()
                    confidences = [confidence]
                elif prefix == "I":
                    current_tokens.append(token.group(0))
                    current_end = token.end()
                    confidences.append(confidence)
                else:
                    flush_current()

            flush_current()
            return entities
        except Exception as e:
            logger.warning(f"ML entity extraction failed: {e}")
            return []

    def _extract_regex(self, text: str) -> List[ExtractedEntity]:
        """
        Extract entities using regex patterns.
        """
        entities = []
        text_lower = text.lower()
        for entity_type, patterns in self.PATTERNS.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text_lower, re.IGNORECASE)
                for match in matches:
                    # FIX: Safely find the actual matched value, ignoring any None groups
                    captured_groups = [g for g in match.groups() if g is not None]
                    
                    # Grab the last captured group (the actual entity), or the full match
                    value = captured_groups[-1] if captured_groups else match.group(0)
                    
                    # Prevent any empty values from causing a crash
                    if not value:
                        continue
                        
                    entities.append(ExtractedEntity(
                        entity_type=entity_type,
                        value=value.strip(),
                        confidence=0.9,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        normalized_value=self._normalize_value(entity_type, value)
                    ))
        return entities

    def _extract_keywords(self, text: str) -> List[ExtractedEntity]:
        """
        Extract entities using keyword matching.
        """

        entities = []
        text_lower = text.lower()
        words = text_lower.split()

        # Check for colors
        for color in self.COLORS:
            if color in text_lower:
                entities.append(ExtractedEntity(
                    entity_type=EntityType.COLOR,
                    value=color,
                    confidence=0.85,
                    normalized_value=self._normalize_value(EntityType.COLOR, color)
                ))

        # Check for fits
        for fit in self.FITS:
            if fit in text_lower:
                entities.append(ExtractedEntity(
                    entity_type=EntityType.FIT,
                    value=fit,
                    confidence=0.85,
                    normalized_value=self._normalize_value(EntityType.FIT, fit)
                ))

        # Check for products
        for product in self.PRODUCTS:
            if product in text_lower:
                entities.append(ExtractedEntity(
                    entity_type=EntityType.PRODUCT,
                    value=product,
                    confidence=0.85,
                    normalized_value=self._normalize_value(EntityType.PRODUCT, product)
                ))

        # Check for brands
        for brand in self.BRANDS:
            if brand in text_lower:
                entities.append(ExtractedEntity(
                    entity_type=EntityType.BRAND,
                    value=brand,
                    confidence=0.85,
                    normalized_value=self._normalize_value(EntityType.BRAND, brand)
                ))

        return entities

    def _normalize_value(self, entity_type: EntityType, value: str) -> str:
        """
        Normalize extracted value.
        """

        value = value.strip().lower()

        if entity_type == EntityType.SIZE:
            # Normalize size formats
            size_map = {
                "xs": "XS", "s": "S", "m": "M", "l": "L",
                "xl": "XL", "xxl": "XXL", "3xl": "3XL",
                "xxxxl": "4XL", "xxxl": "3XL"
            }
            return size_map.get(value, value.upper())

        if entity_type == EntityType.PRICE:
            # Extract numeric value
            numeric = re.sub(r'[^\d.]', '', value)
            try:
                return str(float(numeric))
            except ValueError:
                return value

        if entity_type == EntityType.COLOR:
            return value.capitalize()

        if entity_type == EntityType.FIT:
            return value.capitalize()

        if entity_type == EntityType.PRODUCT:
            return value.capitalize()

        if entity_type == EntityType.BRAND:
            return value.capitalize()

        return value

    def _deduplicate(self, entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
        """
        Remove duplicate entities, keeping highest confidence.
        """

        seen = {}
        for entity in entities:
            key = (entity.entity_type, entity.normalized_value or entity.value)
            if key not in seen or entity.confidence > seen[key].confidence:
                seen[key] = entity

        return list(seen.values())


entity_extractor = EntityExtractor()
