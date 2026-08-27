from typing import Any, Dict, Optional

from app.conversation.context import ConversationContextManager
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
from app.services.product_service import product_service


def _rank_products(
    products,
    filters: ProductSearchFilters,
):
    """
    Rank already tenant-filtered products before they are displayed.

    Filtering remains the responsibility of MongoDB. Ranking only changes
    result order and never removes a product.
    """
    if not products:
        return []

    query_tokens = set(
        (filters.query or "").lower().split()
    )

    def score(product):
        title_tokens = set(
            product.title.lower().split()
        )

        searchable_text = " ".join(
            part
            for part in (
                product.title,
                product.description,
                product.category,
                product.type,
                product.brand,
                product.material,
                product.fit,
                product.gender,
            )
            if part
        ).lower()

        searchable_tokens = set(
            searchable_text.split()
        )

        query_score = 0.0

        if query_tokens:
            title_match = (
                len(query_tokens & title_tokens)
                / len(query_tokens)
            )

            overall_match = (
                len(query_tokens & searchable_tokens)
                / len(query_tokens)
            )

            query_score = (
                0.7 * title_match
                + 0.3 * overall_match
            )

        filter_checks = 0
        filter_matches = 0

        scalar_filters = (
            (filters.category, product.category),
            (filters.type, product.type),
            (filters.brand, product.brand),
            (filters.material, product.material),
            (filters.fit, product.fit),
            (filters.gender, product.gender),
            (filters.age_group, product.age_group),
        )

        for requested, actual in scalar_filters:
            if requested:
                filter_checks += 1

                if (
                    actual
                    and requested.strip().lower()
                    == actual.strip().lower()
                ):
                    filter_matches += 1

        if filters.color:
            filter_checks += 1

            if any(
                filters.color.strip().lower()
                == value.strip().lower()
                for value in product.color
            ):
                filter_matches += 1

        if filters.size:
            filter_checks += 1

            if any(
                filters.size.strip().lower()
                == value.strip().lower()
                for value in product.size
            ):
                filter_matches += 1

        attribute_score = (
            filter_matches / filter_checks
            if filter_checks
            else 0.0
        )

        featured_score = (
            1.0
            if product.is_featured
            else 0.0
        )

        stock_score = min(
            max(product.stock, 0) / 10.0,
            1.0,
        )

        recency_score = (
            product.created_at.timestamp()
            if product.created_at
            else 0.0
        )

        final_score = (
            0.60 * query_score
            + 0.25 * attribute_score
            + 0.10 * featured_score
            + 0.05 * stock_score
        )

        return final_score, recency_score

    return sorted(
        products,
        key=score,
        reverse=True,
    )


