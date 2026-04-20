from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from math import radians, sin, cos, sqrt, atan2
from typing import Dict, List, Optional

import requests

from tools.geocoding import geocode_location_sync


OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

DEFAULT_RADIUS_METERS = 2000

REQUEST_HEADERS = {
    "User-Agent": "newvoice-realestate-agent/1.0 (contact: local-dev)",
}

ALLOWED_AMENITIES = {"hospital", "school", "bank", "metro", "college"}

GENERIC_AMENITY_NOT_FOUND_REPLY = (
    "sorry umm i couldn't find what you asked for, umm i am really sorry, anything else i can help with?"
)

session_memory: Dict[str, Optional[object]] = {
    "location": None,
    "lat": None,
    "lon": None,
}


@dataclass
class Amenity:
    name: str
    amenity_type: str
    distance_km: float
    lat: float
    lon: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "amenity_type": self.amenity_type,
            "distance_km": self.distance_km,
            "lat": self.lat,
            "lon": self.lon,
        }


@dataclass
class AmenitiesReport:
    location_name: str
    lat: float
    lon: float
    amenity_type: str
    amenities: List[Amenity] = field(default_factory=list)
    formatted: str = ""

    def to_dict(self) -> dict:
        return {
            "location_name": self.location_name,
            "lat": self.lat,
            "lon": self.lon,
            "amenity_type": self.amenity_type,
            "amenities": [a.to_dict() for a in self.amenities],
            "formatted": self.formatted,
        }


def haversine(lat1, lon1, lat2, lon2):
    radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return radius_km * 2 * atan2(sqrt(a), sqrt(1 - a))


def fetch_amenities(lat, lon, amenity_type="school", radius_meters=DEFAULT_RADIUS_METERS):
    amenity_type = normalize_amenity_type(amenity_type)
    print(f"[amenities] fetch_amenities: amenity_type={amenity_type}, lat={lat}, lon={lon}, radius={radius_meters}m")

    query = f"""
    [out:json][timeout:12];
    (
      node["amenity"="{amenity_type}"](around:{int(radius_meters)},{lat},{lon});
      way["amenity"="{amenity_type}"](around:{int(radius_meters)},{lat},{lon});
    );
    out center 30;
    """

    retries = 2
    backoff_sec = 0.8
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            print(f"[amenities] fetch_amenities: overpass attempt={attempt}")
            response = requests.post(
                OVERPASS_API_URL,
                data=query,
                headers=REQUEST_HEADERS,
                timeout=12,
            )

            if response.status_code == 504:
                raise requests.HTTPError("504 Gateway Timeout", response=response)

            response.raise_for_status()
            payload = response.json()
            raw_elements = payload.get("elements", [])

            parsed = []
            seen = set()
            for elem in raw_elements:
                tags = elem.get("tags", {}) or {}
                name = tags.get("name")
                if not name:
                    continue

                elem_lat = elem.get("lat")
                elem_lon = elem.get("lon")
                if elem_lat is None or elem_lon is None:
                    center = elem.get("center", {})
                    elem_lat = center.get("lat")
                    elem_lon = center.get("lon")

                if elem_lat is None or elem_lon is None:
                    continue

                key = (name.lower().strip(), round(float(elem_lat), 6), round(float(elem_lon), 6))
                if key in seen:
                    continue
                seen.add(key)

                distance_km = haversine(float(lat), float(lon), float(elem_lat), float(elem_lon))
                parsed.append({
                    "name": name,
                    "type": amenity_type,
                    "lat": float(elem_lat),
                    "lon": float(elem_lon),
                    "distance_km": round(distance_km, 3),
                })

            parsed.sort(key=lambda item: item["distance_km"])
            top5 = parsed[:5]
            print(f"[amenities] fetch_amenities: parsed={len(parsed)}, returning={len(top5)}")
            return top5

        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            last_error = exc
            should_retry = attempt < retries
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            print(f"[amenities] fetch_amenities: error={exc}, status={status_code}, retry={should_retry}")
            if not should_retry:
                break
            time.sleep(backoff_sec * attempt)
        except ValueError as exc:
            last_error = exc
            print(f"[amenities] fetch_amenities: invalid JSON={exc}")
            break

    raise RuntimeError(f"Overpass API failed after retries: {last_error}")


