from contextlib import asynccontextmanager

from fastapi import FastAPI
from pymongo.errors import ConnectionFailure
from app.database.indexes import ensure_indexes
from app.core.config import settings
from app.utils.logger import logger
from app.database.mongodb import mongodb
from app.database.redis_cache import redis_cache
from app.api.webhook import router as message_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown events.
    """

    # Startup
    logger.info(f"{settings.APP_NAME} starting...")

    try:
        await mongodb.connect()
        await ensure_indexes()
    except ConnectionFailure:
        if settings.MONGODB_REQUIRED:
            raise
        logger.warning(
            "MongoDB is unavailable; running in stateless ML-only mode."
        )

    await redis_cache.connect()

    logger.info(f"{settings.APP_NAME} started successfully.")

    yield

    # Shutdown
    logger.info(f"{settings.APP_NAME} shutting down...")

    await mongodb.disconnect()
    await redis_cache.disconnect()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan
)

app.include_router(message_router, prefix="/api")


@app.get("/")
async def health_check():

    return {
        "status": "running",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


@app.get("/health")
async def health():

    mongodb_ok = mongodb.is_connected

    redis_ok = redis_cache.is_connected

    return {
        "status": (
            "healthy"
            if mongodb_ok
            else "degraded"
        ),
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "dependencies": {
            "mongodb": mongodb_ok,
            "redis": redis_ok,
        },
    }