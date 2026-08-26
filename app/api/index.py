"""
Vercel serverless entrypoint for the Meridin FastAPI application.

Vercel imports this module and uses the exported ASGI ``app`` object
as the Python Function handler.
"""

from app.main import app

__all__ = ["app"]