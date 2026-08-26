from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# ENUMS
# ============================================================


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    INTERACTIVE = "interactive"
    BUTTON = "button"
    LOCATION = "location"
    CONTACT = "contact"
    UNKNOWN = "unknown"


class IntentType(str, Enum):
    GREETING = "greeting"
    PRODUCT_SEARCH = "product_search"
    PRODUCT_DETAILS = "product_details"
    AVAILABILITY = "availability"
    PRICE_INQUIRY = "price_inquiry"
    ORDER_STATUS = "order_status"
    RETURN = "return"
    CANCELLATION = "cancellation"
    HUMAN_HANDOFF = "human_handoff"
    PAGINATION = "pagination"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    PRODUCT = "product"
    CATEGORY = "category"
    BRAND = "brand"
    COLOR = "color"
    MATERIAL = "material"
    SIZE = "size"
    PRICE = "price"
    PRICE_MIN = "price_min"
    PRICE_MAX = "price_max"
    FIT = "fit"
    GENDER = "gender"
    AGE_GROUP = "age_group"
    TYPE = "type"
    TAG = "tag"
    UNKNOWN = "unknown"


# ============================================================
# TENANT
# ============================================================


class TenantSettings(BaseModel):
    """
    Nested tenant settings stored under the tenant's settings object.
    """

    webhook_secret: Optional[str] = None


class TenantFeatureFlags(BaseModel):
    """
    Tenant-specific feature configuration.
    """

    enable_ai_responses: bool = True
    enable_product_recommendations: bool = True

    enable_order_tracking: bool = False
    enable_returns: bool = False
    enable_cancellation: bool = False

    enable_human_handoff: bool = True
    enable_analytics: bool = True

    use_synonyms: bool = True

    max_products_per_response: int = 5

    auto_reply_outside_hours: bool = False

    @field_validator("max_products_per_response")
    @classmethod
    def validate_max_products_per_response(
        cls,
        value: int,
    ) -> int:
        return max(1, min(value, 20))


class Tenant(BaseModel):
    """
    Tenant/client model stored in the MongoDB clients collection.
    """

    id: str = Field(alias="_id")

    tenant_id: str

    business_name: str

    welcome_message: Optional[str] = None
    fallback_message: Optional[str] = None

    phone_number_id: str
    access_token: str
    webhook_verify_token: str

    is_active: bool = True

    feature_flags: TenantFeatureFlags = Field(
        default_factory=TenantFeatureFlags
    )

    settings: TenantSettings = Field(
        default_factory=TenantSettings
    )

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        populate_by_name=True
    )


# ============================================================
# PRODUCT
# ============================================================


class ProductVariant(BaseModel):
    """
    A purchasable product variant.

    A variant may represent a size/color combination and its
    corresponding stock.
    """

    id: Optional[str] = None

    sku: Optional[str] = None

    size: Optional[str] = None

    color: Optional[str] = None

    stock: int = 0

    price: Optional[float] = None

    model_config = ConfigDict(
        extra="allow"
    )

    @field_validator("stock")
    @classmethod
    def validate_stock(
        cls,
        value: int,
    ) -> int:
        return max(0, value)


class Product(BaseModel):
    """
    Clothing product stored inside a tenant-specific inventory
    collection.
    """

    id: str = Field(alias="_id")

    tenant_id: str

    title: str

    description: Optional[str] = None

    category: Optional[str] = None

    type: Optional[str] = None

    brand: Optional[str] = None

    material: Optional[str] = None

    fit: Optional[str] = None

    gender: Optional[str] = None

    age_group: Optional[str] = None

    color: List[str] = Field(
        default_factory=list
    )

    size: List[str] = Field(
        default_factory=list
    )

    tags: List[str] = Field(
        default_factory=list
    )

    price: float = 0.0

    stock: int = 0

    variants: List[ProductVariant] = Field(
        default_factory=list
    )

    images: List[str] = Field(
        default_factory=list
    )

    image_url: Optional[str] = None

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
    )

    @field_validator("stock")
    @classmethod
    def validate_stock(
        cls,
        value: int,
    ) -> int:
        return max(0, value)

    @field_validator("price")
    @classmethod
    def validate_price(
        cls,
        value: float,
    ) -> float:
        return max(0.0, value)


class ProductSearchFilters(BaseModel):
    """
    Filters used by the product repository/service.
    """

    query: Optional[str] = None

    category: Optional[str] = None

    type: Optional[str] = None

    brand: Optional[str] = None

    material: Optional[str] = None

    fit: Optional[str] = None

    gender: Optional[str] = None

    age_group: Optional[str] = None

    color: Optional[str] = None

    size: Optional[str] = None

    tags: List[str] = Field(
        default_factory=list
    )

    min_price: Optional[float] = None

    max_price: Optional[float] = None

    in_stock_only: bool = False

    sort_by: Optional[str] = None

    offset: int = 0

    limit: int = 10

    model_config = ConfigDict(
        extra="allow"
    )

    @field_validator("offset")
    @classmethod
    def validate_offset(
        cls,
        value: int,
    ) -> int:
        return max(0, value)

    @field_validator("limit")
    @classmethod
    def validate_limit(
        cls,
        value: int,
    ) -> int:
        return max(1, min(value, 100))

    @field_validator("min_price", "max_price")
    @classmethod
    def validate_price(
        cls,
        value: Optional[float],
    ) -> Optional[float]:
        if value is None:
            return None

        return max(0.0, value)


# ============================================================
# ML ENTITIES
# ============================================================


class ExtractedEntity(BaseModel):
    entity_type: EntityType

    value: str

    confidence: float = 1.0

    normalized_value: Optional[str] = None

    model_config = ConfigDict(
        extra="allow"
    )


