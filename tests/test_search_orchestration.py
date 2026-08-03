import unittest

from app.conversation.session import ConversationSession
from app.models.schemas import (
    ConversationContext,
    ConversationStatus,
    MessageDirection,
    MessageType,
    ProductSearchFilters,
)
from app.services.inventory_search_service import inventory_search_service


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


if __name__ == "__main__":
    unittest.main()
