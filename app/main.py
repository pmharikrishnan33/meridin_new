from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo.errors import ConnectionFailure

from app.api.dashboard_admin import router as dashboard_admin_router
from app.api.dashboard_auth import router as dashboard_auth_router
from app.api.dashboard_client import router as dashboard_client_router
from app.api.webhook import router as message_router
from app.core.config import settings
from app.database.indexes import ensure_indexes
from app.database.mongodb import mongodb
from app.database.redis_cache import redis_cache
from app.ml.loader import model_loader
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown lifecycle.

    ML model loading is synchronous disk/serialization work, so it is
    executed in a worker thread instead of blocking the FastAPI event loop.
    """

    logger.info(
        "%s starting...",
        settings.APP_NAME,
    )

    # ---------------------------------------------------------
    # ML MODELS
    # ---------------------------------------------------------

    try:
        await asyncio.to_thread(
            model_loader.load_all
        )

    except Exception:
        logger.exception(
            "ML model initialization failed."
        )

    # ---------------------------------------------------------
    # MONGODB
    # ---------------------------------------------------------

    try:
        await mongodb.connect()

        if mongodb.is_connected:
            await ensure_indexes()

    except ConnectionFailure:

        if settings.MONGODB_REQUIRED:
            raise

        logger.warning(
            "MongoDB is unavailable; "
            "running without MongoDB."
        )

    except Exception:

        if settings.MONGODB_REQUIRED:
            raise

        logger.exception(
            "MongoDB initialization failed."
        )

    # ---------------------------------------------------------
    # REDIS
    # ---------------------------------------------------------

    try:
        await redis_cache.connect()

    except Exception:
        logger.exception(
            "Redis initialization failed."
        )

    logger.info(
        "%s started successfully.",
        settings.APP_NAME,
    )

    yield

    # ---------------------------------------------------------
    # SHUTDOWN
    # ---------------------------------------------------------

    logger.info(
        "%s shutting down...",
        settings.APP_NAME,
    )

    try:
        await mongodb.disconnect()

    except Exception:
        logger.exception(
            "MongoDB shutdown failed."
        )

    try:
        await redis_cache.disconnect()

    except Exception:
        logger.exception(
            "Redis shutdown failed."
        )


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:5501",
        "http://127.0.0.1:5501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    message_router,
    prefix="/api",
)

app.include_router(
    dashboard_auth_router,
    prefix="/api",
)

app.include_router(
    dashboard_client_router,
    prefix="/api",
)

app.include_router(
    dashboard_admin_router,
    prefix="/api",
)


@app.get("/")
async def health_check():
    return {
        "status": "running",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
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
        "ml": {
            "loaded": model_loader.is_loaded(),
        },
    }