class MessageUnderstanding(BaseModel):
    original_text: str

    normalized_text: str

    intent: IntentType

    intent_confidence: float

    entities: List[ExtractedEntity] = Field(
        default_factory=list
    )

    model_config = ConfigDict(
        extra="allow"
    )


# ============================================================
# BOT RESPONSE
# ============================================================


class ProductResponse(BaseModel):
    """
    Product representation returned to the WhatsApp response layer.
    """

    product_id: str

    title: str

    description: Optional[str] = None

    price: Optional[float] = None

    images: List[str] = Field(
        default_factory=list
    )

    image_url: Optional[str] = None

    sizes: List[str] = Field(
        default_factory=list
    )

    colors: List[str] = Field(
        default_factory=list
    )

    type: Optional[str] = None

    category: Optional[str] = None

    brand: Optional[str] = None

    material: Optional[str] = None

    fit: Optional[str] = None

    gender: Optional[str] = None

    stock: int = 0

    variants: List[ProductVariant] = Field(
        default_factory=list
    )

    score: Optional[float] = None

    model_config = ConfigDict(
        extra="allow"
    )


class BotResponse(BaseModel):
    """
    Response produced by an intent handler.

    The WhatsApp sender is responsible for converting this object
    into one or more provider-specific messages.
    """

    response_type: str = "text"

    text: Optional[str] = None

    products: List[ProductResponse] = Field(
        default_factory=list
    )

    quick_replies: List[Dict[str, Any]] = Field(
        default_factory=list
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    model_config = ConfigDict(
        extra="allow"
    )


# ============================================================
# CONVERSATION CONTEXT
# ============================================================


class ConversationContext(BaseModel):
    """
    Persistent conversation state used by the product-search workflow.
    """

    current_product: Optional[str] = None

    current_category: Optional[str] = None

    current_brand: Optional[str] = None

    current_color: Optional[str] = None

    current_size: Optional[str] = None

    current_query: Optional[str] = None

    last_search_filters: Dict[str, Any] = Field(
        default_factory=dict
    )

    last_search_results: List[str] = Field(
        default_factory=list
    )

    active_search_key: Optional[str] = None

    active_search_offset: int = 0

    active_search_total: int = 0

    active_search_query: Optional[str] = None

    active_search_filters: Dict[str, Any] = Field(
        default_factory=dict
    )

    active_search_results: List[str] = Field(
        default_factory=list
    )

    active_search_page: int = 1

    awaiting_entity: Optional[str] = None

    awaiting_confirmation: bool = False

    model_config = ConfigDict(
        extra="allow"
    )


# ============================================================
# MESSAGE
# ============================================================


class Message(BaseModel):
    """
    Persisted inbound or outbound message.
    """

    id: str

    tenant_id: str

    conversation_id: str

    customer_id: str

    whatsapp_message_id: Optional[str] = None

    direction: MessageDirection

    message_type: MessageType = MessageType.TEXT

    text: str = ""

    intent: Optional[IntentType] = None

    intent_confidence: Optional[float] = None

    entities: Dict[str, Any] = Field(
        default_factory=dict
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    is_from_bot: bool = False

    bot_response_type: Optional[str] = None

    response_to_message_id: Optional[str] = None

    delivery_status: str = "pending"

    delivery_error: Optional[str] = None

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        extra="allow"
    )


# ============================================================
# CUSTOMER
# ============================================================


class Customer(BaseModel):
    """
    WhatsApp customer belonging to exactly one tenant.
    """

    id: str = Field(alias="_id")

    tenant_id: str

    phone_number: str

    wa_id: Optional[str] = None

    name: Optional[str] = None

    profile_name: Optional[str] = None

    is_active: bool = True

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
    )


# ============================================================
# CONVERSATION
# ============================================================


class Conversation(BaseModel):
    """
    Persisted conversation between one tenant and one customer.
    """

    id: str = Field(alias="_id")

    tenant_id: str

    customer_id: str

    customer_phone: Optional[str] = None

    status: str = "active"

    context: ConversationContext = Field(
        default_factory=ConversationContext
    )

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
    )


# ============================================================
# ORDER
# ============================================================


class Order(BaseModel):
    """
    Minimal tenant-scoped order model.
    """

    id: str = Field(alias="_id")

    tenant_id: str

    order_number: str

    customer_id: Optional[str] = None

    status: str = "pending"

    total: float = 0.0

    items: List[Dict[str, Any]] = Field(
        default_factory=list
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
    )


# ============================================================
# TEMPLATE
# ============================================================


class MessageTemplate(BaseModel):
    """
    Tenant-specific WhatsApp template.
    """

    id: str = Field(alias="_id")

    tenant_id: str

    name: str

    language: str = "en"

    content: Optional[str] = None

    is_active: bool = True

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
    )


# ============================================================
# API / WEBHOOK SCHEMAS
# ============================================================


class WhatsAppIncomingMessage(BaseModel):
    """
    Normalized inbound WhatsApp message passed from the webhook layer
    into the message service.
    """

    tenant_id: str

    user_id: str

    text: str

    whatsapp_message_id: Optional[str] = None

    message_type: MessageType = MessageType.TEXT

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )


class DeliveryStatusUpdate(BaseModel):
    """
    Normalized outbound delivery update.
    """

    tenant_id: Optional[str] = None

    outbound_message_id: str

    whatsapp_message_id: Optional[str] = None

    status: str

    error: Optional[str] = None

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )


# ============================================================
# HEALTH
# ============================================================


class HealthResponse(BaseModel):
    status: str

    database: Optional[str] = None

    models_loaded: Optional[bool] = None

    version: Optional[str] = None

    model_config = ConfigDict(
        extra="allow"
    )