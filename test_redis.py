import asyncio

from app.database.redis_cache import redis_cache


async def main():
    await redis_cache.connect()

    print("CONNECTED:", redis_cache.is_connected)

    result = await redis_cache.set(
        "meridin_test",
        "ok",
        ttl=60,
    )

    print("SET:", result)

    value = await redis_cache.get("meridin_test")

    print("GET:", value)


asyncio.run(main())