def build_amenity_fallback_reply(location_name: Optional[str], amenity_type: str) -> str:
    place = (location_name or "that area").strip() or "that area"
    kind = (amenity_type or "place").strip() or "place"
    return (
        f"sorry umm i couldn't find any {kind} near {place}, "
        "umm i am really sorry, anything else i can help with?"
    )


def format_amenities_human(location_name: str, amenity_type: str, amenities: List[dict]) -> str:
    if not amenities:
        return build_amenity_fallback_reply(location_name, amenity_type)
    lines = [f"Top nearby {amenity_type}s around {location_name}:"]
    for idx, item in enumerate(amenities, start=1):
        lines.append(f"{idx}. {item['name']} ({item['distance_km']} km)")
    return " ".join(lines)


def normalize_amenity_type(amenity_type: str) -> str:
    raw = (amenity_type or "school").strip().lower()
    if raw in {"hospital", "hospitals"}:
        return "hospital"
    if raw in {"school", "schools"}:
        return "school"
    if raw in {"college", "colleges", "clg", "colg"}:
        return "college"
    if raw in {"bank", "banks", "atm", "atms"}:
        return "bank"
    if raw in {"metro", "subway", "station", "metro station"}:
        return "metro"
    return raw if raw in ALLOWED_AMENITIES else "school"


def _extract_location_phrase(user_input: str) -> Optional[str]:
    text = (user_input or "").strip()
    if not text:
        return None
    pattern = r"\b(?:in|near|around|at)\s+([a-zA-Z0-9\-\s,]+)$"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip(" .,")
        return candidate if candidate else None
    return None


def _extract_amenity_type(user_input: str) -> str:
    text = (user_input or "").lower()
    if "hospital" in text:
        return "hospital"
    if "school" in text:
        return "school"
    if "college" in text or "clg" in text or "colg" in text:
        return "college"
    if "bank" in text or "atm" in text:
        return "bank"
    if "metro" in text or "station" in text or "subway" in text:
        return "metro"
    return "school"


def handle_user_query(user_input: str, context_location: Optional[str] = None):
    print(f"[amenities] handle_user_query: input='{user_input}'")
    amenity_type = _extract_amenity_type(user_input)
    location_in_query = _extract_location_phrase(user_input)

    location_name = None
    lat = None
    lon = None

    if location_in_query:
        print(f"[amenities] handle_user_query: new location detected='{location_in_query}'")
        lat, lon, resolved_name = geocode_location_sync(location_in_query)
        if lat is not None and lon is not None:
            session_memory["location"] = resolved_name or location_in_query
            session_memory["lat"] = lat
            session_memory["lon"] = lon
            location_name = session_memory["location"]
        else:
            print("[amenities] handle_user_query: geocoding failed, will fallback to memory")

    if (lat is None or lon is None) and context_location:
        print(f"[amenities] handle_user_query: trying context location='{context_location}'")
        ctx_lat, ctx_lon, ctx_name = geocode_location_sync(context_location)
        if ctx_lat is not None and ctx_lon is not None:
            session_memory["location"] = ctx_name or context_location
            session_memory["lat"] = ctx_lat
            session_memory["lon"] = ctx_lon
            location_name = session_memory["location"]
            lat = ctx_lat
            lon = ctx_lon

    if lat is None or lon is None:
        if session_memory.get("lat") is not None and session_memory.get("lon") is not None:
            location_name = str(session_memory.get("location") or "Stored Location")
            lat = float(session_memory["lat"])
            lon = float(session_memory["lon"])
            print(f"[amenities] handle_user_query: using session location='{location_name}'")
        else:
            print("[amenities] handle_user_query: no session memory and no location in query, cannot resolve location")
            return {
                "location": None,
                "lat": None,
                "lon": None,
                "amenity_type": amenity_type,
                "results": [],
                "formatted": GENERIC_AMENITY_NOT_FOUND_REPLY,
            }

    try:
        if amenity_type == "metro":
            metro_results = _fetch_metro_stations(lat=lat, lon=lon, radius_meters=DEFAULT_RADIUS_METERS)
            formatted = format_amenities_human(location_name, "metro station", metro_results)
            return {
                "location": location_name,
                "lat": lat,
                "lon": lon,
                "amenity_type": "metro",
                "results": metro_results,
                "formatted": formatted,
            }

        amenities = fetch_amenities(lat=lat, lon=lon, amenity_type=amenity_type, radius_meters=DEFAULT_RADIUS_METERS)
        formatted = format_amenities_human(location_name, amenity_type, amenities)

        return {
            "location": location_name,
            "lat": lat,
            "lon": lon,
            "amenity_type": amenity_type,
            "results": amenities,
            "formatted": formatted,
        }
    except Exception as exc:
        print(f"[amenities] handle_user_query: fetch failed error={exc}")
        return {
            "location": location_name,
            "lat": lat,
            "lon": lon,
            "amenity_type": amenity_type,
            "results": [],
            "formatted": build_amenity_fallback_reply(location_name, amenity_type),
            "error": str(exc),
        }


