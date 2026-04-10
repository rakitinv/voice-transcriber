"""
Top-level API router.

All API endpoints are registered here.
"""

from fastapi import APIRouter

from . import auth, conversations, search, upload, websocket

api_router = APIRouter(prefix="/api")

# Register sub-routers
api_router.include_router(auth.router)
api_router.include_router(conversations.router)
api_router.include_router(upload.router)
api_router.include_router(search.router)
api_router.include_router(websocket.router)

