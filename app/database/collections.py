from motor.motor_asyncio import AsyncIOMotorCollection

from app.database.mongodb import mongodb


class Collections:
    """
    MongoDB collections with tenant-aware access.
    All tenant-specific data is accessed through these collections.
    """

    @property
    def tenants(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["tenants"]

    @property
    def products(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["products"]

    @property
    def customers(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["customers"]

    @property
    def conversations(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["conversations"]

    @property
    def messages(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["messages"]

    @property
    def orders(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["orders"]

    @property
    def analytics(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["analytics"]


collections = Collections()