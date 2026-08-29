from __future__ import annotations

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
    Extract entities from customer messages.

    Extraction layers:

        1. ML NER model
        2. deterministic regex extraction
        3. catalog-independent keyword extraction

    The deterministic layers intentionally remain active even when
    the ML model is available. This protects important commerce
    entities such as colors, sizes, prices and categories from a
    low-confidence NER prediction.
    """

    PATTERNS = {
        EntityType.SIZE: [
            r"\b(?:size\s+)?(xs|xxxl|xxl|xl|l|m|s|3xl|4xl|5xl)\b",
            r"\b(size)\s*[:\-]?\s*(xs|xxxl|xxl|xl|l|m|s|3xl|4xl|5xl)\b",
        ],

        EntityType.PRICE: [
            (
                r"(?:under|below|less than|max|maximum|budget)"
                r"\s*(?:rs\.?|inr|₹)?\s*"
                r"(\d+(?:,\d{3})*(?:\.\d{2})?)"
            ),
            (
                r"(?:above|over|more than|min|minimum)"
                r"\s*(?:rs\.?|inr|₹)?\s*"
                r"(\d+(?:,\d{3})*(?:\.\d{2})?)"
            ),
            (
                r"(?:rs\.?|inr|₹)\s*"
                r"(\d+(?:,\d{3})*(?:\.\d{2})?)"
            ),
            (
                r"(\d+(?:,\d{3})*(?:\.\d{2})?)"
                r"\s*(?:rs\.?|inr|₹)"
            ),
            (
                r"price\s*"
                r"(?:rs\.?|inr|₹)?\s*"
                r"(\d+(?:,\d{3})*(?:\.\d{2})?)"
            ),
        ],

        EntityType.ORDER_ID: [
            r"\b(?:order|ord)[\s#:\-]*([A-Z0-9]{6,})\b",
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
        "navy blue",
        "maroon",
        "burgundy",
        "teal",
        "olive",
        "olive green",
        "gold",
        "silver",
        "cream",
        "ivory",
        "charcoal",
        "charcoal grey",
        "charcoal gray",
        "khaki",
        "baby blue",
        "baby pink",
        "sky blue",
        "emerald green",
        "mustard yellow",
        "peach",
        "coral",
        "lavender",
        "chocolate brown",
    ]

    FITS = [
        "regular fit",
        "regular",
        "slim fit",
        "slim",
        "skinny",
        "oversized",
        "oversize",
        "loose fit",
        "loose",
        "relaxed fit",
        "relaxed",
        "tapered",
        "straight",
        "bootcut",
        "flare",
        "athletic",
    ]

    # Clothing category vocabulary mirrors inventory_metadata.category_aliases.
    CATEGORIES = [
        "dresses", "dress", "gown", "frock", "tops", "top",
        "shirts", "shirt", "button-down", "button down", "button-up", "button up",
        "t-shirts", "t-shirt", "tshirts", "tshirt", "tee", "tees", "t shirt", "t shirts",
        "kurtis", "kurti", "kurtas", "kurta", "ethnic-wear", "ethnic wear", "ethnic", "traditional wear",
        "sarees", "saree", "skirts", "skirt", "jeans", "jean", "pants", "pant",
        "shorts", "short", "co-ords", "co-ord", "coord", "coords", "co ord", "co ords", "matching set",
        "jackets", "jacket", "polos", "polo", "polo shirt", "polo shirts", "chinos", "chino",
        "cargo pants", "cargo pant", "cargo", "track pants", "track pant", "tracksuit pants",
        "hoodies", "hoodie", "sweatshirts", "sweatshirt", "sets", "set", "co-ord set",
    ]

    # Non-category product terms remain PRODUCT entities.
    PRODUCTS = [
        "coat", "sweater", "cardigan", "leggings", "joggers",
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

    GENDERS = [
        "women",
        "woman",
        "womens",
        "women's",
        "female",
        "ladies",
        "lady",
        "men",
        "man",
        "mens",
        "men's",
        "male",
        "gentlemen",
        "girls",
        "girl",
        "girl's",
        "girls'",
        "boys",
        "boy",
        "boy's",
        "boys'",
        "unisex",
        "gender neutral",
        "gender-neutral",
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
        "velvet",
        "chiffon",
        "georgette",
        "corduroy",
    ]

    DRESS_STYLES = [
        "maxi",
        "midi",
        "mini",
        "a-line",
        "a line",
        "bodycon",
    ]

    def __init__(self) -> None:
        pass

    # =========================================================
    # PUBLIC EXTRACTION
    # =========================================================

    def extract(
        self,
        text: str,
        intent: Optional[str] = None,
    ) -> EntityExtractionResult:
        """
        Extract entities from text.
        """

        if not text or not text.strip():
            return EntityExtractionResult(
                entities=[],
                extracted_dict={},
            )

        entities: List[ExtractedEntity] = []

        # -----------------------------------------------------
        # ML
        # -----------------------------------------------------

        if (
            model_loader.entity_model is not None
            and model_loader.entity_vectorizer is not None
        ):
            entities.extend(
                self._extract_ml(text)
            )

        # -----------------------------------------------------
        # REGEX
        # -----------------------------------------------------

        entities.extend(
            self._extract_regex(text)
        )

        # -----------------------------------------------------
        # KEYWORDS
        # -----------------------------------------------------

        entities.extend(
            self._extract_keywords(text)
        )

        # -----------------------------------------------------
        # DEDUPLICATION
        # -----------------------------------------------------

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
            "Extracted entities: %s",
            extracted_dict,
        )

        return EntityExtractionResult(
            entities=entities,
            extracted_dict=extracted_dict,
        )

    # =========================================================
    # ML EXTRACTION
    # =========================================================

    def _extract_ml(
        self,
        text: str,
    ) -> List[ExtractedEntity]:
        """
        Extract entities using the trained token-level NER model.
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

            classes = []

            if hasattr(
                model_loader.entity_model,
                "classes_",
            ):
                classes = list(
                    model_loader.entity_model.classes_
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
                    or not current_tokens
                ):
                    return

                value = " ".join(
                    current_tokens
                )

                confidence = (
                    sum(confidences)
                    / len(confidences)
                    if confidences
                    else 1.0
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

            for index, (
                token_match,
                raw_label,
            ) in enumerate(
                zip(
                    tokens,
                    labels,
                )
            ):

                label = str(
                    raw_label
                )

                if (
                    label == "O"
                    or "-"
                    not in label
                ):
                    flush_current()
                    continue

                prefix, raw_type = (
                    label.split(
                        "-",
                        1,
                    )
                )

                try:
                    entity_type = EntityType(
                        raw_type.lower()
                    )
                except ValueError:
                    flush_current()
                    continue

                confidence = 1.0

                if (
                    probabilities is not None
                    and classes
                ):
                    try:
                        class_index = classes.index(
                            label
                        )

                        confidence = float(
                            probabilities[
                                index
                            ][
                                class_index
                            ]
                        )
                    except (
                        ValueError,
                        IndexError,
                        TypeError,
                    ):
                        confidence = 0.0

                token_value = (
                    token_match.group(0)
                )

                if (
                    prefix.upper() == "B"
                    or entity_type != current_type
                ):

                    flush_current()

                    current_type = entity_type
                    current_tokens = [
                        token_value
                    ]
                    current_start = (
                        token_match.start()
                    )
                    current_end = (
                        token_match.end()
                    )
                    confidences = [
                        confidence
                    ]

                elif (
                    prefix.upper() == "I"
                ):

                    current_tokens.append(
                        token_value
                    )

                    current_end = (
                        token_match.end()
                    )

                    confidences.append(
                        confidence
                    )

                else:

                    flush_current()

            flush_current()

            return entities

        except Exception as exc:

            logger.warning(
                "ML entity extraction failed: %s",
                exc,
            )

            return []

    # =========================================================
    # REGEX EXTRACTION
    # =========================================================

    def _extract_regex(
        self,
        text: str,
    ) -> List[ExtractedEntity]:
        """
        Extract deterministic entities using regular expressions.
        """

        entities: List[ExtractedEntity] = []

        text_lower = text.lower()

        for (
            entity_type,
            patterns,
        ) in self.PATTERNS.items():

            for pattern in patterns:

                for match in re.finditer(
                    pattern,
                    text_lower,
                    re.IGNORECASE,
                ):

                    value = None

                    # Prefer the final captured group because
                    # some patterns contain helper groups such as
                    # "size".
                    captured = [
                        group
                        for group in match.groups()
                        if group is not None
                    ]

                    if captured:
                        value = captured[-1]
                    else:
                        value = match.group(0)

                    if not value:
                        continue

                    metadata: Dict[str, Any] = {}

                    if (
                        entity_type
                        == EntityType.PRICE
                    ):

                        full_match = (
                            match.group(0)
                            .lower()
                        )

                        if any(
                            keyword in full_match
                            for keyword in (
                                "under",
                                "below",
                                "less than",
                                "max",
                                "maximum",
                                "budget",
                            )
                        ):
                            metadata[
                                "operator"
                            ] = "max"

                        elif any(
                            keyword in full_match
                            for keyword in (
                                "above",
                                "over",
                                "more than",
                                "min",
                                "minimum",
                            )
                        ):
                            metadata[
                                "operator"
                            ] = "min"

                        else:
                            metadata[
                                "operator"
                            ] = "exact"

                    entities.append(
                        ExtractedEntity(
                            entity_type=entity_type,
                            value=str(
                                value
                            ).strip(),
                            confidence=0.90,
                            start_pos=match.start(),
                            end_pos=match.end(),
                            normalized_value=(
                                self._normalize_value(
                                    entity_type,
                                    str(value),
                                )
                            ),
                            metadata=metadata,
                        )
                    )

        return entities

    # =========================================================
    # KEYWORD EXTRACTION
    # =========================================================

    def _extract_keywords(
        self,
        text: str,
    ) -> List[ExtractedEntity]:
        """
        Extract deterministic commerce entities from known vocabulary.
        """

        entities: List[ExtractedEntity] = []

        text_lower = text.lower()

        def add_keyword_entities(
            keywords: List[str],
            entity_type: EntityType,
        ) -> None:

            # Longest terms first so:
            #
            # "navy blue"
            #
            # wins over:
            #
            # "blue"
            #
            for keyword in sorted(
                keywords,
                key=len,
                reverse=True,
            ):

                normalized_keyword = (
                    keyword.lower()
                )

                pattern = (
                    rf"(?<!\w)"
                    rf"{re.escape(normalized_keyword)}"
                    rf"(?!\w)"
                )

                match = re.search(
                    pattern,
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
            self.CATEGORIES,
            EntityType.CATEGORY,
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
            self.GENDERS,
            EntityType.GENDER,
        )

        add_keyword_entities(
            self.MATERIALS,
            EntityType.MATERIAL,
        )

        # Dress-specific styles from the new category requirements.
        add_keyword_entities(
            self.DRESS_STYLES,
            EntityType.STYLE,
        )

        return entities

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_value(
        entity_type: EntityType,
        value: str,
    ) -> str:
        """
        Normalize extracted entity values.
        """

        normalized = (
            value.strip().lower()
        )

        if entity_type == EntityType.SIZE:

            size_map = {
                "xs": "XS",
                "s": "S",
                "m": "M",
                "l": "L",
                "xl": "XL",
                "xxl": "2XL",
                "xxxl": "3XL",
                "3xl": "3XL",
                "xxxxl": "4XL",
                "4xl": "4XL",
                "5xl": "5XL",
            }

            return size_map.get(
                normalized,
                normalized.upper(),
            )

        if entity_type == EntityType.PRICE:

            numeric = re.sub(
                r"[^\d.]",
                "",
                normalized,
            )

            try:
                return str(
                    float(numeric)
                )
            except ValueError:
                return normalized

        if entity_type == EntityType.COLOR:

            aliases = {
                "gray": "Grey",
                "navy": "Navy",
                "olive": "Olive",
                "charcoal": "Charcoal",
                "mustard": "Mustard Yellow",
                "emerald": "Emerald Green",
                "skyblue": "Sky Blue",
                "babyblue": "Baby Blue",
                "babypink": "Baby Pink",
                "chocolate": "Chocolate Brown",
            }

            if normalized in aliases:
                return aliases[
                    normalized
                ]

            return normalized.title()

        if entity_type == EntityType.FIT:
            return normalized.title()

        if entity_type == EntityType.PRODUCT:
            return normalized.lower()

        if entity_type == EntityType.BRAND:
            return normalized.title()

        if entity_type == EntityType.GENDER:
            gender_aliases = {
                "woman": "women",
                "womens": "women",
                "women's": "women",
                "female": "women",
                "ladies": "women",
                "lady": "women",
                "man": "men",
                "mens": "men",
                "men's": "men",
                "male": "men",
                "gentlemen": "men",
                "girl": "girls",
                "girl's": "girls",
                "girls'": "girls",
                "boy": "boys",
                "boy's": "boys",
                "boys'": "boys",
                "gender neutral": "unisex",
                "gender-neutral": "unisex",
            }

            return gender_aliases.get(
                normalized,
                normalized,
            )

        if entity_type == EntityType.STYLE:

            style_aliases = {
                "a line": "a-line",
            }

            return style_aliases.get(
                normalized,
                normalized,
            )

        return normalized

    # =========================================================
    # DEDUPLICATION
    # =========================================================

    @staticmethod
    def _deduplicate(
        entities: List[ExtractedEntity],
    ) -> List[ExtractedEntity]:
        """
        Remove duplicate/overlapping entities.

        Priority:

        1. higher confidence
        2. longer span
        3. earlier occurrence

        Different non-overlapping entity types are preserved.
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

            candidate_start = (
                candidate.start_pos
            )

            candidate_end = (
                candidate.end_pos
            )

            duplicate = False

            for existing in selected:

                existing_start = (
                    existing.start_pos
                )

                existing_end = (
                    existing.end_pos
                )

                overlaps = (
                    candidate_start
                    < existing_end
                    and candidate_end
                    > existing_start
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
                )

                existing_value = (
                    existing.normalized_value
                    or existing.value
                )

                same_value = (
                    candidate_value
                    .strip()
                    .lower()
                    ==
                    existing_value
                    .strip()
                    .lower()
                )

                if same_type or same_value:
                    duplicate = True
                    break

                # Clothing category vocabulary is authoritative for overlapping
                # product/category terms such as "shirt". Prefer CATEGORY so
                # the downstream metadata resolver can produce category IDs.
                if (
                    candidate.entity_type == EntityType.CATEGORY
                    and existing.entity_type == EntityType.PRODUCT
                ):
                    selected.remove(existing)
                    break

                if (
                    candidate.entity_type == EntityType.PRODUCT
                    and existing.entity_type == EntityType.CATEGORY
                ):
                    duplicate = True
                    break

                # Do not allow a lower-confidence overlapping
                # entity to replace a stronger entity.
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
            key=lambda entity: (
                entity.start_pos,
                entity.end_pos,
            ),
        )


entity_extractor = EntityExtractor()