"""
Inventory data models — adapted to the multi-collection inventory schema.

Clothing items live in per-brand collections (``inventory.clothing_{brand}``)
inside the ``meridin`` database.  Each clothing document holds a single
color/size variant, referencing entries in ``inventory.clothing_attributes``
for the resolved display names, pricing, and stock.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict


class ClothingItem(BaseModel):
    """
    A single clothing variant stored in a per-brand collection.

    The ``color`` and ``size`` fields are foreign-key IDs that reference
    documents in ``inventory.clothing_attributes``.
    """

    id: str = Field(alias="_id")
    tenant_id: str
    title: str
    description: Optional[str] = None
    media: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None
    color: str                     # attribute ID reference
    size: str                      # attribute ID reference
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(populate_by_name=True)


class ClothingAttribute(BaseModel):
    """
    Resolves a color/size attribute ID to its display name and carries
    the variant-level pricing and inventory data.

    Stored in ``inventory.clothing_attributes``.  Each document maps an ID
    to either a ``color`` name or a ``size`` name (per-attribute layout).
    """

    id: str = Field(alias="_id")
    type: Optional[str] = None             # "color" or "size" discriminator
    color: Optional[str] = None            # resolved color name (e.g. "Red")
    size: Optional[str] = None             # resolved size name (e.g. "M")
    name: Optional[str] = None             # generic fallback name
    price: float = 0.0
    stock: int = 0
    age_group: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(populate_by_name=True)

    @property
    def display_name(self) -> str:
        """Return whichever name field is populated."""
        return self.color or self.size or self.name or self.id


class RankedClothingItem(BaseModel):
    """
    A ClothingItem with its resolved attribute data and a relevance score.

    ``sizes_available`` aggregates all size names across variants that share
    the same product title, so the caller can present a grouped view.
    """

    item: ClothingItem
    color_name: str = ""
    size_name: str = ""
    price: float = 0.0
    stock: int = 0
    score: float = 0.0
    sizes_available: List[str] = Field(default_factory=list)
    colors_available: List[str] = Field(default_factory=list)

    # Convenience accessors -------------------------------------------------

    @property
    def product_id(self) -> str:
        return self.item.id

    @property
    def title(self) -> str:
        return self.item.title

    @property
    def image(self) -> Optional[str]:
        return self.item.media[0] if self.item.media else None


class ZeroResultResponse(BaseModel):
    """
    Response returned when a search yields zero results and the progressive
    fallback has selected the closest available products.
    """

    relaxed: bool = True                  # whether filters were relaxed
    relaxed_filters: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    results: List[RankedClothingItem] = Field(default_factory=list)
    total: int = 0
