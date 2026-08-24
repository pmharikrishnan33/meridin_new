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
        Load all ML models.

        Missing or invalid model files do not crash the
        application. The individual ML components can
        fall back to their fallback logic.

        The log message accurately reports which models
        were loaded and which are missing.
        """

        logger.info(
            "Loading ML models..."
        )

        self._intent_model = (
            self._load_model(
                settings.INTENT_MODEL
            )
        )

        self._intent_vectorizer = (
            self._load_model(
                settings.INTENT_VECTORIZER
            )
        )

        self._entity_model = (
            self._load_model(
                settings.ENTITY_MODEL
            )
        )

        self._entity_vectorizer = (
            self._load_model(
                settings.ENTITY_VECTORIZER
            )
        )

        self._loaded = True

        models = {
            "intent_model": (
                self._intent_model
            ),

            "intent_vectorizer": (
                self._intent_vectorizer
            ),

            "entity_model": (
                self._entity_model
            ),

            "entity_vectorizer": (
                self._entity_vectorizer
            ),
        }

        missing = [
            name
            for name, model in models.items()
            if model is None
        ]

        if missing:

            logger.warning(
                "ML pipeline loaded with missing "
                "models: %s",
                ", ".join(missing),
            )

        else:

            logger.info(
                "All ML models loaded successfully."
            )

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

            # --- Compatibility fix for sklearn version mismatch ---
            # Models trained with sklearn 1.9.0+ (where the multi_class
            # parameter was removed/renamed) can fail at runtime on
            # sklearn <= 1.6.1 because predict_proba() still references
            # self.multi_class.  If the attribute is missing, restore it
            # so predict_proba works across versions.
            if hasattr(model, "predict_proba") and not hasattr(model, "multi_class"):
                model.multi_class = "multinomial"
                logger.info(
                    f"Restored multi_class='multinomial' on {model_path.name} "
                    f"(sklearn version compatibility fix)"
                )
            # -------------------------------------------------------

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
        return bool(self._loaded)


model_loader = ModelLoader()