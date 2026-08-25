from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Optional

import joblib

from app.core.config import settings
from app.utils.logger import logger


class ModelLoader:
    """
    Centralized ML model loader.

    Responsibilities:
    - Load ML artifacts once.
    - Support lazy loading.
    - Avoid loading the same artifact multiple times.
    - Handle missing model files safely.
    - Handle corrupted/incompatible artifacts safely.
    - Expose model/vectorizer availability.
    - Keep model loading independent from prediction logic.

    Expected artifacts:

        intent_model
        intent_vectorizer
        entity_model
        entity_vectorizer

    The loader does not perform predictions.
    """

    def __init__(self) -> None:
        self._intent_model: Optional[Any] = None
        self._intent_vectorizer: Optional[Any] = None

        self._entity_model: Optional[Any] = None
        self._entity_vectorizer: Optional[Any] = None

        self._loaded = False

        # Prevent duplicate model loading if multiple requests
        # trigger lazy loading concurrently.
        self._lock = Lock()

    # =========================================================
    # LOAD ALL
    # =========================================================

    def load_all(self) -> None:
        """
        Load all configured ML artifacts.

        Missing or invalid artifacts do not crash the application.

        Important:
        `_loaded` becomes True only after an attempted load cycle
        has completed. A missing artifact remains None and is
        reported through the availability methods.
        """

        if self._loaded:
            return

        with self._lock:

            # Another thread may have completed loading while
            # this thread was waiting for the lock.
            if self._loaded:
                return

            logger.info(
                "Loading ML models..."
            )

            self._intent_model = self._load_model(
                settings.INTENT_MODEL
            )

            self._intent_vectorizer = self._load_model(
                settings.INTENT_VECTORIZER
            )

            self._entity_model = self._load_model(
                settings.ENTITY_MODEL
            )

            self._entity_vectorizer = self._load_model(
                settings.ENTITY_VECTORIZER
            )

            self._loaded = True

            self._log_model_status()

    # =========================================================
    # SINGLE MODEL LOADING
    # =========================================================

    @staticmethod
    def _load_model(
        path: str | Path,
    ) -> Optional[Any]:
        """
        Load one serialized ML artifact.

        Returns:
            Loaded artifact when successful.
            None when the file is missing, invalid, or cannot
            be deserialized.
        """

        if path is None:
            logger.error(
                "ML model path is None."
            )
            return None

        try:
            model_path = Path(path)
        except (TypeError, ValueError) as exc:
            logger.error(
                "Invalid ML model path '%s': %s",
                path,
                exc,
            )
            return None

        if not model_path.exists():

            logger.warning(
                "ML model file not found: %s",
                model_path,
            )

            return None

        if not model_path.is_file():

            logger.warning(
                "ML model path is not a file: %s",
                model_path,
            )

            return None

        try:

            model = joblib.load(
                model_path
            )

        except Exception as exc:

            logger.exception(
                "Failed to load ML model '%s': %s",
                model_path,
                exc,
            )

            return None

        if model is None:

            logger.error(
                "ML artifact '%s' loaded as None.",
                model_path,
            )

            return None

        logger.info(
            "Loaded ML artifact: %s",
            model_path.name,
        )

        return model

    # =========================================================
    # STATUS LOGGING
    # =========================================================

    def _log_model_status(self) -> None:
        """
        Log the state of all ML artifacts after loading.
        """

        models = {
            "intent_model": self._intent_model,
            "intent_vectorizer": self._intent_vectorizer,
            "entity_model": self._entity_model,
            "entity_vectorizer": self._entity_vectorizer,
        }

        loaded = [
            name
            for name, model in models.items()
            if model is not None
        ]

        missing = [
            name
            for name, model in models.items()
            if model is None
        ]

        if loaded:
            logger.info(
                "ML artifacts loaded: %s",
                ", ".join(loaded),
            )

        if missing:
            logger.warning(
                "ML pipeline has missing artifacts: %s",
                ", ".join(missing),
            )

        if not missing:
            logger.info(
                "All ML artifacts loaded successfully."
            )

    # =========================================================
    # LAZY LOADING
    # =========================================================

    def _ensure_loaded(self) -> None:
        """
        Ensure model loading has been attempted.
        """

        if not self._loaded:
            self.load_all()

    # =========================================================
    # INTENT MODEL
    # =========================================================

    @property
    def intent_model(self) -> Optional[Any]:
        self._ensure_loaded()
        return self._intent_model

    @property
    def intent_vectorizer(self) -> Optional[Any]:
        self._ensure_loaded()
        return self._intent_vectorizer

    # =========================================================
    # ENTITY MODEL
    # =========================================================

    @property
    def entity_model(self) -> Optional[Any]:
        self._ensure_loaded()
        return self._entity_model

    @property
    def entity_vectorizer(self) -> Optional[Any]:
        self._ensure_loaded()
        return self._entity_vectorizer

    # =========================================================
    # PIPELINE AVAILABILITY
    # =========================================================

    def is_intent_pipeline_available(self) -> bool:
        """
        Return True when both intent artifacts are available.
        """

        self._ensure_loaded()

        return (
            self._intent_model is not None
            and self._intent_vectorizer is not None
        )

    def is_entity_pipeline_available(self) -> bool:
        """
        Return True when both entity artifacts are available.
        """

        self._ensure_loaded()

        return (
            self._entity_model is not None
            and self._entity_vectorizer is not None
        )

    def is_loaded(self) -> bool:
        """
        Return whether a model loading attempt has completed.
        """

        return bool(
            self._loaded
        )

    # =========================================================
    # COMPLETE STATUS
    # =========================================================

    def is_fully_loaded(self) -> bool:
        """
        Return True only when every required ML artifact exists.
        """

        self._ensure_loaded()

        return (
            self._intent_model is not None
            and self._intent_vectorizer is not None
            and self._entity_model is not None
            and self._entity_vectorizer is not None
        )

    def get_status(self) -> dict[str, bool]:
        """
        Return machine-readable ML artifact status.
        """

        self._ensure_loaded()

        return {
            "loaded": self._loaded,
            "intent_model": (
                self._intent_model is not None
            ),
            "intent_vectorizer": (
                self._intent_vectorizer is not None
            ),
            "entity_model": (
                self._entity_model is not None
            ),
            "entity_vectorizer": (
                self._entity_vectorizer is not None
            ),
            "intent_pipeline": (
                self.is_intent_pipeline_available()
            ),
            "entity_pipeline": (
                self.is_entity_pipeline_available()
            ),
            "fully_loaded": (
                self.is_fully_loaded()
            ),
        }

    # =========================================================
    # RESET
    # =========================================================

    def reset(self) -> None:
        """
        Clear loaded artifacts.

        Useful for tests and controlled model reloads.

        This does not reload the models immediately.
        The next property access will trigger lazy loading.
        """

        with self._lock:

            self._intent_model = None
            self._intent_vectorizer = None

            self._entity_model = None
            self._entity_vectorizer = None

            self._loaded = False

        logger.info(
            "ML model loader reset."
        )


model_loader = ModelLoader()