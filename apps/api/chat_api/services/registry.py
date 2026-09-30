"""Read the document registry the ingestion pipeline maintains."""

import asyncio
import time
from typing import Any

import boto3

_CACHE_SECONDS = 10.0
_cache: tuple[float, list[dict[str, Any]]] | None = None


def _scan(table_name: str) -> list[dict[str, Any]]:
    table = boto3.resource("dynamodb").Table(table_name)
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        if not page.get("LastEvaluatedKey"):
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


async def list_documents(table_name: str) -> list[dict[str, Any]]:
    """Return every registry item, cached briefly to spare DynamoDB on repeated calls.

    Args:
        table_name: DynamoDB registry table.

    Returns:
        Registry items sorted by display name.
    """
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] > _CACHE_SECONDS:
        items = await asyncio.to_thread(_scan, table_name)
        _cache = (
            now,
            sorted(items, key=lambda item: str(item.get("name", "")).lower()),
        )
    return _cache[1]


def clear_cache() -> None:
    """Drop the cached listing (used by tests)."""
    global _cache
    _cache = None


async def find_ready(table_name: str, knowledge_base_id: str) -> dict[str, Any] | None:
    """Return the ``READY`` document backed by a Knowledge Base id, or ``None``."""
    for item in await list_documents(table_name):
        if item.get("kb_id") == knowledge_base_id and item.get("status") == "READY":
            return item
    return None
