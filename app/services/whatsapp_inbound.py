"""
Normalize incoming WhatsApp Cloud API messages.

For the current Meridin pagination flow we support:

1. Normal text messages
2. WhatsApp interactive button replies
3. WhatsApp interactive list replies

Interactive replies are converted into deterministic internal commands.
"""

from typing import Any, Dict, Optional


def normalize_whatsapp_message(
    message: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Convert one WhatsApp message into Meridin's internal format.

    Returns None for unsupported message types.
    """

    message_id = message.get("id")
    sender = message.get("from")
    message_type = message.get("type")

    if not message_id or not sender or not message_type:
        return None

    # =========================================================
    # TEXT MESSAGE
    # =========================================================

    if message_type == "text":

        body = (
            message.get("text") or {}
        ).get("body")

        if not body:
            return None

        body = body.strip()

        if not body:
            return None

        return {
            "whatsapp_message_id": str(
                message_id
            ),
            "user_id": str(sender),
            "text": body,
            "message_type": "text",
            "metadata": {},
        }

    # =========================================================
    # INTERACTIVE MESSAGE
    # =========================================================

    if message_type == "interactive":

        interactive = (
            message.get("interactive")
            or {}
        )

        interactive_type = interactive.get(
            "type"
        )

        # -----------------------------------------------------
        # BUTTON REPLY
        # -----------------------------------------------------

        if interactive_type == "button_reply":

            reply = (
                interactive.get(
                    "button_reply"
                )
                or {}
            )

            reply_id = reply.get("id")
            reply_title = reply.get("title")

            if not reply_id:
                return None

            return {
                "whatsapp_message_id": str(
                    message_id
                ),
                "user_id": str(sender),

                # IMPORTANT:
                # This bypasses ML later.
                "text": (
                    f"__COMMAND__:{reply_id}"
                ),

                "message_type": "interactive",

                "metadata": {
                    "interactive_type":
                        "button_reply",
                    "reply_id":
                        reply_id,
                    "reply_title":
                        reply_title,
                },
            }

        # -----------------------------------------------------
        # LIST REPLY
        # -----------------------------------------------------

        if interactive_type == "list_reply":

            reply = (
                interactive.get(
                    "list_reply"
                )
                or {}
            )

            reply_id = reply.get("id")
            reply_title = reply.get("title")
            reply_description = reply.get(
                "description"
            )

            if not reply_id:
                return None

            return {
                "whatsapp_message_id": str(
                    message_id
                ),
                "user_id": str(sender),

                "text": (
                    f"__COMMAND__:{reply_id}"
                ),

                "message_type": "interactive",

                "metadata": {
                    "interactive_type":
                        "list_reply",
                    "reply_id":
                        reply_id,
                    "reply_title":
                        reply_title,
                    "reply_description":
                        reply_description,
                },
            }

    # =========================================================
    # UNSUPPORTED MESSAGE TYPE
    # =========================================================

    return None