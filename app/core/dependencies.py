from pymongo.database import Database

from app.database.mongodb import mongodb


def get_database() -> Database:
    """
    Return the MongoDB database instance.
    """
    return mongodb.get_database()