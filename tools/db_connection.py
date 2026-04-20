"""
tools/db_connection.py
Lightweight MongoDB async connection helper — lives inside tools/ so all
tool modules can import it without touching the project root.
"""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from logger import get_logger

LOGGER = get_logger(__name__)

_client: AsyncIOMotorClient | None = None
_collection: AsyncIOMotorCollection | None = None


async def get_property_collection(
    uri: str,
    db_name: str,
    collection_name: str,
) -> AsyncIOMotorCollection:
    """
    Return a cached Motor collection.  The connection is created once and
    reused for the lifetime of the process.
    """
    global _client, _collection

    if _collection is not None:
        LOGGER.debug("Reusing cached Mongo collection: %s.%s", db_name, collection_name)
        return _collection

    LOGGER.info("Initializing MongoDB client for %s.%s", db_name, collection_name)
    _client = AsyncIOMotorClient(uri)
    db = _client[db_name]
    _collection = db[collection_name]
    LOGGER.info("MongoDB collection ready")
    return _collection


async def close_connection() -> None:
    """Gracefully close the Motor client (call on shutdown)."""
    global _client, _collection
    if _client is not None:
        LOGGER.info("Closing MongoDB client")
        _client.close()
        _client = None
        _collection = None