from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from app.models.schemas import IntentType, EntityType


@dataclass
class IntentConfig:
    """
    Configuration for an intent handler.
    """
    handler_class: str  # e.g., "ProductSearchHandler"
    requires_entities: bool = True
    required_entities: List[EntityType] = None
    optional_entities: List[EntityType] = None
    min_confidence: float = 0.5
    fallback_intent: Optional[IntentType] = None
    response_type: str = "structured"  # structured, template, ai
    requires_tenant_config: bool = False
    allowed_tenant_features: List[str] = None


# Intent routing configuration
INTENT_CONFIGS: Dict[IntentType, IntentConfig] = {
    IntentType.GREETING: IntentConfig(
        handler_class="GreetingHandler",
        requires_entities=False,
        min_confidence=0.2,
        response_type="template",
    ),

    IntentType.PRODUCT_SEARCH: IntentConfig(
        handler_class="ProductSearchHandler",
        requires_entities=True,
        # Move COLOR and SIZE here to force the follow-up question
        required_entities=[EntityType.PRODUCT, EntityType.COLOR, EntityType.SIZE],
        optional_entities=[
            EntityType.FIT,
            EntityType.PRICE,
            EntityType.BRAND,
            EntityType.CATEGORY
        ],
        min_confidence=0.25,
        response_type="structured",
        allowed_tenant_features=["enable_product_recommendations"],
    ),

    IntentType.PRODUCT_INQUIRY: IntentConfig(
        handler_class="ProductInquiryHandler",
        requires_entities=True,
        required_entities=[EntityType.PRODUCT],
        optional_entities=[EntityType.COLOR, EntityType.SIZE, EntityType.FIT],
        min_confidence=0.25,
        response_type="structured",
    ),

    IntentType.AVAILABILITY: IntentConfig(
        handler_class="AvailabilityHandler",
        requires_entities=True,
        required_entities=[EntityType.PRODUCT],
        optional_entities=[EntityType.SIZE, EntityType.COLOR, EntityType.FIT],
        min_confidence=0.25,
        response_type="structured",
    ),

    IntentType.ORDER_STATUS: IntentConfig(
        handler_class="OrderStatusHandler",
        requires_entities=True,
        required_entities=[EntityType.ORDER_ID],
        min_confidence=0.3,
        response_type="structured",
        allowed_tenant_features=["enable_order_tracking"],
    ),

    IntentType.CANCEL_ORDER: IntentConfig(
        handler_class="CancelOrderHandler",
        requires_entities=True,
        required_entities=[EntityType.ORDER_ID],
        min_confidence=0.4,
        response_type="structured",
        allowed_tenant_features=["enable_cancellation"],
        fallback_intent=IntentType.ORDER_STATUS,
    ),

    IntentType.RETURN_REQUEST: IntentConfig(
        handler_class="ReturnRequestHandler",
        requires_entities=True,
        required_entities=[EntityType.ORDER_ID],
        optional_entities=[EntityType.PRODUCT],
        min_confidence=0.3,
        response_type="structured",
        allowed_tenant_features=["enable_returns"],
    ),

    IntentType.COMPLAINT: IntentConfig(
        handler_class="ComplaintHandler",
        requires_entities=False,
        optional_entities=[EntityType.ORDER_ID, EntityType.PRODUCT],
        min_confidence=0.25,
        response_type="template",
        allowed_tenant_features=["enable_human_handoff"],
        fallback_intent=IntentType.COMPLAINT,
    ),

    IntentType.THANKS: IntentConfig(
        handler_class="ThanksHandler",
        requires_entities=False,
        min_confidence=0.2,
        response_type="template",
    ),

    IntentType.UNKNOWN: IntentConfig(
        handler_class="FallbackHandler",
        requires_entities=False,
        min_confidence=0.0,
        response_type="template",
    ),
}


# A lightweight pagination intent is treated as a follow-up search action
# that uses the active cached search state in the session context.
PAGINATION_INTENT = "pagination"


def get_intent_config(intent: IntentType) -> IntentConfig:
    """
    Get configuration for an intent.
    """
    return INTENT_CONFIGS.get(intent, INTENT_CONFIGS[IntentType.UNKNOWN])


def get_handler_class(intent: IntentType) -> str:
    """
    Get handler class name for an intent.
    """
    return get_intent_config(intent).handler_class


def get_required_entities(intent: IntentType) -> List[EntityType]:
    """
    Get required entities for an intent.
    """
    config = get_intent_config(intent)
    return config.required_entities or []


def get_optional_entities(intent: IntentType) -> List[EntityType]:
    """
    Get optional entities for an intent.
    """
    config = get_intent_config(intent)
    return config.optional_entities or []


def check_tenant_feature(tenant_settings: Dict[str, Any], feature: str) -> bool:
    """
    Check if tenant has a feature enabled.
    """

    feature_flags = tenant_settings.get("feature_flags", {})
    return feature_flags.get(feature, False)