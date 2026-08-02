"""
Prompt templates for LLM-powered responses.

Each template is a function that builds a list of messages suitable for
the OpenRouter chat completions API.  Templates are organized by intent
so that the fallback handler can request intent-specific guidance.
"""

from typing import List, Dict

from app.models.schemas import IntentType, MessageUnderstanding


def _base_system_prompt() -> str:
    """Core system instructions shared across all intents."""
    return (
        "You are Meridin, a helpful WhatsApp shopping assistant for an Indian "
        "e-commerce store. Respond concisely and in the user's language. "
        "Do not reveal that you are an AI. Keep responses under 200 words. "
        "If you don't understand something, ask a clarifying question."
    )


def _intent_context(intent: IntentType) -> str:
    """Return a short instruction string specific to the given intent."""
    mapping: Dict[IntentType, str] = {
        IntentType.PRODUCT_SEARCH: (
            "The user is looking for a product. Suggest relevant items, "
            "mention price ranges, and ask if they'd like to see more details "
            "or check availability."
        ),
        IntentType.PRODUCT_INQUIRY: (
            "The user is asking about a specific product. Provide details "
            "about materials, sizing, care instructions, and availability."
        ),
        IntentType.AVAILABILITY: (
            "The user is asking about stock availability. Mention which sizes "
            "and colors are in stock and the expected restock date if applicable."
        ),
        IntentType.ORDER_STATUS: (
            "The user is asking about their order status. Provide the current "
            "status, estimated delivery date, and tracking information if available."
        ),
        IntentType.CANCEL_ORDER: (
            "The user wants to cancel an order. Explain the cancellation policy, "
            "confirm the order can be cancelled, and guide them through next steps."
        ),
        IntentType.RETURN_REQUEST: (
            "The user wants to return or exchange an item. Explain the return "
            "policy, eligibility criteria, and how to initiate the return process."
        ),
        IntentType.COMPLAINT: (
            "The user has a complaint. Acknowledge their concern, apologize for "
            "any inconvenience, and offer to escalate to a human agent if needed."
        ),
        IntentType.GREETING: (
            "Respond with a friendly greeting and offer quick-reply options "
            "for browsing products, tracking orders, or getting help."
        ),
        IntentType.THANKS: (
            "Respond politely to the user's gratitude and ask if there's "
            "anything else you can help with."
        ),
        IntentType.UNKNOWN: (
            "The user's intent is unclear. Ask a clarifying question and offer "
            "suggested quick-reply options."
        ),
    }
    return mapping.get(intent, mapping[IntentType.UNKNOWN])


def build_messages(
    understanding: MessageUnderstanding,
    conversation_history: List[Dict[str, str]] | None = None,
) -> List[Dict[str, str]]:
    """
    Build a full message list for the LLM from a message understanding
    and optional conversation history.
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _base_system_prompt() + " " + _intent_context(understanding.intent)},
    ]

    if conversation_history:
        messages.extend(conversation_history[-10:])

    messages.append(
        {
            "role": "user",
            "content": understanding.original_text,
        }
    )

    return messages


def build_fallback_messages(
    user_text: str,
    conversation_history: List[Dict[str, str]] | None = None,
) -> List[Dict[str, str]]:
    """
    Build messages for a generic fallback response when intent is unknown.
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _base_system_prompt() + " " + _intent_context(IntentType.UNKNOWN)},
    ]

    if conversation_history:
        messages.extend(conversation_history[-10:])

    messages.append({"role": "user", "content": user_text})

    return messages


# Common response templates for structured replies
RESPONSE_TEMPLATES: Dict[str, str] = {
    "greeting": "Hello! 👋 Welcome to our store. How can I help you today?",
    "fallback": "I'm sorry, I didn't quite understand that. Could you rephrase?",
    "out_of_stock": "I'm sorry, that item is currently out of stock.",
    "order_not_found": "I couldn't find an order with that ID. Could you double-check?",
    "human_handoff": "Let me connect you with a human agent who can help.",
}
