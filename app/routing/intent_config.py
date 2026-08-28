from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.models.schemas import EntityType, IntentType


@dataclass
class IntentConfig:
    """
    Configuration for an intent handler.
    """

    handler_class: str

    requires_entities: bool = True

    required_entities: Optional[
        List[EntityType]
    ] = None

    optional_entities: Optional[
        List[EntityType]
    ] = None

    min_confidence: float = 0.18

    fallback_intent: Optional[
        IntentType
    ] = None

    response_type: str = "structured"

    requires_tenant_config: bool = False

    allowed_tenant_features: Optional[
        List[str]
    ] = None


INTENT_CONFIGS: Dict[
    IntentType,
    IntentConfig,
] = {

    # ---------------------------------------------------------
    # GREETING
    # ---------------------------------------------------------

    IntentType.GREETING: IntentConfig(
        handler_class="GreetingHandler",
        requires_entities=False,
        min_confidence=0.15,
        response_type="template",
    ),

    # ---------------------------------------------------------
    # PRODUCT SEARCH
    # ---------------------------------------------------------

    IntentType.PRODUCT_SEARCH: IntentConfig(
        handler_class="ProductSearchHandler",
        requires_entities=False,

        # Product search requirements are handled by
        # ConversationRequirementEngine.
        #
        # Do not put PRODUCT and SIZE here because the requirement
        # engine already owns conversational collection.
        required_entities=[],

        optional_entities=[
            EntityType.PRODUCT,
            EntityType.COLOR,
            EntityType.SIZE,
            EntityType.FIT,
            EntityType.PRICE,
            EntityType.BRAND,
            EntityType.CATEGORY,
            EntityType.MATERIAL,
            EntityType.GENDER,
            EntityType.STYLE,
            EntityType.PATTERN,
            EntityType.OCCASION,
            EntityType.SEASON,
            EntityType.SLEEVE,
            EntityType.NECK,
        ],

        # Your diagnostic produced:
        #
        # I need a black shirt
        # product_search = 0.2255
        #
        # Therefore 0.25 would reject a correct prediction.
        min_confidence=0.18,

        response_type="structured",

        allowed_tenant_features=[
            "enable_product_recommendations"
        ],
    ),

    # ---------------------------------------------------------
    # PRODUCT INQUIRY
    # ---------------------------------------------------------

    IntentType.PRODUCT_INQUIRY: IntentConfig(
        handler_class="ProductInquiryHandler",
        requires_entities=True,

        required_entities=[
            EntityType.PRODUCT
        ],

        optional_entities=[
            EntityType.COLOR,
            EntityType.SIZE,
            EntityType.FIT,
        ],

        min_confidence=0.18,
        response_type="structured",
    ),

    # ---------------------------------------------------------
    # AVAILABILITY
    # ---------------------------------------------------------

    IntentType.AVAILABILITY: IntentConfig(
        handler_class="AvailabilityHandler",
        requires_entities=False,

        optional_entities=[
            EntityType.PRODUCT,
            EntityType.CATEGORY,
            EntityType.SIZE,
            EntityType.COLOR,
            EntityType.FIT,
        ],

        min_confidence=0.18,
        response_type="structured",
    ),

    # ---------------------------------------------------------
    # PAGINATION
    # ---------------------------------------------------------

    IntentType.PAGINATION: IntentConfig(
        handler_class="PaginationHandler",
        requires_entities=False,
        min_confidence=0.15,
        response_type="structured",
    ),

    # ---------------------------------------------------------
    # ORDER STATUS
    # ---------------------------------------------------------

    IntentType.ORDER_STATUS: IntentConfig(
        handler_class="OrderStatusHandler",
        requires_entities=True,

        required_entities=[
            EntityType.ORDER_ID
        ],

        min_confidence=0.18,
        response_type="structured",

        allowed_tenant_features=[
            "enable_order_tracking"
        ],
    ),

    # ---------------------------------------------------------
    # CANCEL ORDER
    # ---------------------------------------------------------

    IntentType.CANCEL_ORDER: IntentConfig(
        handler_class="CancelOrderHandler",
        requires_entities=True,

        required_entities=[
            EntityType.ORDER_ID
        ],

        min_confidence=0.18,
        response_type="structured",

        allowed_tenant_features=[
            "enable_cancellation"
        ],

        fallback_intent=IntentType.ORDER_STATUS,
    ),

    # ---------------------------------------------------------
    # RETURN REQUEST
    # ---------------------------------------------------------

    IntentType.RETURN_REQUEST: IntentConfig(
        handler_class="ReturnRequestHandler",
        requires_entities=True,

        required_entities=[
            EntityType.ORDER_ID
        ],

        optional_entities=[
            EntityType.PRODUCT
        ],

        min_confidence=0.18,
        response_type="structured",

        allowed_tenant_features=[
            "enable_returns"
        ],
    ),

    # ---------------------------------------------------------
    # COMPLAINT
    # ---------------------------------------------------------

    IntentType.COMPLAINT: IntentConfig(
        handler_class="ComplaintHandler",
        requires_entities=False,

        optional_entities=[
            EntityType.ORDER_ID,
            EntityType.PRODUCT,
        ],

        min_confidence=0.18,
        response_type="template",

        allowed_tenant_features=[
            "enable_human_handoff"
        ],

        fallback_intent=IntentType.COMPLAINT,
    ),

    # ---------------------------------------------------------
    # THANKS
    # ---------------------------------------------------------

    IntentType.THANKS: IntentConfig(
        handler_class="ThanksHandler",
        requires_entities=False,
        min_confidence=0.15,
        response_type="template",
    ),

    # ---------------------------------------------------------
    # UNKNOWN
    # ---------------------------------------------------------

    IntentType.UNKNOWN: IntentConfig(
        handler_class="FallbackHandler",
        requires_entities=False,
        min_confidence=0.0,
        response_type="template",
    ),
}


def get_intent_config(
    intent: IntentType,
) -> IntentConfig:
    """
    Return configuration for an intent.
    """

    return INTENT_CONFIGS.get(
        intent,
        INTENT_CONFIGS[
            IntentType.UNKNOWN
        ],
    )


def get_handler_class(
    intent: IntentType,
) -> str:
    """
    Return handler class for an intent.
    """

    return get_intent_config(
        intent
    ).handler_class


def get_required_entities(
    intent: IntentType,
) -> List[EntityType]:
    """
    Return required entities for an intent.
    """

    config = get_intent_config(
        intent
    )

    return config.required_entities or []


def get_optional_entities(
    intent: IntentType,
) -> List[EntityType]:
    """
    Return optional entities for an intent.
    """

    config = get_intent_config(
        intent
    )

    return config.optional_entities or []


def check_tenant_feature(
    tenant_settings: Dict[str, Any],
    feature: str,
) -> bool:
    """
    Check whether a tenant feature is enabled.
    """

    feature_flags = (
        tenant_settings.get(
            "feature_flags",
            {},
        )
        or {}
    )

    return bool(
        feature_flags.get(
            feature,
            False,
        )
    )