def _fetch_metro_stations(lat: float, lon: float, radius_meters: int) -> List[dict]:
    print(f"[amenities] _fetch_metro_stations: lat={lat}, lon={lon}, radius={radius_meters}")
    query = f"""
    [out:json][timeout:12];
    (
      node["railway"="station"]["station"~"subway|metro"](around:{int(radius_meters)},{lat},{lon});
      way["railway"="station"]["station"~"subway|metro"](around:{int(radius_meters)},{lat},{lon});
    );
    out center 30;
    """
    response = requests.post(OVERPASS_API_URL, data=query, headers=REQUEST_HEADERS, timeout=12)
    response.raise_for_status()
    payload = response.json()
    rows = []
    for elem in payload.get("elements", []):
        tags = elem.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        elem_lat = elem.get("lat") or (elem.get("center") or {}).get("lat")
        elem_lon = elem.get("lon") or (elem.get("center") or {}).get("lon")
        if elem_lat is None or elem_lon is None:
            continue
        rows.append({
            "name": name,
            "type": "metro",
            "lat": float(elem_lat),
            "lon": float(elem_lon),
            "distance_km": round(haversine(lat, lon, float(elem_lat), float(elem_lon)), 3),
        })
    rows.sort(key=lambda item: item["distance_km"])
    return rows[:5]


async def fetch_amenities_report(
    amenity_types: List[str],
    lat: float,
    lon: float,
    radius_km: int = 2,
) -> AmenitiesReport:
    radius_meters = max(1000, min(2000, int(radius_km * 1000)))
    all_rows: List[dict] = []

    for amenity_type in amenity_types:
        normalized = normalize_amenity_type(amenity_type)
        if normalized == "metro":
            rows = await asyncio.to_thread(_fetch_metro_stations, lat, lon, radius_meters)
        else:
            rows = await asyncio.to_thread(fetch_amenities, lat, lon, normalized, radius_meters)
        all_rows.extend(rows)

    all_rows.sort(key=lambda item: item["distance_km"])
    final_rows = all_rows[:5]

    amenities = [
        Amenity(
            name=row["name"],
            amenity_type=row["type"],
            distance_km=row["distance_km"],
            lat=row["lat"],
            lon=row["lon"],
        )
        for row in final_rows
    ]

    formatted = format_amenities_human("the selected area", "place", final_rows)
    return AmenitiesReport(
        location_name="the selected area",
        lat=lat,
        lon=lon,
        amenity_type="mixed",
        amenities=amenities,
        formatted=formatted,
    )


def format_amenities_for_voice(report: AmenitiesReport, max_results: int = 5) -> str:
    rows = [a.to_dict() for a in report.amenities[:max_results]]
    return format_amenities_human(
        location_name=report.location_name,
        amenity_type=report.amenity_type,
        amenities=rows,
    )