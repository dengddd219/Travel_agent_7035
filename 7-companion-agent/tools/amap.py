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

CITY_BIAS_ALIASES = {
    "beijing": "北京",
    "peking": "北京",
    "shanghai": "上海",
    "chengdu": "成都",
    "chongqing": "重庆",
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "hangzhou": "杭州",
    "nanjing": "南京",
    "xian": "西安",
    "xi'an": "西安",
    "hong kong": "香港",
    "hongkong": "香港",
    "tokyo": "东京",
}

CITY_NAME_HINTS = {
    "北京",
    "北京市",
    "上海",
    "上海市",
    "广州",
    "广州市",
    "深圳",
    "深圳市",
    "成都",
    "成都市",
    "重庆",
    "重庆市",
    "杭州",
    "杭州市",
    "南京",
    "南京市",
    "西安",
    "西安市",
    "香港",
    "东京",
    "武汉",
    "武汉市",
    *CITY_BIAS_ALIASES.keys(),
    *CITY_BIAS_ALIASES.values(),
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


def _city_field_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _city_match_tokens(city_bias: str) -> set[str]:
    normalized = _normalize_city_bias(city_bias)
    compact = normalized.strip()
    tokens = {compact.lower()}
    if compact.endswith("市"):
        tokens.add(compact[:-1].lower())
    return {token for token in tokens if token}


def _matches_city(item: dict[str, Any], city_bias: str) -> bool:
    """Match POI/geocode results against the current itinerary city.

    Do not use formatted_address here: street names can contain another city name
    and same-name POIs often exist across cities.
    """
    if not city_bias:
        return True
    city_tokens = _city_match_tokens(city_bias)
    haystack = " ".join(
        _city_field_text(item.get(field)).lower()
        for field in ("city", "cityname", "pname", "province", "district", "adname")
    )
    return any(token in haystack for token in city_tokens)


def _normalize_city_bias(city_bias: str) -> str:
    value = city_bias.strip()
    return CITY_BIAS_ALIASES.get(value.lower(), value)


def _query_has_city_hint(query: str) -> bool:
    lowered = query.lower()
    return any(str(city).lower() in lowered for city in CITY_NAME_HINTS if city)


def _query_with_city_bias(query: str, city_bias: str) -> str:
    clean_query = query.strip()
    normalized_city = _normalize_city_bias(city_bias).strip()
    if not clean_query or not normalized_city or _query_has_city_hint(clean_query):
        return clean_query
    return f"{normalized_city}{clean_query}"


def _city_from_item(item: dict[str, Any], fallback_city: str) -> str:
    for field in ("city", "cityname", "pname", "province"):
        value = _city_field_text(item.get(field))
        if value:
            return value
    return fallback_city


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

    clean_query = query.strip()
    city_bias = _normalize_city_bias(city_bias or settings.default_city)
    biased_query = _query_with_city_bias(clean_query, city_bias)
    params = {"key": settings.amap_api_key, "address": biased_query, "city": city_bias}
    response = requests.get(AMAP_GEOCODE_URL, params=params, timeout=settings.request_timeout_s)
    response.raise_for_status()
    payload = response.json()
    geocodes = payload.get("geocodes") or []
    filtered_geocodes = [item for item in geocodes if _matches_city(item, city_bias)]
    if filtered_geocodes:
        item = filtered_geocodes[0]
        coords = _extract_coords(item.get("location", ""))
        lat, lon = coords or (0.0, 0.0)
        return {
            "name": clean_query,
            "address": item.get("formatted_address", clean_query),
            "city": _city_from_item(item, city_bias),
            "district": item.get("district") or _city_from_item(item, city_bias),
            "lat": lat,
            "lon": lon,
            "adcode": item.get("adcode", ""),
            "source": "amap_geocode",
        }

    params = {
        "key": settings.amap_api_key,
        "keywords": biased_query,
        "city": city_bias,
        "citylimit": "true",
        "offset": 3,
        "page": 1,
        "extensions": "all",
    }
    response = requests.get(AMAP_PLACE_TEXT_URL, params=params, timeout=settings.request_timeout_s)
    response.raise_for_status()
    payload = response.json()
    pois = payload.get("pois") or []
    pois = [item for item in pois if _matches_city(item, city_bias)]
    if not pois:
        raise ValueError(f"No location result found for '{query}'.")

    item = pois[0]
    coords = _extract_coords(item.get("location", ""))
    lat, lon = coords or (0.0, 0.0)
    return {
        "name": item.get("name", clean_query),
        "address": item.get("address", clean_query),
        "city": _city_from_item(item, city_bias),
        "district": item.get("adname") or item.get("pname") or city_bias,
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
    city = _normalize_city_bias(city)

    params = {
        "key": settings.amap_api_key,
        "keywords": _query_with_city_bias(query.strip(), city),
        "city": city.strip() or _normalize_city_bias(settings.default_city),
        "citylimit": "true",
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


def fetch_poi_detail_from_amap(
    name: str,
    city: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Query Amap v3/place/text (extensions=all) for open_hours and ticket_price.

    Uses biz_ext.open_time for opening hours and biz_ext.cost for price,
    consistent with how the main travel planner (poi.py) queries Amap.
    Returns a partial dict; callers should merge with static fallback data.
    """
    import re

    settings = settings or Settings.from_env()
    if not settings.has_amap_key:
        return {"source": "fallback"}

    params = {
        "key": settings.amap_api_key,
        "keywords": _query_with_city_bias(name.strip(), city or settings.default_city),
        "city": (city or settings.default_city).strip(),
        "citylimit": "true",
        "offset": 1,
        "page": 1,
        "extensions": "all",
    }
    try:
        response = requests.get(AMAP_PLACE_TEXT_URL, params=params, timeout=settings.request_timeout_s)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {"source": "fallback"}

    pois = payload.get("pois") or []
    if not pois:
        return {"source": "fallback"}

    item = pois[0]
    biz_ext = item.get("biz_ext") or {}

    open_hours = biz_ext.get("open_time") or ""

    ticket_price: float | None = None
    cost_raw = biz_ext.get("cost") or item.get("cost") or ""
    if cost_raw:
        nums = re.findall(r"\d+(?:\.\d+)?", str(cost_raw))
        if nums:
            try:
                ticket_price = float(nums[0])
            except Exception:
                pass

    result: dict[str, Any] = {"source": "amap"}
    if open_hours:
        result["open_hours"] = open_hours
    if ticket_price is not None:
        result["ticket_price"] = ticket_price
    return result
