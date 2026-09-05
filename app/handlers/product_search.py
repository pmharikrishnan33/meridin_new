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
    IntentType,
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
        previous-context merge
            ↓
        metadata normalization
            ↓
        category resolution
            ↓
        required-attribute check
            ↓
        clarification
            ↓
        product search
            ↓
        safe zero-result relaxation
            ↓
        ranked results
            ↓
        pagination state
            ↓
        response

    The handler does not perform generic intent routing. It owns the
    metadata-driven product-search workflow.
    """

    MAX_PRODUCTS_PER_RESPONSE = 3
    DEFAULT_PRODUCTS_PER_RESPONSE = 3
    SEARCH_LIMIT = 100

    # These fields represent filters that should normally not be removed
    # automatically when trying to relax a zero-result search.
    HARD_FILTER_KEYS = {
        "department_id",
        "category_id",
        "category",
    }

    # ============================================================
    # PUBLIC HANDLER
    # ============================================================

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[
            ConversationContext
        ],
    ) -> BotResponse:

        # --------------------------------------------------------
        # 1. BUILD FILTERS FROM CURRENT MESSAGE
        # --------------------------------------------------------

        filters = (
            product_service.entities_to_filters(
                understanding.entities
            )
        )

        # --------------------------------------------------------
        # 2. MERGE FOLLOW-UP SEARCH FILTERS
        # --------------------------------------------------------

        if (
            conversation_context
            and conversation_context.last_search_filters
            and self._should_refine_previous_search(
                filters
            )
        ):
            filters_dict = filters.model_dump(
                exclude_none=True
            )

            merged = (
                ConversationContextManager.merge_filters(
                    conversation_context.last_search_filters,
                    filters_dict,
                )
            )

            filters = ProductSearchFilters(
                **self._sanitize_filter_dict(
                    merged
                )
            )

        # --------------------------------------------------------
        # 3. RECOVER CATEGORY FROM CONTEXT BEFORE NORMALIZATION
        # --------------------------------------------------------
        #
        # This is critical for follow-up messages such as:
        #
        #   User: I need a black shirt
        #   Bot:  What size would you like?
        #   User: 2XL
        #
        # The second message may contain only SIZE. The category from the
        # previous turn must therefore be restored before metadata resolves
        # the size group.
        # --------------------------------------------------------

        if (
            not filters.category
            and conversation_context
            and conversation_context.current_category
        ):
            filters.category = (
                conversation_context.current_category
            )

        # If the generic conversation state already contains the previous
        # search filters, make sure their category is available before the
        # metadata normalization step as well.
        if (
            not filters.category
            and conversation_context
            and conversation_context.last_search_filters
        ):
            previous_category = (
                conversation_context.last_search_filters.get(
                    "category"
                )
            )
            if previous_category:
                filters.category = previous_category

        # --------------------------------------------------------
        # 4. NORMALIZE AGAINST TENANT CATALOG
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # 5. CATEGORY IS REQUIRED TO SELECT REQUIREMENTS
        # --------------------------------------------------------

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
                    "intent": (
                        IntentType.PRODUCT_SEARCH.value
                    ),
                },
            )

        # --------------------------------------------------------
        # 6. GET METADATA REQUIREMENTS
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # 7. SEARCH STATE BEFORE SEARCH
        # --------------------------------------------------------

        if conversation_context:
            conversation_context.current_category = (
                category
            )

            conversation_context.last_search_filters = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            # A completed search requirement means the previous
            # clarification state is no longer valid.
            conversation_context.awaiting_entity = None
            conversation_context.awaiting_confirmation = False
            conversation_context.confirmation_context = {}

        # --------------------------------------------------------
        # 8. PAGE SIZE
        # --------------------------------------------------------

        page_size = self._get_page_size(
            tenant_settings
        )

        # --------------------------------------------------------
        # 9. SEARCH
        # --------------------------------------------------------

        search_limit = self.SEARCH_LIMIT

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

        # --------------------------------------------------------
        # 10. SAFE ZERO-RESULT RELAXATION
        # --------------------------------------------------------

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
                safe_relaxed = (
                    self._sanitize_filter_dict(
                        relaxed_filters_dict
                    )
                )

                relaxed_filters = (
                    ProductSearchFilters(
                        **safe_relaxed
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

            # Never relax category/department identity automatically.
            relaxable_filters = {
                key: value
                for key, value in filters_dict.items()
                if (
                    key
                    not in self.HARD_FILTER_KEYS
                )
            }

            best_key = None

            if relaxable_filters:
                best_key = (
                    await find_best_relaxation(
                        query=understanding.original_text,
                        filters=relaxable_filters,
                        search_fn=search_fn,
                    )
                )

            if (
                best_key
                and best_key
                not in self.HARD_FILTER_KEYS
            ):
                relaxed_dict = {
                    key: value
                    for key, value
                    in filters_dict.items()
                    if key != best_key
                }

                relaxed_dict = (
                    self._sanitize_filter_dict(
                        relaxed_dict
                    )
                )

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
                    filters = relaxed_filters

                    response_text = (
                        build_relaxation_message(
                            query=understanding.original_text,
                            filters=filters_dict,
                            removed_key=best_key,
                            removed_value=(
                                filters_dict.get(
                                    best_key
                                )
                            ),
                        )
                    )

        # --------------------------------------------------------
        # 11. STILL NO PRODUCTS
        # --------------------------------------------------------

        if not products:
            if conversation_context:
                conversation_context.last_search_results = []
                conversation_context.active_search_key = None
                conversation_context.active_search_offset = 0
                conversation_context.active_search_total = 0
                conversation_context.active_search_results = []
                conversation_context.active_search_page = 1

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

        # --------------------------------------------------------
        # 12. BUILD PAGINATION STATE
        # --------------------------------------------------------

        result_ids = [
            str(product.id)
            for product in products
            if product.id is not None
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

        # --------------------------------------------------------
        # 13. SAVE SEARCH CONTEXT
        # --------------------------------------------------------

        filter_dict = (
            filters.model_dump(
                exclude_none=True
            )
        )

        if conversation_context:
            conversation_context.last_search_filters = (
                filter_dict
            )

            conversation_context.last_search_results = (
                result_ids
            )

            conversation_context.current_product = (
                result_ids[0]
                if result_ids
                else None
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

            conversation_context.active_search_page = (
                page["page"]
            )

            conversation_context.active_search_page_size = (
                page_size
            )

            conversation_context.active_search_results = (
                result_ids
            )

            conversation_context.awaiting_entity = None
            conversation_context.awaiting_confirmation = False
            conversation_context.confirmation_context = {}

        # --------------------------------------------------------
        # 14. RESPONSE PRODUCTS
        # --------------------------------------------------------

        display_maps = await catalog_metadata_service.get_display_maps(
            tenant_id
        )

        response_products = [
            product_service.product_to_response(
                product,
                display_maps=display_maps,
            )
            for product in products[
                :page_size
            ]
        ]

        # --------------------------------------------------------
        # 15. PAGINATION
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # 16. RESPONSE TEXT
        # --------------------------------------------------------

        if response_text is None:
            if len(products) == 1:
                response_text = (
                    "I found this item for you:"
                )
            else:
                response_text = (
                    "I found these products for you:"
                )

        # --------------------------------------------------------
        # 17. FINAL RESPONSE
        # --------------------------------------------------------

        return BotResponse(
            response_type="product_list",
            text=response_text,
            products=response_products,
            quick_replies=quick_replies,
            metadata={
                "search_performed": True,
                "results_count": len(products),
                "filters_applied": filter_dict,
                "page": 1,
                "page_size": page_size,
                "has_more": has_more,
                "total_results": len(products),
                "product_ids": result_ids[
                    :page_size
                ],
            },
        )

    # ============================================================
    # PAGE SIZE
    # ============================================================

    def _get_page_size(
        self,
        tenant_settings: Dict[str, Any],
    ) -> int:
        """
        Resolve tenant-configured response size while enforcing the
        WhatsApp/application maximum.
        """

        feature_flags = (
            tenant_settings.get(
                "feature_flags",
                {},
            )
            or {}
        )

        configured = feature_flags.get(
            "max_products_per_response",
            self.DEFAULT_PRODUCTS_PER_RESPONSE,
        )

        try:
            configured = int(
                configured
            )
        except (
            TypeError,
            ValueError,
        ):
            configured = (
                self.DEFAULT_PRODUCTS_PER_RESPONSE
            )

        return max(
            1,
            min(
                configured,
                self.MAX_PRODUCTS_PER_RESPONSE,
            ),
        )

    # ============================================================
    # REQUIREMENT WORKFLOW
    # ============================================================

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
        """

        if not required_attributes:
            return []

        entity_values: Dict[
            str,
            str,
        ] = {}

        for entity in (
            understanding.entities or []
        ):
            value = (
                entity.normalized_value
                or entity.value
            )

            if value is None:
                continue

            value = str(value).strip()

            if not value:
                continue

            entity_key = (
                entity.entity_type.value
            )

            existing = entity_values.get(
                entity_key
            )

            if (
                existing is None
                or entity.confidence >= 0
            ):
                entity_values[
                    entity_key
                ] = value

        missing: List[
            Tuple[str, str]
        ] = []

        for requirement in (
            required_attributes
        ):
            key = str(
                requirement.get(
                    "key",
                    "",
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
        Resolve metadata requirement names against current filters/entities.
        """

        normalized_key = (
            key.strip().lower()
        )

        direct_filter_map = {
            "color": filters.color,
            "colour": filters.color,
            "size": filters.size,
            "brand": filters.brand,
            "material": filters.material,
            "fit": filters.fit,
            "gender": filters.gender,
            "type": filters.type,
            "style": filters.style,
            "pattern": filters.pattern,
            "occasion": filters.occasion,
            "season": filters.season,
            "sleeve": filters.sleeve,
            "neck": filters.neck,
        }

        if normalized_key in direct_filter_map:
            return bool(
                direct_filter_map[
                    normalized_key
                ]
            )

        dynamic_value = (
            getattr(filters, "attributes", {}) or {}
        ).get(normalized_key)
        if dynamic_value is not None:
            return bool(str(dynamic_value).strip())

        if normalized_key in {
            "dress_style",
            "dressstyle",
        }:
            attributes = getattr(filters, "attributes", {}) or {}
            return bool(
                attributes.get("dress_style")
                or attributes.get("dress_style_id")
                or filters.style
                or entity_values.get("style")
            )

        if normalized_key in {
            "product_type",
        }:
            return bool(
                filters.type
                or filters.style
                or entity_values.get(
                    "style"
                )
            )

        if normalized_key in entity_values:
            return bool(
                entity_values[
                    normalized_key
                ]
            )

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
                    filters.style
                    or filters.type
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
        Ask for exactly one missing requirement.

        The router will persist the pending requirement after receiving this
        response. This prevents the handler from depending on persistence
        infrastructure.
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
                    for item in missing_requirements
                ],
                "category": category,
                "filters_collected": (
                    filters.model_dump(
                        exclude_none=True
                    )
                ),
                "requirement": {
                    "key": key,
                    "question": question,
                },
            },
        )

    # ============================================================
    # CONTEXT REFINEMENT
    # ============================================================

    @staticmethod
    def _should_refine_previous_search(
        filters: ProductSearchFilters,
    ) -> bool:
        """
        A bare refinement such as "M" inherits the previous search.

        A new product/category/type query starts a fresh search.
        """

        return not any(
            (
                filters.query,
                filters.category,
                filters.type,
            )
        )

    # ============================================================
    # FILTER SAFETY
    # ============================================================

    @staticmethod
    def _sanitize_filter_dict(
        filters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Keep only fields supported by ProductSearchFilters.
        """

        allowed = set(
            ProductSearchFilters.model_fields.keys()
        )

        return {
            key: value
            for key, value in (
                filters or {}
            ).items()
            if key in allowed
        }