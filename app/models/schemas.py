from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class IntentType(str, Enum):
    GREETING = "greeting"
    PRODUCT_SEARCH = "product_search"
    PRODUCT_INQUIRY = "product_inquiry"
    AVAILABILITY = "availability"
    PAGINATION = "pagination"
    ORDER_STATUS = "order_status"
    CANCEL_ORDER = "cancel_order"
    RETURN_REQUEST = "return_request"
    COMPLAINT = "complaint"
    THANKS = "thanks"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    PRODUCT = "product"
    COLOR = "color"
    SIZE = "size"
    FIT = "fit"
    PRICE = "price"
    BRAND = "brand"
    CATEGORY = "category"
    ORDER_ID = "order_id"
    DATE = "date"
    DISCOUNT = "discount"
    GENDER = "gender"
    MATERIAL = "material"
    NECK = "neck"
    OCCASION = "occasion"
    PATTERN = "pattern"
    SEASON = "season"
    SLEEVE = "sleeve"
    STYLE = "style"


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    INTERACTIVE = "interactive"
    LOCATION = "location"
    CONTACT = "contact"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    TEMPLATE = "template"


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    ESCALATED = "escalated"
    BOT_HANDOFF = "bot_handoff"


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    REFUNDED = "refunded"


class WhatsAppContact(BaseModel):
    profile: Optional[Dict[str, str]] = None
    wa_id: str


class WhatsAppMessage(BaseModel):
    from_: str = Field(alias="from")
    id: str
    timestamp: str
    type: str

    text: Optional[Dict[str, str]] = None
    image: Optional[Dict[str, Any]] = None
    interactive: Optional[Dict[str, Any]] = None
    location: Optional[Dict[str, Any]] = None
    contacts: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(
        populate_by_name=True
    )


class WhatsAppChange(BaseModel):
    field: str
    value: Dict[str, Any]


class WhatsAppEntry(BaseModel):
    id: str
    changes: List[WhatsAppChange]


class IncomingWhatsAppWebhook(BaseModel):
    object: str
    entry: List[WhatsAppEntry]


class IncomingMessage(BaseModel):
    user_id: str
    tenant_id: str
    text: str

    message_type: MessageType = (
        MessageType.TEXT
    )

    media_id: Optional[str] = None
    media_url: Optional[str] = None

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    timestamp: datetime = Field(
        default_factory=_now_utc
    )

    raw_payload: Dict[str, Any] = Field(
        default_factory=dict
    )


class TenantSettings(BaseModel):
    webhook_secret: Optional[str] = None


class TenantFeatureFlags(BaseModel):
    enable_ai_responses: bool = True
    enable_product_recommendations: bool = True

    enable_order_tracking: bool = False
    enable_returns: bool = False
    enable_cancellation: bool = False

    enable_human_handoff: bool = True
    enable_analytics: bool = True

    use_synonyms: bool = True

    # WhatsApp product responses are capped by the application at three
    # products per response.
    max_products_per_response: int = 3

    auto_reply_outside_hours: bool = False


class Tenant(BaseModel):
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


class ProductVariant(BaseModel):
    size: str
    color: str
    fit: Optional[str] = None
    sku: str

    stock: int = 0

    price: float
    sale_price: Optional[float] = None

    images: List[str] = Field(
        default_factory=list
    )


class Product(BaseModel):
    id: str = Field(alias="_id")
    tenant_id: str

    title: str
    description: Optional[str] = None

    price: float = 0.0

    department_id: Optional[int] = None
    category_id: Optional[int] = None

    # Legacy/display fields retained for migration compatibility.
    category: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None

    color_ids: List[int] = Field(
        default_factory=list
    )

    color: List[str] = Field(
        default_factory=list
    )

    size_group: Optional[str] = None

    size_ids: List[int] = Field(
        default_factory=list
    )

    size: List[str] = Field(
        default_factory=list
    )

    material: Optional[str] = None
    fit: Optional[str] = None
    gender: Optional[str] = None
    age_group: Optional[str] = None

    tags: List[str] = Field(
        default_factory=list
    )

    stock: int = 0

    media: List[str] = Field(
        default_factory=list
    )

    variants: List[Dict[str, Any]] = Field(
        default_factory=list
    )

    is_featured: bool = False

    # Category-specific metadata attributes.
    attributes: Dict[str, Any] = Field(default_factory=dict)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(
        populate_by_name=True
    )

    @property
    def name(self) -> str:
        return self.title


