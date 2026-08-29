from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.conversation.context import (
    ConversationContextManager,
)
from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    BotResponse,
    ConversationContext,
    EntityType,
    MessageUnderstanding,
    ProductSearchFilters,
)
from app.search.zero_result_handler import (
    build_relaxation_message,
    find_best_relaxation,
)
from app.services.catalog_metadata_service import (
    catalog_metadata_service,
)
from app.services.inventory_search_service import (
    inventory_search_service,
)
from app.services.product_service import (
    product_service,
)


class ProductSearchHandler(BaseHandler):
    """
    Handles PRODUCT_SEARCH intents.

    Workflow:

        user query
            ↓
        entity extraction
            ↓
        filter construction
            ↓
        catalog metadata normalization
            ↓
        required-attribute check
            ↓
        clarification if required
            ↓
        product search
            ↓
        zero-result relaxation
            ↓
        ranked results
            ↓
        pagination state
            ↓
        WhatsApp product response

    The handler intentionally does not search until all metadata-defined
    required attributes for the selected category are available.
    """

    MAX_PRODUCTS_PER_RESPONSE = 3
    DEFAULT_PRODUCTS_PER_RESPONSE = 3

    # Fetch enough candidates for ranking and pagination.
    SEARCH_LIMIT = 100

    # =========================================================
    # PUBLIC HANDLER
    # =========================================================

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[
            ConversationContext
        ],
    ) -> BotResponse:

        # =====================================================
        # 1. BUILD INITIAL FILTERS
        # =====================================================

        filters = (
            product_service.entities_to_filters(
                understanding.entities
            )
        )

        # =====================================================
        # 2. MERGE FOLLOW-UP FILTERS
        # =====================================================
        #
        # Example:
        #
        # First message:
        #     "I need a black shirt"
        #
        # Stored:
        #     category = shirts
        #     color = black
        #
        # Follow-up:
        #     "M"
        #
        # New filters:
        #     size = M
        #
        # We merge them before checking requirements.
        #

        if (
            conversation_context
            and conversation_context.last_search_filters
            and self._should_refine_previous_search(
                filters
            )
        ):

            filters_dict = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            merged = (
                ConversationContextManager.merge_filters(
                    conversation_context.last_search_filters,
                    filters_dict,
                )
            )

            filters = ProductSearchFilters(
                **merged
            )

        # =====================================================
        # 3. NORMALIZE AGAINST CATALOG METADATA
        # =====================================================

        filters, size_clarification = (
            await catalog_metadata_service.normalize_filters(
                tenant_id=tenant_id,
                filters=filters,
                source_text=understanding.original_text,
            )
        )

        if size_clarification:

            return BotResponse(
                response_type="text",
                text=size_clarification,
                metadata={
                    "needs_clarification": True,
                    "missing": "size",
                    "filters": filters.model_dump(
                        exclude_none=True
                    ),
                },
            )

        # =====================================================
        # 4. RECOVER CATEGORY FROM PREVIOUS CONTEXT
        # =====================================================

        if (
            not filters.category
            and conversation_context
            and conversation_context.current_category
        ):

            filters.category = (
                conversation_context.current_category
            )

            filters, size_clarification = (
                await catalog_metadata_service.normalize_filters(
                    tenant_id=tenant_id,
                    filters=filters,
                    source_text=understanding.original_text,
                )
            )

            if size_clarification:

                return BotResponse(
                    response_type="text",
                    text=size_clarification,
                    metadata={
                        "needs_clarification": True,
                        "missing": "size",
                    },
                )

        # =====================================================
        # 5. DETERMINE CATEGORY
        # =====================================================

        category = filters.category

        if not category:

            return BotResponse(
                response_type="text",
                text=(
                    "What type of clothing are you "
                    "looking for? For example, shirts, "
                    "t-shirts, dresses, jeans, or kurtas."
                ),
                quick_replies=[],
                metadata={
                    "needs_clarification": True,
                    "missing": "category",
                },
            )

        # =====================================================
        # 6. CHECK METADATA-DEFINED REQUIREMENTS
        # =====================================================
        #
        # Your inventory_metadata now defines requirements such as:
        #
        # men/shirts:
        #     color required
        #     size required
        #
        # women/dresses:
        #     dress_style required
        #     color required
        #     size required
        #
        # The handler converts the requirement keys into the values
        # available in ProductSearchFilters.
        #

        required_attributes = (
            await catalog_metadata_service
            .get_required_category_attributes(
                tenant_id=tenant_id,
                category=category,
            )
        )

        missing_requirements = (
            self._find_missing_requirements(
                filters=filters,
                understanding=understanding,
                required_attributes=required_attributes,
            )
        )

        if missing_requirements:

            return self._build_requirement_response(
                category=category,
                missing_requirements=missing_requirements,
                filters=filters,
            )

        # =====================================================
        # 7. SAVE CURRENT FILTER STATE BEFORE SEARCH
        # =====================================================

        if conversation_context:

            conversation_context.current_category = (
                category
            )

            conversation_context.last_search_filters = (
                filters.model_dump(
                    exclude_none=True
                )
            )

        # =====================================================
        # 8. DETERMINE PAGE SIZE
        # =====================================================

        feature_flags = (
            tenant_settings.get(
                "feature_flags",
                {},
            )
            or {}
        )

        configured_page_size = (
            feature_flags.get(
                "max_products_per_response",
                self.DEFAULT_PRODUCTS_PER_RESPONSE,
            )
        )

        try:

            page_size = max(
                1,
                min(
                    int(
                        configured_page_size
                    ),
                    self.MAX_PRODUCTS_PER_RESPONSE,
                ),
            )

        except (
            TypeError,
            ValueError,
        ):

            page_size = (
                self.DEFAULT_PRODUCTS_PER_RESPONSE
            )

        # =====================================================
        # 9. SEARCH
        # =====================================================

        search_limit = (
            self.SEARCH_LIMIT
        )

        filters.limit = search_limit
        filters.offset = 0
        filters.in_stock_only = True

        products = (
            await product_service.search_products(
                tenant_id=tenant_id,
                filters=filters,
            )
        )

        response_text: Optional[str] = None

        # =====================================================
        # 10. ZERO-RESULT RELAXATION
        # =====================================================

        if not products:

            filters_dict = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            filters_dict.pop(
                "limit",
                None,
            )

            filters_dict.pop(
                "offset",
                None,
            )

            async def search_fn(
                relaxed_filters_dict: Dict[str, Any],
            ):

                relaxed_filters = (
                    ProductSearchFilters(
                        **relaxed_filters_dict
                    )
                )

                relaxed_filters.limit = (
                    search_limit
                )

                relaxed_filters.offset = 0

                relaxed_filters.in_stock_only = True

                return (
                    await product_service.search_products(
                        tenant_id=tenant_id,
                        filters=relaxed_filters,
                    )
                )

            best_key = (
                await find_best_relaxation(
                    query=understanding.original_text,
                    filters=filters_dict,
                    search_fn=search_fn,
                )
            )

            if best_key:

                relaxed_dict = {
                    key: value
                    for key, value
                    in filters_dict.items()
                    if key != best_key
                }

                relaxed_filters = (
                    ProductSearchFilters(
                        **relaxed_dict
                    )
                )

                relaxed_filters.limit = (
                    search_limit
                )

                relaxed_filters.offset = 0

                relaxed_filters.in_stock_only = True

                products = (
                    await product_service.search_products(
                        tenant_id=tenant_id,
                        filters=relaxed_filters,
                    )
                )

                if products:

                    filters = (
                        relaxed_filters
                    )

                response_text = (
                    build_relaxation_message(
                        query=understanding.original_text,
                        filters=filters_dict,
                        removed_key=best_key,
                        removed_value=(
                            filters_dict[
                                best_key
                            ]
                        ),
                    )
                )

        # =====================================================
        # 11. STILL NO PRODUCTS
        # =====================================================

        if not products:

            return BotResponse(
                response_type="text",
                text=(
                    "I couldn't find any in-stock "
                    "products matching your request. "
                    "Would you like to try another "
                    "color, size, or category?"
                ),
                quick_replies=[
                    {
                        "label": "Search Again",
                        "value": "search_again",
                    }
                ],
                metadata={
                    "search_performed": True,
                    "results_count": 0,
                    "filters_applied": (
                        filters.model_dump(
                            exclude_none=True
                        )
                    ),
                },
            )

        # =====================================================
        # 12. BUILD PAGINATION STATE
        # =====================================================

        result_ids = [
            product.id
            for product in products
        ]

        page = (
            inventory_search_service.build_search_page(
                tenant_id=tenant_id,
                filters=filters,
                result_ids=result_ids,
                page=1,
                page_size=page_size,
            )
        )

        # =====================================================
        # 13. SAVE CONVERSATION SEARCH STATE
        # =====================================================

        if conversation_context:

            filter_dict = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            conversation_context.last_search_filters = (
                filter_dict
            )

            conversation_context.last_search_results = (
                result_ids
            )

            conversation_context.current_product = (
                products[0].id
            )

            conversation_context.active_search_key = (
                page["search_key"]
            )

            conversation_context.active_search_offset = (
                page["offset"]
            )

            conversation_context.active_search_total = (
                page["total"]
            )

            conversation_context.active_search_query = (
                filters.query
            )

            conversation_context.active_search_filters = (
                filter_dict
            )

            conversation_context.active_search_page = 1

            conversation_context.active_search_page_size = (
                page_size
            )

            conversation_context.active_search_results = (
                result_ids
            )

        # =====================================================
        # 14. BUILD RESPONSE PRODUCTS
        # =====================================================

        response_products = [
            product_service.product_to_response(
                product
            )
            for product
            in products[
                :page_size
            ]
        ]

        # =====================================================
        # 15. PAGINATION
        # =====================================================

        has_more = (
            len(products)
            > page_size
        )

        quick_replies: List[
            Dict[str, str]
        ] = []

        if has_more:

            quick_replies.append(
                {
                    "label": "Show more",
                    "value": "show_more",
                }
            )

        # =====================================================
        # 16. RESPONSE TEXT
        # =====================================================

        if response_text is None:

            if len(products) == 1:

                response_text = (
                    "I found this item for you:"
                )

            else:

                response_text = (
                    "I found these products for you:"
                )

        # =====================================================
        # 17. FINAL STRUCTURED RESPONSE
        # =====================================================

        return BotResponse(
            response_type="product_list",
            text=response_text,
            products=response_products,
            quick_replies=quick_replies,
            metadata={
                "search_performed": True,
                "results_count": len(products),
                "filters_applied": (
                    filters.model_dump(
                        exclude_none=True
                    )
                ),
                "page": 1,
                "page_size": page_size,
                "has_more": has_more,
                "total_results": len(products),
            },
        )

    # =========================================================
    # REQUIREMENT WORKFLOW
    # =========================================================

    @staticmethod
    def _find_missing_requirements(
        filters: ProductSearchFilters,
        understanding: MessageUnderstanding,
        required_attributes: List[
            Dict[str, Any]
        ],
    ) -> List[
        Tuple[str, str]
    ]:
        """
        Determine which metadata-defined attributes are missing.

        Returns:

            [
                ("size", "What size would you like?")
            ]

        or:

            [
                ("dress_style", "What style of dress are you looking for?"),
                ("size", "What size would you like?")
            ]
        """

        if not required_attributes:
            return []

        # Build values from both the current filters and entities.
        entity_values: Dict[
            str,
            str
        ] = {}

        for entity in understanding.entities:

            value = (
                entity.normalized_value
                or entity.value
            )

            if not value:
                continue

            normalized_value = (
                str(value).strip()
            )

            if not normalized_value:
                continue

            entity_values[
                entity.entity_type.value
            ] = normalized_value

        missing: List[
            Tuple[str, str]
        ] = []

        for requirement in required_attributes:

            key = str(
                requirement.get(
                    "key",
                    ""
                )
            ).strip()

            if not key:
                continue

            if not ProductSearchHandler._requirement_has_value(
                key=key,
                filters=filters,
                entity_values=entity_values,
            ):

                question = str(
                    requirement.get(
                        "question",
                        "",
                    )
                ).strip()

                if not question:

                    label = str(
                        requirement.get(
                            "label",
                            key.replace(
                                "_",
                                " ",
                            ),
                        )
                    ).strip()

                    question = (
                        f"What {label} would you like?"
                    )

                missing.append(
                    (
                        key,
                        question,
                    )
                )

        return missing

    @staticmethod
    def _requirement_has_value(
        key: str,
        filters: ProductSearchFilters,
        entity_values: Dict[str, str],
    ) -> bool:
        """
        Map metadata requirement keys to the current search filters/entities.
        """

        normalized_key = (
            key.strip().lower()
        )

        # Direct filter mappings.
        direct_filter_map = {
            "color": filters.color,
            "size": filters.size,
            "brand": filters.brand,
            "material": filters.material,
            "fit": filters.fit,
            "gender": filters.gender,
            "type": filters.type,
        }

        if normalized_key in direct_filter_map:

            return bool(
                direct_filter_map[
                    normalized_key
                ]
            )

        # Dress style is represented by ProductSearchFilters.type
        # because the current Product schema exposes `type`.
        if normalized_key in {
            "dress_style",
            "style",
        }:

            if filters.type:
                return True

            if (
                entity_values.get(
                    "style"
                )
            ):
                return True

            return False

        # Check an entity with the exact requirement name.
        if entity_values.get(
            normalized_key
        ):
            return True

        # Common aliases between metadata requirements and entity types.
        aliases = {
            "colour": "color",
            "dressstyle": "style",
            "product_type": "style",
        }

        mapped = aliases.get(
            normalized_key
        )

        if mapped:
            if mapped == "style":
                return bool(
                    filters.type
                    or entity_values.get(
                        "style"
                    )
                )

            return bool(
                entity_values.get(
                    mapped
                )
            )

        return False

    @staticmethod
    def _build_requirement_response(
        category: str,
        missing_requirements: List[
            Tuple[str, str]
        ],
        filters: ProductSearchFilters,
    ) -> BotResponse:
        """
        Build a focused clarification response.

        Only the first missing requirement is asked at a time.
        This creates the intended conversational workflow:

            "I need a black shirt"
                ↓
            "What size would you like?"
                ↓
            "M"
                ↓
            search
        """

        key, question = (
            missing_requirements[0]
        )

        return BotResponse(
            response_type="text",
            text=question,
            quick_replies=[],
            metadata={
                "needs_clarification": True,
                "missing": key,
                "missing_requirements": [
                    item[0]
                    for item
                    in missing_requirements
                ],
                "category": category,
                "filters_collected": (
                    filters.model_dump(
                        exclude_none=True
                    )
                ),
            },
        )

    # =========================================================
    # CONTEXT REFINEMENT
    # =========================================================

    @staticmethod
    def _should_refine_previous_search(
        filters: ProductSearchFilters,
    ) -> bool:
        """
        Determine whether the current message should refine
        the previous product search.

        A message such as:

            "M"

        should inherit the previous:

            shirt + black

        while a new query such as:

            "I need a dress"

        should not inherit unrelated filters.
        """

        return not any(
            (
                filters.query,
                filters.category,
                filters.type,
            )
        )