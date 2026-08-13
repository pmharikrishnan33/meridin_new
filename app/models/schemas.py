from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ==========================================================
# ENUMS
# ==========================================================

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


# ==========================================================
# INCOMING MESSAGE (WhatsApp Webhook)
# ==========================================================

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
    """
    Normalized incoming message after webhook parsing.
    """
    user_id: str
    tenant_id: str
    text: str
    message_type: MessageType = MessageType.TEXT
    media_id: Optional[str] = None
    media_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


# ==========================================================
# TENANT
# ==========================================================

class TenantFeatureFlags(BaseModel):
    """
    Feature flags per tenant - stored in MongoDB.
    """
    enable_ai_responses: bool = True
    enable_product_recommendations: bool = True
    enable_order_tracking: bool = False
    enable_returns: bool = False
    enable_cancellation: bool = False
    enable_human_handoff: bool = True
    enable_analytics: bool = True
    max_products_per_response: int = 5
    supported_languages: List[str] = Field(default_factory=lambda: ["en"])
    business_hours: Dict[str, str] = Field(default_factory=dict)
    auto_reply_outside_hours: bool = False
    out_of_hours_message: str = "We're currently closed. We'll get back to you during business hours."


class TenantSettings(BaseModel):
    """
    Nested tenant settings that are safe to keep under the ``settings``
    object. Only the webhook secret is modeled here to avoid duplicating
    the primary tenant credential fields at two different levels.
    """
    webhook_secret: Optional[str] = None


class Tenant(BaseModel):
    """
    Tenant model - stored in MongoDB.
    """

    id: str = Field(alias="_id")
    tenant_id: Optional[str] = None
    tenant_name: str
    business_name: str
    phone_number_id: str
    access_token: str
    webhook_verify_token: str
    is_active: bool = True

    settings: TenantSettings = Field(
        default_factory=TenantSettings
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow
    )

    model_config = ConfigDict(
        populate_by_name=True
    )


# ==========================================================
# PRODUCT
# ==========================================================

class ProductVariant(BaseModel):
    size: str
    color: str
    fit: Optional[str] = None
    sku: str
    stock: int = 0
    price: float
    sale_price: Optional[float] = None
    images: List[str] = Field(default_factory=list)


class Product(BaseModel):
    """
    Product model - stored in MongoDB (tenant-specific collection or shared with tenant_id).
    """
    id: str = Field(alias="_id")
    tenant_id: str
    name: str = Field(alias="title")
    description: str
    category: str
    type: Optional[str] = None
    sub_category: Optional[str] = None
    brand: Optional[str] = None
    gender: Optional[str] = None  # men, women, unisex, kids
    base_price: float = Field(alias="price")
    currency: str = "INR"
    tags: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    color: List[str] = Field(default_factory=list)
    size: List[str] = Field(default_factory=list)
    stock: int = 0
    images: List[str] = Field(default_factory=list, alias="media")
    is_active: bool = True
    is_featured: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(populate_by_name=True)


class ProductSearchFilters(BaseModel):
    """
    Filters for product search.
    """
    query: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    sub_category: Optional[str] = None
    brand: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    fit: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    in_stock_only: bool = True
    gender: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    limit: int = 10
    offset: int = 0
    sort_by: str = "relevance"  # relevance, price_asc, price_desc, newest, popular


class ProductSearchResult(BaseModel):
    """
    Product search result with scoring.
    """
    product: Product
    score: float
    matched_attributes: List[str] = Field(default_factory=list)


# ==========================================================
# CUSTOMER
# ==========================================================

class Customer(BaseModel):
    """
    Customer model - stored in MongoDB.
    """
    id: Optional[str] = Field(default=None, alias="_id")
    tenant_id: str
    phone_number: str
    wa_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    language: str = "en"
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    is_blocked: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_interaction_at: Optional[datetime] = None

    model_config = ConfigDict(populate_by_name=True)


# ==========================================================
# CONVERSATION
# ==========================================================

class ConversationContext(BaseModel):
    """
    Current conversation context - maintained in memory and persisted.
    """
    current_intent: Optional[IntentType] = None
    current_product: Optional[str] = None  # product_id
    current_category: Optional[str] = None
    last_search_filters: Dict[str, Any] = Field(default_factory=dict)
    last_search_results: List[str] = Field(default_factory=list)  # product_ids
    last_order_id: Optional[str] = None
    awaiting_entity: Optional[EntityType] = None
    awaiting_confirmation: bool = False
    confirmation_context: Dict[str, Any] = Field(default_factory=dict)
    language: str = "en"
    message_count: int = 0

    # -- Inventory search state -------------------------------------------
    # Tracks the most recent AI-ranked search so that "Next" / navigation
    # can paginate the cached ranked list without re-querying the database.
    active_search_key: Optional[str] = None
    active_search_offset: int = 0
    active_search_total: int = 0
    active_search_query: Optional[str] = None
    active_search_filters: Dict[str, Any] = Field(default_factory=dict)
    active_search_results: List[str] = Field(default_factory=list)
    active_search_page: int = 1
    active_search_page_size: int = 10

    # -- Inventory store -------------------------------------------
    # The store_name used to resolve the ``inventory.<store_name>`` collection
    # on follow-up messages (e.g. "show more", pagination).
    active_store_name: Optional[str] = None


