import json
from pathlib import Path
from typing import List, Dict, Set

from rapidfuzz import process, fuzz

from app.core.config import settings
from app.utils.logger import logger


class VocabularyMatcher:
    """
    Fuzzy matches words to known vocabulary.
    Handles typos, variations, and unknown words.
    """

    def __init__(self):
        self.words: List[str] = []
        self.word_to_category: Dict[str, str] = {}
        self._categories: Dict[str, Set[str]] = {}

    def load(self) -> None:
        """
        Load vocabulary from JSON file.
        Expected format:
        {
            "products": ["hoodie", "t-shirt", "jeans", ...],
            "colors": ["black", "white", "blue", ...],
            "sizes": ["xs", "s", "m", "l", "xl", ...],
            "fits": ["regular", "slim", "oversized", ...]
        }
        """

        path = Path(settings.VOCABULARY_FILE)

        if not path.exists():
            logger.warning(f"Vocabulary file not found: {path}")
            self.words = []
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.words = []
        self.word_to_category = {}
        self._categories = {}

        for category, word_list in data.items():
            self._categories[category] = set(word_list)
            for word in word_list:
                self.words.append(word)
                self.word_to_category[word] = category

        logger.info(f"Loaded {len(self.words)} vocabulary words across {len(self._categories)} categories.")

    def match_word(self, word: str, score_cutoff: int = 85) -> str:
        """
        Fuzzy match a single word to vocabulary.
        Returns the matched word or original if no good match.
        """

        if not self.words:
            return word

        result = process.extractOne(
            word,
            self.words,
            scorer=fuzz.ratio,
            score_cutoff=score_cutoff
        )

        if result:
            matched_word = result[0]
            logger.debug(f"Vocabulary match: '{word}' -> '{matched_word}' (score: {result[1]})")
            return matched_word

        return word

    def get_category(self, word: str) -> str | None:
        """
        Get the category of a vocabulary word.
        """
        return self.word_to_category.get(word)

    def get_words_by_category(self, category: str) -> List[str]:
        """
        Get all vocabulary words for a category.
        """
        return list(self._categories.get(category, set()))

    def process(self, text: str, score_cutoff: int = 85) -> str:
        """
        Process entire text, matching each word to vocabulary.
        """
        if not self.words:
            return text

        words = text.split()
        output = []

        for word in words:
            matched = self.match_word(word, score_cutoff)
            output.append(matched)

        return " ".join(output)

    def extract_entities_by_vocab(self, text: str) -> Dict[str, List[str]]:
        """
        Extract entities by matching against vocabulary categories.
        Returns dict of category -> matched words.
        """
        entities: Dict[str, List[str]] = {cat: [] for cat in self._categories}

        words = text.lower().split()

        for word in words:
            matched = self.match_word(word, score_cutoff=80)
            if matched != word:
                category = self.get_category(matched)
                if category and matched not in entities[category]:
                    entities[category].append(matched)

        return {k: v for k, v in entities.items() if v}


vocabulary_matcher = VocabularyMatcher()