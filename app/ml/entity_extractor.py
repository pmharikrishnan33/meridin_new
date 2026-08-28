import asyncio
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
    Extracts entities from user messages.

    Uses the trained ML model when available and combines it with
    deterministic regex/vocabulary extraction for reliable clothing
    search terms.
    """

    PATTERNS = {
        EntityType.SIZE: [
            r"\b(xs|s|m|l|xl|xxl|3xl|4xl|xxxxl|xxxl)\b",
            r"\bsize\s+(xs|s|m|l|xl|xxl|3xl|4xl|xxxxl|xxxl)\b",
        ],
        EntityType.PRICE: [
            (
                r"(?:under|below|less than|max|maximum|budget|"
                r"above|over|more than|min|minimum)\s*"
                r"(?:rs\.?|inr|₹)?\s*"
                r"(\d+(?:,\d{3})*(?:\.\d{2})?)"
            ),
            r"(?:rs\.?|inr|₹)\s*(\d+(?:,\d{3})*(?:\.\d{2})?)",
            (
                r"(\d+(?:,\d{3})*(?:\.\d{2})?)\s*"
                r"(?:rs\.?|inr|₹)"
            ),
            (
                r"price\s*(?:rs\.?|inr|₹)?\s*"
                r"(\d+(?:,\d{3})*(?:\.\d{2})?)"
            ),
        ],
        EntityType.ORDER_ID: [
            r"\b(?:order|ord)[\s#:-]*([A-Z0-9]{6,})\b",
            r"\b([A-Z]{2,3}\d{6,})\b",
        ],
    }

    COLORS = [
        "black",
        "white",
        "blue",
        "red",
        "green",
        "yellow",
        "pink",
        "purple",
        "orange",
        "grey",
        "gray",
        "brown",
        "beige",
        "navy",
        "maroon",
        "teal",
        "olive",
        "gold",
        "silver",
        "cream",
        "ivory",
        "charcoal",
        "khaki",
    ]

    FITS = [
        "regular",
        "slim",
        "skinny",
        "oversized",
        "loose",
        "relaxed",
        "tapered",
        "straight",
        "bootcut",
        "flare",
        "athletic",
    ]

    PRODUCTS = [
        "hoodie",
        "t-shirt",
        "tshirt",
        "shirt",
        "jeans",
        "pants",
        "trousers",
        "shorts",
        "jacket",
        "coat",
        "sweater",
        "sweatshirt",
        "cardigan",
        "kurta",
        "top",
        "dress",
        "skirt",
        "leggings",
        "joggers",
        "cargo",
    ]

    BRANDS = [
        "nike",
        "puma",
        "adidas",
        "levis",
        "zara",
        "roadster",
        "hrx",
        "max",
        "allen solly",
        "jockey",
        "van heusen",
        "muji",
        "sparx",
    ]

    MATERIALS = [
        "cotton",
        "linen",
        "denim",
        "silk",
        "wool",
        "polyester",
        "rayon",
        "viscose",
        "nylon",
        "leather",
    ]

    GENDERS = [
        "men",
        "mens",
        "male",
        "women",
        "womens",
        "female",
        "unisex",
        "boys",
        "girls",
        "kids",
    ]

    STYLES = [
        "casual",
        "formal",
        "party",
        "streetwear",
        "traditional",
        "western",
        "ethnic",
    ]

    PATTERNS_LIST = [
        "plain",
        "printed",
        "print",
        "striped",
        "stripe",
        "checked",
        "checkered",
        "floral",
        "graphic",
        "solid",
        "polka",
    ]

    def __init__(self) -> None:
        pass

    async def extract_async(
        self,
        text: str,
        intent: Optional[str] = None,
    ) -> EntityExtractionResult:
        """
        Run synchronous extraction in a worker thread.
        """

        return await asyncio.to_thread(
            self.extract,
            text,
            intent,
        )

    def extract(
        self,
        text: str,
        intent: Optional[str] = None,
    ) -> EntityExtractionResult:
        """
        Extract all entities from text.
        """

        if not text or not text.strip():
            return EntityExtractionResult(
                entities=[],
                extracted_dict={},
            )

        entities: List[ExtractedEntity] = []

        if (
            model_loader.entity_model
            and model_loader.entity_vectorizer
        ):
            entities.extend(
                self._extract_ml(text)
            )

        entities.extend(
            self._extract_regex(text)
        )

        entities.extend(
            self._extract_keywords(text)
        )

        entities = self._deduplicate(
            entities
        )

        extracted_dict: Dict[str, Any] = {}

        for entity in entities:
            key = entity.entity_type.value

            if key not in extracted_dict:
                extracted_dict[key] = (
                    entity.normalized_value
                    or entity.value
                )

        logger.debug(
            f"Extracted entities: {extracted_dict}"
        )

        return EntityExtractionResult(
            entities=entities,
            extracted_dict=extracted_dict,
        )

    def _extract_ml(
        self,
        text: str,
    ) -> List[ExtractedEntity]:
        """
        Extract entities using the trained NER model.
        """

        if (
            model_loader.entity_vectorizer is None
            or model_loader.entity_model is None
        ):
            return []

        try:
            tokens = list(
                re.finditer(
                    r"\S+",
                    text,
                )
            )

            if not tokens:
                return []

            token_values = [
                match.group(0)
                for match in tokens
            ]

            vectorized = (
                model_loader.entity_vectorizer.transform(
                    token_values
                )
            )

            labels = (
                model_loader.entity_model.predict(
                    vectorized
                )
            )

            probabilities = None

            if hasattr(
                model_loader.entity_model,
                "predict_proba",
            ):
                probabilities = (
                    model_loader.entity_model.predict_proba(
                        vectorized
                    )
                )

            entities: List[ExtractedEntity] = []

            current_type: Optional[EntityType] = None
            current_tokens: List[str] = []
            current_start: Optional[int] = None
            current_end: Optional[int] = None
            confidences: List[float] = []

            def flush_current() -> None:
                nonlocal current_type
                nonlocal current_tokens
                nonlocal current_start
                nonlocal current_end
                nonlocal confidences

                if (
                    current_type is None
                    or current_start is None
                    or current_end is None
                ):
                    return

                value = " ".join(
                    current_tokens
                )

                confidence = (
                    sum(confidences)
                    / len(confidences)
                    if confidences
                    else 0.0
                )

                entities.append(
                    ExtractedEntity(
                        entity_type=current_type,
                        value=value,
                        confidence=confidence,
                        start_pos=current_start,
                        end_pos=current_end,
                        normalized_value=(
                            self._normalize_value(
                                current_type,
                                value,
                            )
                        ),
                    )
                )

                current_type = None
                current_tokens = []
                current_start = None
                current_end = None
                confidences = []

            classes = []

            if probabilities is not None:
                classes = list(
                    model_loader.entity_model.classes_
                )

            for index, (
                token,
                label,
            ) in enumerate(
                zip(tokens, labels)
            ):
                label = str(label)

                if (
                    label == "O"
                    or "-" not in label
                ):
                    flush_current()
                    continue

                prefix, raw_type = label.split(
                    "-",
                    1,
                )

                try:
                    entity_type = EntityType(
                        raw_type.lower()
                    )
                except ValueError:
                    flush_current()
                    continue

                confidence = 1.0

                if probabilities is not None:
                    try:
                        class_index = classes.index(
                            label
                        )

                        confidence = float(
                            probabilities[index][
                                class_index
                            ]
                        )
                    except (
                        ValueError,
                        IndexError,
                        TypeError,
                    ):
                        confidence = 0.0

                if (
                    prefix == "B"
                    or entity_type != current_type
                ):
                    flush_current()

                    current_type = entity_type
                    current_tokens = [
                        token.group(0)
                    ]
                    current_start = token.start()
                    current_end = token.end()
                    confidences = [
                        confidence
                    ]

                elif prefix == "I":
                    current_tokens.append(
                        token.group(0)
                    )
                    current_end = token.end()
                    confidences.append(
                        confidence
                    )

                else:
                    flush_current()

            flush_current()

            return entities

        except Exception as exc:
            logger.warning(
                f"ML entity extraction failed: {exc}"
            )
            return []

    def _extract_regex(
        self,
        text: str,
    ) -> List[ExtractedEntity]:
        """
        Extract entities using regex patterns.
        """

        entities: List[ExtractedEntity] = []
        text_lower = text.lower()

        for (
            entity_type,
            patterns,
        ) in self.PATTERNS.items():

            for pattern in patterns:
                matches = re.finditer(
                    pattern,
                    text_lower,
                    re.IGNORECASE,
                )

                for match in matches:
                    captured_groups = [
                        group
                        for group in match.groups()
                        if group is not None
                    ]

                    value = (
                        captured_groups[-1]
                        if captured_groups
                        else match.group(0)
                    )

                    if not value:
                        continue

                    metadata: Dict[str, Any] = {}

                    if entity_type == EntityType.PRICE:
                        full_match = (
                            match.group(0).lower()
                        )

                        if any(
                            keyword in full_match
                            for keyword in [
                                "under",
                                "below",
                                "less than",
                                "max",
                                "maximum",
                                "budget",
                            ]
                        ):
                            metadata["operator"] = "max"

                        elif any(
                            keyword in full_match
                            for keyword in [
                                "above",
                                "over",
                                "more than",
                                "min",
                                "minimum",
                            ]
                        ):
                            metadata["operator"] = "min"

                        else:
                            metadata["operator"] = "exact"

                    entities.append(
                        ExtractedEntity(
                            entity_type=entity_type,
                            value=value.strip(),
                            confidence=0.90,
                            start_pos=match.start(),
                            end_pos=match.end(),
                            normalized_value=(
                                self._normalize_value(
                                    entity_type,
                                    value,
                                )
                            ),
                            metadata=metadata,
                        )
                    )

        return entities

    def _extract_keywords(
        self,
        text: str,
    ) -> List[ExtractedEntity]:
        """
        Extract entities using deterministic vocabulary matching.
        """

        entities: List[ExtractedEntity] = []
        text_lower = text.lower()

        def add_keyword_entities(
            keywords: List[str],
            entity_type: EntityType,
        ) -> None:
            for keyword in keywords:
                match = re.search(
                    rf"\b{re.escape(keyword.lower())}\b",
                    text_lower,
                )

                if not match:
                    continue

                entities.append(
                    ExtractedEntity(
                        entity_type=entity_type,
                        value=keyword,
                        confidence=0.85,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        normalized_value=(
                            self._normalize_value(
                                entity_type,
                                keyword,
                            )
                        ),
                    )
                )

        add_keyword_entities(
            self.COLORS,
            EntityType.COLOR,
        )

        add_keyword_entities(
            self.FITS,
            EntityType.FIT,
        )

        add_keyword_entities(
            self.PRODUCTS,
            EntityType.PRODUCT,
        )

        add_keyword_entities(
            self.BRANDS,
            EntityType.BRAND,
        )

        add_keyword_entities(
            self.MATERIALS,
            EntityType.MATERIAL,
        )

        add_keyword_entities(
            self.GENDERS,
            EntityType.GENDER,
        )

        add_keyword_entities(
            self.STYLES,
            EntityType.STYLE,
        )

        add_keyword_entities(
            self.PATTERNS_LIST,
            EntityType.PATTERN,
        )

        return entities

    def _normalize_value(
        self,
        entity_type: EntityType,
        value: str,
    ) -> str:
        """
        Normalize extracted value.
        """

        value = value.strip().lower()

        if entity_type == EntityType.SIZE:
            size_map = {
                "xs": "XS",
                "s": "S",
                "m": "M",
                "l": "L",
                "xl": "XL",
                "xxl": "XXL",
                "3xl": "3XL",
                "xxxl": "3XL",
                "4xl": "4XL",
                "xxxxl": "4XL",
            }

            return size_map.get(
                value,
                value.upper(),
            )

        if entity_type == EntityType.PRICE:
            numeric = re.sub(
                r"[^\d.]",
                "",
                value,
            )

            try:
                return str(
                    float(numeric)
                )
            except ValueError:
                return value

        if entity_type in {
            EntityType.COLOR,
            EntityType.FIT,
            EntityType.PRODUCT,
            EntityType.CATEGORY,
            EntityType.BRAND,
            EntityType.MATERIAL,
            EntityType.GENDER,
            EntityType.STYLE,
            EntityType.PATTERN,
        }:
            return value.capitalize()

        return value

    def _deduplicate(
        self,
        entities: List[ExtractedEntity],
    ) -> List[ExtractedEntity]:
        """
        Remove duplicate and overlapping entities.
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

        selected: List[
            ExtractedEntity
        ] = []

        for candidate in sorted_entities:
            duplicate = False

            for existing in selected:
                overlaps = (
                    candidate.start_pos
                    < existing.end_pos
                    and candidate.end_pos
                    > existing.start_pos
                )

                if not overlaps:
                    continue

                same_type = (
                    candidate.entity_type
                    == existing.entity_type
                )

                candidate_value = (
                    candidate.normalized_value
                    or candidate.value
                ).strip().lower()

                existing_value = (
                    existing.normalized_value
                    or existing.value
                ).strip().lower()

                same_value = (
                    candidate_value
                    == existing_value
                )

                if same_type or same_value:
                    duplicate = True
                    break

                if (
                    candidate.confidence
                    <= existing.confidence
                ):
                    duplicate = True
                    break

            if not duplicate:
                selected.append(
                    candidate
                )

        return sorted(
            selected,
            key=lambda entity: entity.start_pos,
        )


entity_extractor = EntityExtractor()