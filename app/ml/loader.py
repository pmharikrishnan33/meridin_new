from pathlib import Path
from typing import Any, Optional

import joblib

from app.core.config import settings
from app.utils.logger import logger


class ModelLoader:
    """
    Loads ML models once at startup.
    Models are loaded lazily on first access.
    """

    def __init__(self):
        self._intent_model: Optional[Any] = None
        self._intent_vectorizer: Optional[Any] = None
        self._entity_model: Optional[Any] = None
        self._entity_vectorizer: Optional[Any] = None
        self._loaded = False

    def load_all(self) -> None:
        """
        Load all models at startup.
        """

        logger.info("Loading ML models...")

        self._intent_model = self._load_model(settings.INTENT_MODEL)
        self._intent_vectorizer = self._load_model(settings.INTENT_VECTORIZER)
        self._entity_model = self._load_model(settings.ENTITY_MODEL)
        self._entity_vectorizer = self._load_model(settings.ENTITY_VECTORIZER)

        self._loaded = True

        logger.info("All ML models loaded successfully.")

    def _load_model(self, path: str) -> Optional[Any]:
        """
        Load a single model file.
        """

        model_path = Path(path)

        if not model_path.exists():
            logger.warning(f"Model file not found: {model_path}")
            return None

        try:
            model = joblib.load(model_path)
            logger.info(f"Loaded model: {model_path.name}")
            return model
        except Exception as e:
            logger.exception(f"Failed to load model {model_path}: {e}")
            return None

    # Lazy loading properties
    @property
    def intent_model(self) -> Optional[Any]:
        if not self._loaded:
            self.load_all()
        return self._intent_model

    @property
    def intent_vectorizer(self) -> Optional[Any]:
        if not self._loaded:
            self.load_all()
        return self._intent_vectorizer

    @property
    def entity_model(self) -> Optional[Any]:
        if not self._loaded:
            self.load_all()
        return self._entity_model

    @property
    def entity_vectorizer(self) -> Optional[Any]:
        if not self._loaded:
            self.load_all()
        return self._entity_vectorizer

    def is_loaded(self) -> bool:
        return self._loaded


model_loader = ModelLoader()