class Conversation(BaseModel):
    """
    Conversation model - stored in MongoDB.
    """
    id: Optional[str] = Field(default=None, alias="_id")
    tenant_id: str
    customer_id: str
    status: ConversationStatus = ConversationStatus.ACTIVE
    context: ConversationContext = Field(default_factory=ConversationContext)
    assigned_agent_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None

    model_config = ConfigDict(populate_by_name=True)


# ==========================================================
# MESSAGE
# ==========================================================

class Message(BaseModel):
    """
    Message model - stored in MongoDB.
    """
    id: Optional[str] = Field(default=None, alias="_id")
    tenant_id: str
    conversation_id: str
    customer_id: str
    direction: MessageDirection
    message_type: MessageType
    text: Optional[str] = None
    media_url: Optional[str] = None
    media_id: Optional[str] = None
    media_mime_type: Optional[str] = None
    intent: Optional[IntentType] = None
    intent_confidence: Optional[float] = None
    entities: Dict[str, Any] = Field(default_factory=dict)
    response_to_message_id: Optional[str] = None
    is_from_bot: bool = False
    bot_response_type: Optional[str] = None  # template, ai, structured
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(populate_by_name=True)


# ==========================================================
# ORDER
# ==========================================================

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
    """
    Order model - stored in MongoDB.
    """
    id: str = Field(alias="_id")
    tenant_id: str
    customer_id: str
    order_number: str
    status: OrderStatus = OrderStatus.PENDING
    items: List[OrderItem] = Field(default_factory=list)
    subtotal: float = 0.0
    tax: float = 0.0
    shipping: float = 0.0
    discount: float = 0.0
    total: float = 0.0
    currency: str = "INR"
    shipping_address: Optional[ShippingAddress] = None
    payment_method: Optional[str] = None
    payment_status: str = "pending"
    payment_id: Optional[str] = None
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    notes: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    model_config = ConfigDict(populate_by_name=True)


# ==========================================================
# UNDERSTANDING (ML OUTPUT)
# ==========================================================

class ExtractedEntity(BaseModel):
    """
    Single extracted entity from user message.
    """
    entity_type: EntityType
    value: str
    confidence: float
    start_pos: int = 0
    end_pos: int = 0
    normalized_value: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MessageUnderstanding(BaseModel):
    """
    Complete understanding of a user message after ML processing.
    """
    original_text: str
    normalized_text: str
    intent: IntentType
    intent_confidence: float
    entities: List[ExtractedEntity] = Field(default_factory=list)
    sentiment: Optional[str] = None  # positive, negative, neutral
    language: str = "en"
    needs_clarification: bool = False
    clarification_question: Optional[str] = None


# ==========================================================
# RESPONSE
# ==========================================================

class ResponseProduct(BaseModel):
    """
    Product summary for response.
    """
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
    sizes_available: List[str] = Field(default_factory=list)
    colors_available: List[str] = Field(default_factory=list)
    in_stock: bool = True


class BotResponse(BaseModel):
    """
    Structured bot response ready for WhatsApp formatting.
    """
    response_type: str  # text, product_list, product_card, order_status, quick_reply, template
    text: Optional[str] = None
    products: List[ResponseProduct] = Field(default_factory=list)
    quick_replies: List[Dict[str, str]] = Field(default_factory=list)
    template_name: Optional[str] = None
    template_params: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ==========================================================
# ANALYTICS
# ==========================================================

class AnalyticsEvent(BaseModel):
    """
    Analytics event - stored in MongoDB.
    """
    id: Optional[str] = Field(default=None, alias="_id")
    tenant_id: str
    customer_id: Optional[str] = None
    conversation_id: Optional[str] = None
    event_type: str  # message_received, intent_detected, product_viewed, order_placed, etc.
    event_data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(populate_by_name=True)


# ==========================================================
# TEMPLATE
# ==========================================================

class Template(BaseModel):
    """
    Message template — stored in MongoDB, scoped per tenant.

    Used by handlers (GreetingHandler, ThanksHandler, FallbackHandler) to
    build responses without hardcoding text.
    """
    id: Optional[str] = Field(default=None, alias="_id")
    tenant_id: str
    name: str                # e.g. "greeting", "thanks", "fallback"
    language: str = "en"
    category: str = "UTILITY"  # MARKETING or UTILITY (WhatsApp category)
    response_type: str = "text"  # text, product_list, order_status, template, ai
    body_text: Optional[str] = None
    quick_replies: List[Dict[str, str]] = Field(default_factory=list)
    footer_text: Optional[str] = None
    variables: List[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(populate_by_name=True)