class ProductSearchFilters(BaseModel):
    query: Optional[str] = None

    department_id: Optional[int] = None
    category_id: Optional[int] = None
    category_ids: List[int] = Field(default_factory=list)

    category: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None
    material: Optional[str] = None
    fit: Optional[str] = None
    gender: Optional[str] = None

    color_id: Optional[int] = None
    color: Optional[str] = None

    size_group: Optional[str] = None
    size_id: Optional[int] = None
    size: Optional[str] = None

    tags: List[str] = Field(
        default_factory=list
    )

    min_price: Optional[float] = None
    max_price: Optional[float] = None

    in_stock_only: bool = True
    age_group: Optional[str] = None

    # Metadata-driven requirements may use these fields. They are kept
    # explicit rather than relying on Pydantic extra fields.
    style: Optional[str] = None
    pattern: Optional[str] = None
    occasion: Optional[str] = None
    season: Optional[str] = None
    sleeve: Optional[str] = None
    neck: Optional[str] = None

    # Metadata-defined category attributes, e.g. dress_style.
    attributes: Dict[str, Any] = Field(default_factory=dict)

    limit: int = 10
    offset: int = 0
    sort_by: str = "relevance"

    model_config = ConfigDict(
        extra="forbid"
    )


class ProductSearchResult(BaseModel):
    product: Product
    score: float

    matched_attributes: List[str] = Field(
        default_factory=list
    )


