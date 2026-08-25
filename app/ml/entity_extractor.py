import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple

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
            r'(?:under|below|less than|max|maximum|budget|above|over|more than|min|minimum)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
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
        if model_loader.entity_vectorizer is None or model_loader.entity_model is None:
            return []

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

                predicted_label = str(label)

                if probabilities is not None:
                    classes = list(
                        model_loader.entity_model.classes_
                    )

                    try:
                        predicted_class_index = classes.index(
                            predicted_label
                        )
                        confidence = float(
                            probabilities[
                                index
                            ][
                                predicted_class_index
                            ]
                        )
                    except ValueError:
                        confidence = 0.0
                else:
                    confidence = 1.0

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
                    captured_groups = [g for g in match.groups() if g is not None]
                    value = captured_groups[-1] if captured_groups else match.group(0)
                    if not value:
                        continue

                    metadata = {}
                    if entity_type == EntityType.PRICE:
                        full_match = match.group(0).lower()
                        if any(keyword in full_match for keyword in [
                            "under", "below", "less than", "max", "maximum", "budget"
                        ]):
                            metadata["operator"] = "max"
                        elif any(keyword in full_match for keyword in [
                            "above", "over", "more than", "min", "minimum"
                        ]):
                            metadata["operator"] = "min"
                        else:
                            metadata["operator"] = "exact"

                    entities.append(ExtractedEntity(
                        entity_type=entity_type,
                        value=value.strip(),
                        confidence=0.9,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        normalized_value=self._normalize_value(entity_type, value),
                        metadata=metadata,
                    ))
        return entities

    def _extract_keywords(self, text: str) -> List[ExtractedEntity]:
        """
        Extract entities using whole-word keyword matching.
        """

        entities = []
        text_lower = text.lower()
        def add_keyword_entities(keywords: List[str], entity_type: EntityType) -> None:
            for keyword in keywords:
                match = re.search(rf"\b{re.escape(keyword.lower())}\b", text_lower)
                if not match:
                    continue
                entities.append(ExtractedEntity(
                    entity_type=entity_type,
                    value=keyword,
                    confidence=0.85,
                    start_pos=match.start(),
                    end_pos=match.end(),
                    normalized_value=self._normalize_value(entity_type, keyword),
                ))

        add_keyword_entities(self.COLORS, EntityType.COLOR)
        add_keyword_entities(self.FITS, EntityType.FIT)
        add_keyword_entities(self.PRODUCTS, EntityType.PRODUCT)
        add_keyword_entities(self.BRANDS, EntityType.BRAND)

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

    def _deduplicate(
        self,
        entities: List[ExtractedEntity],
    ) -> List[ExtractedEntity]:
        """
        Remove duplicate and overlapping entities.

        Priority:
        1. Higher confidence.
        2. Longer span when confidence is equal.
        3. Preserve different entity types when spans do not overlap.
        """

        if not entities:
            return []

        sorted_entities = sorted(
            entities,
            key=lambda entity: (
                -float(entity.confidence),
                -(
                    entity.end_pos
                    - entity.start_pos
                ),
                entity.start_pos,
            ),
        )

        selected: List[ExtractedEntity] = []

        for candidate in sorted_entities:
            candidate_start = candidate.start_pos
            candidate_end = candidate.end_pos

            duplicate = False

            for existing in selected:
                existing_start = existing.start_pos
                existing_end = existing.end_pos

                overlaps = (
                    candidate_start < existing_end
                    and candidate_end > existing_start
                )

                if not overlaps:
                    continue

                same_type = (
                    candidate.entity_type
                    == existing.entity_type
                )

                same_value = (
                    (
                        candidate.normalized_value
                        or candidate.value
                    ).strip().lower()
                    ==
                    (
                        existing.normalized_value
                        or existing.value
                    ).strip().lower()
                )

                if same_type or same_value:
                    duplicate = True
                    break

                # Different entity types may overlap.
                # Prefer the higher-confidence entity.
                if (
                    candidate.confidence
                    <= existing.confidence
                ):
                    duplicate = True
                    break

            if not duplicate:
                selected.append(candidate)

        return sorted(
            selected,
            key=lambda entity: entity.start_pos,
        )


entity_extractor = EntityExtractor()
