from __future__ import annotations

import httpx
import requests
from typing import Optional, Tuple

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

REQUEST_HEADERS = {
    "User-Agent": "newvoice-realestate-agent/1.0 (contact: local-dev)",
}


def geocode_location_sync(location: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    if not location or not location.strip():
        return None, None, None

    params = {"q": location, "format": "jsonv2", "limit": 1}

    try:
        response = requests.get(
            NOMINATIM_URL,
            params=params,
            headers=REQUEST_HEADERS,
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()

        if not data:
            return None, None, None

        top = data[0]
        lat = float(top["lat"])
        lon = float(top["lon"])
        display_name = top.get("display_name", location)
        return lat, lon, display_name

    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None, None, None


async def geocode_location_async(location: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    if not location or not location.strip():
        return None, None, None

    params = {"q": location, "format": "jsonv2", "limit": 1}

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(
                NOMINATIM_URL,
                params=params,
                headers=REQUEST_HEADERS,
            )
            response.raise_for_status()
            data = response.json()

        if not data:
            return None, None, None

        top = data[0]
        lat = float(top["lat"])
        lon = float(top["lon"])
        display_name = top.get("display_name", location)
        return lat, lon, display_name

    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None, None, None