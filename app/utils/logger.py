import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings


class Logger:
    """
    Production logger for Meridin.
    Logs flow: Message received -> Intent detected -> Entity extracted ->
    Product searched -> Response sent -> Stored everything
    """

    def __init__(self):
        self.logger = logging.getLogger("meridin")

        # Prevent duplicate handlers
        if self.logger.hasHandlers():
            return

        self.logger.setLevel(settings.LOG_LEVEL)

        # Create logs directory
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(settings.LOG_LEVEL)
        console_handler.setFormatter(formatter)

        # File Handler - rotating (5MB, keep 5 backups)
        file_handler = RotatingFileHandler(
            filename=log_dir / "meridin.log",
            maxBytes=5 * 1024 * 1024,   # 5 MB
            backupCount=5,
            encoding="utf-8"
        )

        file_handler.setLevel(settings.LOG_LEVEL)
        file_handler.setFormatter(formatter)

        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def get_logger(self):
        return self.logger


logger = Logger().get_logger()