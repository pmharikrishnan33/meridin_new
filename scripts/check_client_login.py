import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.mongodb import mongodb
from app.database.collections import collections


async def main():
    await mongodb.connect()

    database = mongodb.get_database()

    print("\nDATABASE:", database.name)
    print("CLIENT COLLECTION:", collections.clients.name)

    count = await collections.clients.count_documents({})

    print("CLIENT COUNT:", count)

    clients = await collections.clients.find(
        {},
        {
            "dashboard_email": 1,
            "business_name": 1,
            "tenant_id": 1,
            "is_active": 1,
        },
    ).to_list(None)

    print("\nCLIENT DOCUMENTS:")

    for client in clients:
        print(client)


asyncio.run(main())