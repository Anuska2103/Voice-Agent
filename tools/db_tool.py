"""
tools/db_tool.py

Property-search tool.  This module is a DUMB EXECUTOR — it receives a
structured query dict that the LLM has already assembled and runs it
against MongoDB.  There is no NLP, regex, or keyword logic here.

Flow
────
LLM (classify + extract) → orchestrator builds `query_dict`
                         → search_properties(query_dict, ...) called
                         → MongoDB find() executed
                         → raw results normalised and returned
"""
from __future__ import annotations

from typing import Any
from logger import get_logger

from tools.db_connection import get_property_collection

LOGGER = get_logger(__name__)


async def search_properties(
    query_dict: dict[str, Any],
    uri: str,
    db_name: str,
    collection_name: str,
    limit: int = 5,
) -> dict[str, Any]:
   
    try:
        collection = await get_property_collection(uri, db_name, collection_name)

        LOGGER.info("DB tool executing query: %s", query_dict)

        cursor = collection.find(query_dict).limit(limit)
        raw = await cursor.to_list(length=limit)

        properties = [
            {
                "title": f"{p.get('bhk') or ''} BHK {p.get('type', 'property')}".strip(),
                "area": p.get("area", "Location N/A"),
                "price": p.get("price", "Price N/A"),
                "bhk": p.get("bhk", "N/A"),
                "type": p.get("type", "N/A"),
                "sqft": p.get("sqft", "N/A"),
                "furnishing": p.get("furnishing", "N/A"),
                "listingType": p.get("listingType", "N/A"),
                "availability": p.get("availability", "N/A"),
                "contact": {
                    "name": (p.get("contact") or {}).get("name", "N/A"),
                    "phone": (p.get("contact") or {}).get("phone", "N/A"),
                },
            }
            for p in raw
        ]

        LOGGER.info("DB tool returned %d properties", len(properties))
        return {
            "properties": properties,
            "count": len(properties),
            "query_used": query_dict,
        }

    except Exception as exc:
        LOGGER.exception("DB tool error: %s", exc)
        return {
            "properties": [],
            "count": 0,
            "query_used": query_dict,
            "error": str(exc),
        }