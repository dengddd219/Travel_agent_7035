from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any

import requests

from config import Settings


AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
AMAP_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"

EXCLUDED_CANDIDATE_KEYWORDS = {
    "酒店",
    "宾馆",
    "民宿",
    "公寓",
    "地名",
    "写字楼",
    "停车场",
    "地铁站",
    "公交站",
}


def _haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> int:
    lat1, lon1 = a
    lat2, lon2 = b
    radius = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return int(2 * radius * asin(sqrt(value)))


def _extract_coords(location: str) -> tuple[float, float] | None:
    if "," not in location:
        return None
    try:
        lon_text, lat_text = location.split(",", 1)
        return float(lat_text), float(lon_text)
    except Exception:
        return None


def _coord_text(item: dict[str, Any]) -> str:
    lat = float(item["lat"])
    lon = float(item["lon"])
    return f"{lon:.6f},{lat:.6f}"


def _matches_city(item: dict[str, Any], city_bias: str) -> bool:
    if not city_bias:
        return True
    city_text = city_bias.strip().lower()
    haystack = " ".join(
        str(item.get(field, "")).strip().lower()
        for field in ("city", "cityname", "pname", "district", "adname", "formatted_address")
    )
    return city_text in haystack


def _is_excluded_candidate(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(item.get("name", "")),
            str(item.get("type", "")),
            str(item.get("biz_type", "")),
        ]
    )
    return any(keyword in haystack for keyword in EXCLUDED_CANDIDATE_KEYWORDS)


