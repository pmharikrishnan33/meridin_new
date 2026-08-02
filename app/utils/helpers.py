"""
General utility helpers used across the Meridin application.

Includes text processing, ID generation, and data formatting utilities.
"""

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


def generate_id() -> str:
    """Generate a unique ID string (UUID4 hex)."""
    return uuid.uuid4().hex


def generate_order_number(prefix: str = "ORD") -> str:
    """
    Generate a human-readable order number.

    Format: ``{prefix}{YYMMDD}{random4}``
    Example: ``ORD250731A8F3``
    """
    date_str = datetime.utcnow().strftime("%y%m%d")
    random_suffix = uuid.uuid4().hex[:4].upper()
    return f"{prefix}{date_str}{random_suffix}"


def sanitize_phone_number(phone: str) -> str:
    """
    Sanitize a phone number for WhatsApp.

    Removes ``+``, ``-``, spaces, and leading zeros, returning just
    the digits (country code + number).
    """
    cleaned = re.sub(r"[^\d]", "", phone)
    return cleaned


def truncate_text(text: str, max_length: int = 4096) -> str:
    """
    Truncate text to ``max_length`` characters, appending an ellipsis
    if truncation occurs.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def format_currency(amount: float, currency: str = "INR") -> str:
    """
    Format a numeric amount as a currency string.

    Uses the appropriate symbol for common currencies.
    """
    symbols = {
        "INR": "₹",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
    }
    symbol = symbols.get(currency, currency)
    return f"{symbol}{amount:,.2f}"


def safe_get(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """
    Safely retrieve a nested value from a dict.

    Usage::

        value = safe_get(data, "user", "profile", "name", default="Unknown")
    """
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge ``override`` into ``base``.

    Returns a new dict; neither input is modified.
    """
    result = base.copy()
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def parse_bool(value: Any) -> bool:
    """
    Parse a value into a boolean.

    Accepts: True/False, "true"/"false", 1/0, "yes"/"no", "on"/"off".
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on", "y", "t"}
    return False


def extract_digits(text: str) -> str:
    """Extract only the digit characters from a string."""
    return re.sub(r"[^\d]", "", text)


def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into a single space."""
    return re.sub(r"\s+", " ", text).strip()


def chunk_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Split a list into chunks of at most ``chunk_size`` items.
    """
    if chunk_size <= 0:
        return [items]
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def format_timestamp(dt: Optional[datetime] = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format a datetime as a string, defaulting to now in UTC."""
    if dt is None:
        dt = datetime.utcnow()
    return dt.strftime(fmt)
