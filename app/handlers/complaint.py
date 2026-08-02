"""
Complaint handler - handles customer complaints and escalates to human agents.
"""

from typing import Dict, Any, Optional

from app.handlers.base_handler import BaseHandler
from app.models.schemas import (
    MessageUnderstanding,
    ConversationContext,
    BotResponse,
    EntityType,
)
from app.utils.logger import logger


class ComplaintHandler(BaseHandler):
    """
    Handles COMPLAINT intents.
    Logs the complaint and offers human handoff.
    """

    async def handle(
        self,
        understanding: MessageUnderstanding,
        tenant_id: str,
        tenant_settings: Dict[str, Any],
        conversation_context: Optional[ConversationContext],
    ) -> BotResponse:

        # Log the complaint for internal tracking
        complaint_detail = understanding.original_text

        logger.warning(
            f"Complaint received (tenant: {tenant_id}): {complaint_detail}"
        )

        # Check if human handoff is enabled
        feature_flags = tenant_settings.get("feature_flags", {})
        human_handoff_enabled = feature_flags.get("enable_human_handoff", False)

        if human_handoff_enabled:
            handoff_msg = tenant_settings.get(
                "human_handoff_message",
                "Let me connect you with a human agent who can help resolve this.",
            )

            # Mark conversation for escalation if context is available
            if conversation_context:
                conversation_context.awaiting_confirmation = True
                conversation_context.confirmation_context = {
                    "complaint_logged": True,
                    "complaint_text": complaint_detail,
                    "requires_human": True,
                }

            return BotResponse(
                response_type="text",
                text=handoff_msg,
                quick_replies=[
                    {"label": "Chat with Agent", "value": "human_handoff"},
                    {"label": "Continue with Bot", "value": "continue_bot"},
                ],
                metadata={
                    "complaint_logged": True,
                    "complaint_text": complaint_detail,
                    "human_handoff_offered": True,
                },
            )

        # Human handoff not enabled — provide standard response
        return BotResponse(
            response_type="text",
            text=(
                "I've noted your complaint. Our support team will review it "
                "and get back to you within 24 hours. "
                "Is there anything else I can help you with in the meantime?"
            ),
            quick_replies=[
                {"label": "Track Order", "value": "track_order"},
                {"label": "Browse Products", "value": "browse_products"},
            ],
            metadata={
                "complaint_logged": True,
                "complaint_text": complaint_detail,
                "human_handoff_available": False,
            },
        )