def resolve_location(
    query: str,
    settings: Settings | None = None,
    city_bias: str | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    if not query.strip():
        raise ValueError("Location query cannot be empty.")

    if not settings.has_amap_key:
        return {
            "name": query.strip(),
            "address": query.strip(),
            "city": settings.default_city,
            "district": settings.default_city,
            "lat": 0.0,
            "lon": 0.0,
            "source": "fallback",
        }

    city_bias = (city_bias or settings.default_city).strip()
    params = {"key": settings.amap_api_key, "address": query.strip(), "city": city_bias}
    response = requests.get(AMAP_GEOCODE_URL, params=params, timeout=settings.request_timeout_s)
    response.raise_for_status()
    payload = response.json()
    geocodes = payload.get("geocodes") or []
    filtered_geocodes = [item for item in geocodes if _matches_city(item, city_bias)]
    if filtered_geocodes or geocodes:
        item = (filtered_geocodes or geocodes)[0]
        coords = _extract_coords(item.get("location", ""))
        lat, lon = coords or (0.0, 0.0)
        return {
            "name": query.strip(),
            "address": item.get("formatted_address", query.strip()),
            "city": item.get("city") or settings.default_city,
            "district": item.get("district") or item.get("city") or settings.default_city,
            "lat": lat,
            "lon": lon,
            "adcode": item.get("adcode", ""),
            "source": "amap_geocode",
        }

    params = {
        "key": settings.amap_api_key,
        "keywords": query.strip(),
        "city": city_bias,
        "offset": 3,
        "page": 1,
        "extensions": "all",
    }
    response = requests.get(AMAP_PLACE_TEXT_URL, params=params, timeout=settings.request_timeout_s)
    response.raise_for_status()
    payload = response.json()
    pois = payload.get("pois") or []
    pois = [item for item in pois if _matches_city(item, city_bias)] or pois
    if not pois:
        raise ValueError(f"No location result found for '{query}'.")

    item = pois[0]
    coords = _extract_coords(item.get("location", ""))
    lat, lon = coords or (0.0, 0.0)
    return {
        "name": item.get("name", query.strip()),
        "address": item.get("address", query.strip()),
        "city": item.get("cityname") or settings.default_city,
        "district": item.get("adname") or item.get("pname") or settings.default_city,
        "lat": lat,
        "lon": lon,
        "adcode": item.get("adcode", ""),
        "source": "amap_place_text",
    }


def retrieve_candidates(
    query: str,
    city: str,
    current_location: dict[str, Any] | None = None,
    settings: Settings | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    settings = settings or Settings.from_env()
    if not settings.has_amap_key:
        return []

    params = {
        "key": settings.amap_api_key,
        "keywords": query.strip(),
        "city": city.strip() or settings.default_city,
        "offset": max(1, min(limit, 10)),
        "page": 1,
        "extensions": "all",
    }
    response = requests.get(AMAP_PLACE_TEXT_URL, params=params, timeout=settings.request_timeout_s)
    response.raise_for_status()
    payload = response.json()
    pois = payload.get("pois") or []
    current_coords = None
    if current_location and current_location.get("lat") and current_location.get("lon"):
        current_coords = (float(current_location["lat"]), float(current_location["lon"]))

    results: list[dict[str, Any]] = []
    for item in pois:
        if _is_excluded_candidate(item):
            continue
        coords = _extract_coords(item.get("location", ""))
        lat, lon = coords or (0.0, 0.0)
        distance_m = None
        if current_coords and lat and lon:
            distance_m = _haversine_meters(current_coords, (lat, lon))
        biz_ext = item.get("biz_ext") or {}
        rating = biz_ext.get("rating")
        try:
            rating = float(rating) if rating else None
        except Exception:
            rating = None
        price_level = biz_ext.get("cost") or item.get("cost")
        try:
            cost_value = float(price_level) if price_level else None
        except Exception:
            cost_value = None
        results.append(
            {
                "name": item.get("name", query.strip()),
                "category": item.get("biz_type") or item.get("type", ""),
                "type_text": item.get("type", ""),
                "address": item.get("address", ""),
                "district": item.get("adname") or item.get("pname") or city,
                "lat": lat,
                "lon": lon,
                "rating": rating,
                "price_level": int(cost_value // 80) + 1 if cost_value else None,
                "estimated_cost": cost_value,
                "open_hours": biz_ext.get("open_time", ""),
                "phone": item.get("tel", ""),
                "distance_m": distance_m,
                "tags": [],
                "source": ["amap_text"],
            }
        )
        if len(results) >= limit:
            break
    return results


def get_route(
    origin: dict[str, Any],
    dest: dict[str, Any],
    mode: str = "walking",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    if not origin or not dest:
        raise ValueError("origin and dest are required")

    if not settings.has_amap_key or not all(k in origin for k in ("lat", "lon")) or not all(k in dest for k in ("lat", "lon")):
        origin_coords = (float(origin.get("lat", 0.0)), float(origin.get("lon", 0.0)))
        dest_coords = (float(dest.get("lat", 0.0)), float(dest.get("lon", 0.0)))
        direct = _haversine_meters(origin_coords, dest_coords) if all(origin_coords) and all(dest_coords) else 0
        divisor = 75 if mode == "walking" else 380
        return {
            "mode": mode,
            "distance_m": direct,
            "duration_min": max(1, round(direct / divisor)) if direct else 0,
            "instruction": "Fallback route estimate.",
            "provider": "fallback",
        }

    endpoint = AMAP_WALKING_URL if mode == "walking" else AMAP_DRIVING_URL
    params = {
        "key": settings.amap_api_key,
        "origin": _coord_text(origin),
        "destination": _coord_text(dest),
    }
    if mode != "walking":
        params["extensions"] = "base"

    response = requests.get(endpoint, params=params, timeout=settings.request_timeout_s)
    response.raise_for_status()
    payload = response.json()
    paths = ((payload.get("route") or {}).get("paths") or [])
    if not paths:
        raise ValueError("No route path returned from Amap.")

    path = paths[0]
    steps = path.get("steps") or []
    instruction = ""
    if steps:
        first_instruction = steps[0].get("instruction", "").strip()
        last_instruction = steps[-1].get("instruction", "").strip()
        instruction = " -> ".join(part for part in [first_instruction, last_instruction] if part)

    return {
        "mode": mode,
        "distance_m": int(float(path.get("distance", 0) or 0)),
        "duration_min": max(1, round(float(path.get("duration", 0) or 0) / 60)),
        "instruction": instruction or "Amap route result.",
        "provider": "amap",
    }
