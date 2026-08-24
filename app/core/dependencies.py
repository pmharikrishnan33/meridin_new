from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.mongodb import mongodb


def get_database() -> AsyncIOMotorDatabase:
    """
    Return the MongoDB database instance.
    """
    return mongodb.get_database()