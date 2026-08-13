from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure

from app.core.config import settings
from app.utils.logger import logger


class MongoDB:
    """
    Async MongoDB connection manager using Motor.
    Creates a single AsyncIOMotorClient for the entire application.
    """

    def __init__(self):
        self.client: AsyncIOMotorClient | None = None
        self.db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        """
        Connect to MongoDB asynchronously.
        """

        try:
            self.client = AsyncIOMotorClient(
                settings.MONGODB_URI,
                serverSelectionTimeoutMS=5000
            )

            # Verify the connection
            await self.client.admin.command("ping")

            self.db = self.client[settings.DATABASE_NAME]

            logger.info("MongoDB connected successfully (async).")

        except ConnectionFailure as e:
            logger.exception(f"MongoDB connection failed: {e}")
            raise

    async def disconnect(self) -> None:
        """
        Close MongoDB connection.
        """

        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            logger.info("MongoDB connection closed.")

    @property
    def is_connected(self) -> bool:
        """Whether a verified database connection is currently available."""
        return self.db is not None

    def get_database(self) -> AsyncIOMotorDatabase:
        """
        Return database instance.
        """

        if self.db is None:
            raise RuntimeError(
                "MongoDB has not been initialized. Call connect() first."
            )

        return self.db


mongodb = MongoDB()