class Customer(BaseModel):
    id: Optional[str] = Field(
        default=None,
        alias="_id",
    )

    tenant_id: str

    phone_number: str
    wa_id: str

    name: Optional[str] = None
    email: Optional[str] = None

    language: str = "en"

    tags: List[str] = Field(
        default_factory=list
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    is_blocked: bool = False

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    last_interaction_at: Optional[
        datetime
    ] = None

    model_config = ConfigDict(
        populate_by_name=True
    )


class ConversationContext(BaseModel):
    current_intent: Optional[IntentType] = None
    current_product: Optional[str] = None
    current_category: Optional[str] = None

    last_search_filters: Dict[str, Any] = Field(
        default_factory=dict
    )

    last_search_results: List[str] = Field(
        default_factory=list
    )

    last_order_id: Optional[str] = None

    awaiting_entity: Optional[EntityType] = None

    awaiting_confirmation: bool = False

    confirmation_context: Dict[str, Any] = Field(
        default_factory=dict
    )

    language: str = "en"

    message_count: int = 0

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

    active_search_page_size: int = 3

    active_store_name: Optional[str] = None

    _message_history: Optional[
        List[Dict[str, Any]]
    ] = PrivateAttr(
        default=None
    )


class Conversation(BaseModel):
    id: Optional[str] = Field(
        default=None,
        alias="_id",
    )

    tenant_id: str
    customer_id: str

    status: ConversationStatus = (
        ConversationStatus.ACTIVE
    )

    context: ConversationContext = Field(
        default_factory=ConversationContext
    )

    assigned_agent_id: Optional[str] = None

    tags: List[str] = Field(
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

    closed_at: Optional[datetime] = None

    model_config = ConfigDict(
        populate_by_name=True
    )


class Message(BaseModel):
    id: Optional[str] = Field(
        default=None,
        alias="_id",
    )

    tenant_id: str
    conversation_id: str
    customer_id: str

    whatsapp_message_id: Optional[str] = None

    direction: MessageDirection
    message_type: MessageType

    text: Optional[str] = None

    media_url: Optional[str] = None
    media_id: Optional[str] = None
    media_mime_type: Optional[str] = None

    intent: Optional[IntentType] = None
    intent_confidence: Optional[float] = None

    entities: Dict[str, Any] = Field(
        default_factory=dict
    )

    response_to_message_id: Optional[str] = None

    is_from_bot: bool = False
    bot_response_type: Optional[str] = None

    delivery_status: Optional[str] = None
    delivery_error: Optional[str] = None

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    sent_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None

    model_config = ConfigDict(
        populate_by_name=True
    )


class OrderItem(BaseModel):
    product_id: str
    variant_sku: str
    name: str

    size: str
    color: str

    fit: Optional[str] = None

    quantity: int

    unit_price: float
    total_price: float


class ShippingAddress(BaseModel):
    name: str
    phone: str

    address_line1: str
    address_line2: Optional[str] = None

    city: str
    state: str
    postal_code: str

    country: str = "India"


class Order(BaseModel):
    id: str = Field(alias="_id")

    tenant_id: str
    customer_id: str

    order_number: str

    status: OrderStatus = (
        OrderStatus.PENDING
    )

    items: List[OrderItem] = Field(
        default_factory=list
    )

    subtotal: float = 0.0
    tax: float = 0.0
    shipping: float = 0.0
    discount: float = 0.0
    total: float = 0.0

    currency: str = "INR"

    shipping_address: Optional[
        ShippingAddress
    ] = None

    payment_method: Optional[str] = None
    payment_status: str = "pending"
    payment_id: Optional[str] = None

    tracking_number: Optional[str] = None
    carrier: Optional[str] = None

    notes: Optional[str] = None

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    confirmed_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    model_config = ConfigDict(
        populate_by_name=True
    )


class ExtractedEntity(BaseModel):
    entity_type: EntityType

    value: str

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    start_pos: int = 0
    end_pos: int = 0

    normalized_value: Optional[str] = None

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )


class MessageUnderstanding(BaseModel):
    original_text: str
    normalized_text: str

    intent: IntentType

    intent_confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    entities: List[ExtractedEntity] = Field(
        default_factory=list
    )

    sentiment: Optional[str] = None
    language: str = "en"

    needs_clarification: bool = False

    clarification_question: Optional[str] = None


class ResponseProduct(BaseModel):
    product_id: str

    name: str

    price: float

    sale_price: Optional[float] = None

    currency: str = "INR"

    image: Optional[str] = None

    stock: int = 0

    category: Optional[str] = None
    product_type: Optional[str] = None

    description: Optional[str] = None

    sizes_available: List[str] = Field(
        default_factory=list
    )

    colors_available: List[str] = Field(
        default_factory=list
    )

    in_stock: bool = True


class BotResponse(BaseModel):
    response_type: str

    text: Optional[str] = None

    products: List[ResponseProduct] = Field(
        default_factory=list
    )

    quick_replies: List[
        Dict[str, str]
    ] = Field(
        default_factory=list
    )

    template_name: Optional[str] = None

    template_params: List[str] = Field(
        default_factory=list
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )


class AnalyticsEvent(BaseModel):
    id: Optional[str] = Field(
        default=None,
        alias="_id",
    )

    tenant_id: str

    customer_id: Optional[str] = None
    conversation_id: Optional[str] = None

    event_type: str

    event_data: Dict[str, Any] = Field(
        default_factory=dict
    )

    timestamp: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        populate_by_name=True
    )


class Template(BaseModel):
    id: Optional[str] = Field(
        default=None,
        alias="_id",
    )

    tenant_id: str

    name: str

    language: str = "en"

    category: str = "UTILITY"

    response_type: str = "text"

    body_text: Optional[str] = None

    quick_replies: List[
        Dict[str, str]
    ] = Field(
        default_factory=list
    )

    footer_text: Optional[str] = None

    variables: List[str] = Field(
        default_factory=list
    )

    is_active: bool = True

    created_at: datetime = Field(
        default_factory=_now_utc
    )

    updated_at: datetime = Field(
        default_factory=_now_utc
    )

    model_config = ConfigDict(
        populate_by_name=True
    )