class ProductSearchHandler(BaseHandler):
    MAX_PRODUCTS_PER_RESPONSE = 3
    DEFAULT_PRODUCTS_PER_RESPONSE = 3
    SEARCH_LIMIT = 100

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        filters = product_service.entities_to_filters(
            understanding.entities
        )

        filters, size_clarification = (
            await catalog_metadata_service.normalize_filters(
                tenant_id,
                filters,
                understanding.original_text,
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

        # A query such as "I need a black shirt" identifies the product
        # family and color, but not the customer's size. Preserve those
        # filters in conversation state and ask for size before showing
        # catalog results.
        if filters.query and not filters.size:
            if conversation_context:
                conversation_context.awaiting_entity = (
                    EntityType.SIZE
                )

                conversation_context.awaiting_confirmation = True

                conversation_context.confirmation_context = {
                    "intent": IntentType.PRODUCT_SEARCH.value,
                    "missing_entities": [
                        EntityType.SIZE.value
                    ],
                }

                conversation_context.last_search_filters = (
                    filters.model_dump(
                        exclude_none=True
                    )
                )

            return BotResponse(
                response_type="text",
                text=(
                    "What size would you like? "
                    "For example: S, M, L, or XL."
                ),
                metadata={
                    "needs_clarification": True,
                    "missing": "size",
                    "filters": filters.model_dump(
                        exclude_none=True
                    ),
                },
            )

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
                **merged
            )

        feature_flags = (
            tenant_settings.get(
                "feature_flags",
                {},
            )
            or {}
        )

        configured_page_size = feature_flags.get(
            "max_products_per_response",
            self.DEFAULT_PRODUCTS_PER_RESPONSE,
        )

        try:
            page_size = max(
                1,
                min(
                    int(configured_page_size),
                    self.MAX_PRODUCTS_PER_RESPONSE,
                ),
            )
        except (TypeError, ValueError):
            page_size = self.DEFAULT_PRODUCTS_PER_RESPONSE

        filters.limit = self.SEARCH_LIMIT
        filters.offset = 0

        products = await product_service.search_products(
            tenant_id,
            filters,
        )

        products = _rank_products(
            products,
            filters,
        )

        response_text = None

        if not products:
            filters_dict = filters.model_dump(
                exclude_none=True
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
                relaxed_filters = ProductSearchFilters(
                    **relaxed_filters_dict
                )

                relaxed_filters.limit = (
                    self.SEARCH_LIMIT
                )

                relaxed_filters.offset = 0

                results = (
                    await product_service.search_products(
                        tenant_id,
                        relaxed_filters,
                    )
                )

                return _rank_products(
                    results,
                    relaxed_filters,
                )

            best_key = await find_best_relaxation(
                query=understanding.original_text,
                filters=filters_dict,
                search_fn=search_fn,
            )

            if best_key:
                relaxed_dict = {
                    key: value
                    for key, value in filters_dict.items()
                    if key != best_key
                }

                relaxed_filters = ProductSearchFilters(
                    **relaxed_dict
                )

                relaxed_filters.limit = (
                    self.SEARCH_LIMIT
                )

                relaxed_filters.offset = 0

                products = await product_service.search_products(
                    tenant_id,
                    relaxed_filters,
                )

                products = _rank_products(
                    products,
                    relaxed_filters,
                )

                if products:
                    filters = relaxed_filters

                response_text = build_relaxation_message(
                    query=understanding.original_text,
                    filters=filters_dict,
                    removed_key=best_key,
                    removed_value=filters_dict[best_key],
                )

        if not products:
            return BotResponse(
                response_type="text",
                text=(
                    "I couldn't find any products "
                    "matching your search. "
                    "Could you try different "
                    "keywords or filters?"
                ),
                quick_replies=[
                    {
                        "label": "Search Again",
                        "value": "__COMMAND__:search_again",
                    }
                ],
                metadata={
                    "search_performed": True,
                    "results_count": 0,
                },
            )

        page = inventory_search_service.build_search_page(
            tenant_id=tenant_id,
            filters=filters,
            result_ids=[
                product.id
                for product in products
            ],
            page=1,
            page_size=page_size,
        )

        if conversation_context:
            conversation_context.last_search_filters = (
                filters.model_dump(
                    exclude_none=True
                )
            )

            conversation_context.last_search_results = [
                product.id
                for product in products
            ]

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
                filters.model_dump(
                    exclude_none=True
                )
            )

            conversation_context.active_search_page = 1

            conversation_context.active_search_page_size = (
                page_size
            )

            conversation_context.active_search_results = [
                product.id
                for product in products
            ]

            conversation_context.awaiting_entity = None
            conversation_context.awaiting_confirmation = False
            conversation_context.confirmation_context = {}

        response_products = [
            product_service.product_to_response(
                product
            )
            for product in products[:page_size]
        ]

        has_more = len(products) > page_size

        if response_text is None:
            response_text = (
                "I found this item for you:"
                if len(products) == 1
                else "I found these products for you:"
            )

        quick_replies = []

        if has_more:
            quick_replies.append(
                {
                    "label": "Show more",
                    "value": "__COMMAND__:show_more",
                }
            )

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

    @staticmethod
    def _should_refine_previous_search(
        filters: ProductSearchFilters,
    ) -> bool:
        return not any(
            (
                filters.query,
                filters.category,
                filters.type,
            )
        )


product_search_handler = ProductSearchHandler()