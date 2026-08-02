import json
import re
from pathlib import Path

from app.core.config import settings
from app.utils.logger import logger


class TextNormalizer:
    """
    Normalizes user input text:
    - Expands abbreviations (blk -> black, xlrg -> xl)
    - Fixes common typos (hoddie -> hoodie, tshirt -> t-shirt)
    - Standardizes size formats (xlrg -> xl, xxxl -> 3xl)
    """

    def __init__(self):
        self.dictionary: dict[str, str] = {}
        self._compiled_patterns: list[tuple[re.Pattern, str]] = []
        self._loaded = False

    def load(self) -> None:
        """
        Load normalization dictionary from JSON file.
        """

        if self._loaded:
            return

        path = Path(settings.NORMALIZATION_FILE)

        if not path.exists():
            logger.warning(f"Normalization file not found: {path}")
            self.dictionary = {}
            self._loaded = True
            return

        with open(path, "r", encoding="utf-8") as f:
            self.dictionary = json.load(f)

        # Pre-compile regex patterns for whole-word matching
        self._compiled_patterns = []
        for key, value in self.dictionary.items():
            # Use word boundaries for exact word matching
            pattern = re.compile(rf'\b{re.escape(key)}\b')
            self._compiled_patterns.append((pattern, value))

        logger.info(f"Loaded {len(self.dictionary)} normalization rules.")
        self._loaded = True

    def normalize(self, text: str) -> str:
        """
        Apply normalization rules to text.
        """
        if not self.dictionary:
            return text

        result = text.lower()

        # Apply each normalization rule
        for pattern, replacement in self._compiled_patterns:
            result = pattern.sub(replacement, result)

        # Clean up extra spaces
        result = re.sub(r'\s+', ' ', result).strip()

        return result


normalizer = TextNormalizer()
