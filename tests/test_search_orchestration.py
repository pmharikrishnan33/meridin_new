import unittest

from app.conversation.session import ConversationSession
from app.models.schemas import (
    ConversationContext,
    ConversationStatus,
    MessageDirection,
    MessageType,
    ProductSearchFilters,
    ResponseProduct,
)
from app.services.inventory_search_service import inventory_search_service
from app.services.response_service import response_service


class SearchOrchestrationTests(unittest.TestCase):
    def test_session_can_store_active_search_and_advance_pages(self):
        session = ConversationSession(
            conversation_id="conv-1",
            tenant_id="tenant-1",
            customer_id="cust-1",
            context=ConversationContext(),
        )

        session.store_active_search(
            search_key="search-abc",
            query="blue dress",
            filters={"category": "dress", "color": "blue"},
            result_ids=["p1", "p2", "p3", "p4"],
            offset=0,
            total=4,
            page_size=2,
        )

        active = session.get_active_search()
        self.assertEqual(active["search_key"], "search-abc")
        self.assertEqual(active["page_size"], 2)
        self.assertEqual(active["offset"], 0)

        session.advance_active_search(page_size=2)
        active = session.get_active_search()
        self.assertEqual(active["offset"], 2)
        self.assertEqual(active["page"], 2)

    def test_inventory_search_service_builds_stable_page_metadata(self):
        filters = ProductSearchFilters(query="dress", brand="nike", limit=2)

        page = inventory_search_service.build_search_page(
            tenant_id="tenant-1",
            filters=filters,
            result_ids=["p1", "p2", "p3", "p4"],
            page=2,
        )

        self.assertTrue(page["search_key"])
        self.assertEqual(page["page"], 2)
        self.assertEqual(page["page_size"], 2)
        self.assertEqual(page["total"], 4)
        self.assertEqual(page["items"], ["p3", "p4"])
        self.assertFalse(page["has_prev"] is False)
        self.assertEqual(page["has_next"], False)

    def test_response_service_preserves_product_details_for_catalog_cards(self):
        response = response_service.build_product_list_response(
            products=[
                ResponseProduct(
                    product_id="p1",
                    name="Blue Dress",
                    price=999.0,
                    image="https://example.com/blue-dress.jpg",
                    sizes_available=["S", "M", "L"],
                    colors_available=["Blue"],
                    in_stock=True,
                    stock=6,
                    category="dress",
                    product_type="party dress",
                )
            ],
            intro_text="I found 1 item for you:",
            quick_replies=[{"label": "Show more", "value": "show_more"}],
        )

        self.assertEqual(response.response_type, "product_list")
        self.assertEqual(response.products[0].name, "Blue Dress")
        self.assertEqual(response.products[0].stock, 6)
        self.assertEqual(response.products[0].category, "dress")
        self.assertEqual(response.quick_replies[0]["value"], "show_more")


if __name__ == "__main__":
    unittest.main()
