from dataclasses import dataclass

from app.ml.normalizer import normalizer
from app.ml.vocabulary_matcher import vocabulary_matcher
from app.utils.logger import logger


@dataclass
class PreprocessedText:
    """
    Result of text preprocessing.
    """
    original: str
    normalized: str
    vocabulary_matched: str
    entities: dict


class TextPreprocessor:
    """
    Complete text preprocessing pipeline:
    1. Normalize (expand abbreviations, fix common typos)
    2. Vocabulary matching (fuzzy match to known words)
    3. Entity extraction via vocabulary
    """

    def __init__(self):
        self._initialized = False

    def initialize(self) -> None:
        """
        Initialize preprocessor components.
        """
        if self._initialized:
            return

        normalizer.load()
        vocabulary_matcher.load()
        self._initialized = True

        logger.info("Text preprocessor initialized.")

    def process(self, text: str) -> PreprocessedText:
        """
        Full preprocessing pipeline.
        """

        if not self._initialized:
            self.initialize()

        # Step 1: Normalize (lowercase, expand abbreviations)
        normalized = normalizer.normalize(text)

        # Step 2: Vocabulary matching (fuzzy match to known words)
        vocab_matched = vocabulary_matcher.process(normalized)

        # Step 3: Extract entities via vocabulary
        entities = vocabulary_matcher.extract_entities_by_vocab(vocab_matched)

        logger.debug(
            f"Preprocessed: '{text}' -> normalized: '{normalized}' "
            f"-> vocab_matched: '{vocab_matched}' -> entities: {entities}"
        )

        return PreprocessedText(
            original=text,
            normalized=normalized,
            vocabulary_matched=vocab_matched,
            entities=entities
        )


preprocessor = TextPreprocessor()