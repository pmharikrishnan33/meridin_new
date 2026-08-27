import re

from motor.motor_asyncio import AsyncIOMotorCollection

from app.database.mongodb import mongodb


_SAFE_TENANT_ID = re.compile(
    r"^[A-Za-z0-9_-]{1,64}$"
)


class Collections:

    @property
    def clients(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["clients"]

    def products(
        self,
        tenant_id: str,
    ) -> AsyncIOMotorCollection:

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if not _SAFE_TENANT_ID.fullmatch(
            tenant_id
        ):
            raise ValueError(
                "Invalid tenant_id format"
            )

        return mongodb.get_database()[
            f"inventory.{tenant_id}"
        ]

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
    def intents(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["intents"]

    @property
    def keywords(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["keywords"]

    @property
    def learned_keywords(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["learned_keywords"]

    @property
    def learned_responses(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["learned_responses"]

    @property
    def templates(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["templates"]

    @property
    def inventory_metadata(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["inventory_metadata"]

    @property
    def ai_model_usage(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["ai_model_usage"]

    @property
    def meta_conversation_usage(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["meta_conversation_usage"]

    @property
    def cache(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["cache"]

    @property
    def rate_limits(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["rate_limits"]

    @property
    def collections(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["collections"]


collections = Collections()