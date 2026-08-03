"""
Narrowing service — generates AI-powered filtering questions when a
search returns too many results.

Delegates to the LLM ranking module for question generation, with
static fallbacks when the LLM is unavailable.
"""

from typing import List, Dict, Any

from app.search.ai_ranking import generate_narrowing_questions
from app.utils.logger import logger


# Default result count above which we ask narrowing questions
NARROWING_THRESHOLD = 10


class NarrowingService:
    """
    Generates follow-up questions to help the user narrow down search results.
    """

    async def should_narrow(self, result_count: int, threshold: int = NARROWING_THRESHOLD) -> bool:
        """Return True if the result count exceeds the narrowing threshold."""
        return result_count > threshold

    async def generate_questions(
        self,
        query: str,
        result_count: int,
        filters: Dict[str, Any],
    ) -> List[str]:
        """
        Generate 2-3 narrowing questions using the LLM.

        Falls back to static questions generated from the current filters
        when the LLM is unavailable.
        """
        logger.info(
            f"Generating {result_count} narrowing questions for query: {query}"
        )
        return await generate_narrowing_questions(query, result_count, filters)


narrowing_service = NarrowingService()
