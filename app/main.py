from contextlib import asynccontextmanager

from fastapi import FastAPI
from pymongo.errors import ConnectionFailure

from app.core.config import settings
from app.utils.logger import logger
from app.database.mongodb import mongodb
from app.database.redis_cache import redis_cache
from app.api.webhook import router as message_router

from fastapi.responses import HTMLResponse
from pathlib import Path

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown events.
    """

    # Startup
    logger.info(f"{settings.APP_NAME} starting...")

    try:
        await mongodb.connect()
    except ConnectionFailure:
        if settings.MONGODB_REQUIRED:
            raise
        logger.warning("MongoDB is unavailable; running in stateless ML-only mode.")

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
async def detailed_health():

    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "mongodb": "connected" if mongodb.is_connected else "disconnected"
    }


@app.get("/super-admin", response_class=HTMLResponse)
async def serve_super_admin():
    """Serves the Super Admin dashboard."""
    # This assumes super_admin.html is saved in the root folder of your project
    html_file = Path("/home/harikrishnan/Desktop/FE/super_admin.html")
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Error: super_admin.html not found</h1>"

@app.get("/client-panel", response_class=HTMLResponse)
async def serve_client_panel():
    """Serves the Client Portal."""
    # This assumes client_panel.html is saved in the root folder of your project
    html_file = Path("/home/harikrishnan/Desktop/FE/client_panel.html")
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Error: client_panel.html not found</h1>"