from __future__ import annotations

from collections import OrderedDict

import requests

from ..config import Settings
from ..data_store import load_city_profile


AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def _normalize_query_items(queries: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for query in queries:
        item = query.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _infer_indoor_outdoor(name: str, raw_type: str, profile: dict) -> str:
    text = f"{name} {raw_type}".lower()
    if any(keyword.lower() in text for keyword in profile.get("indoor_keywords", [])):
        return "indoor"
    if any(keyword.lower() in text for keyword in profile.get("outdoor_keywords", [])):
        return "outdoor"
    return "mixed"


def _infer_category(raw_type: str, name: str) -> str:
    text = f"{raw_type} {name}".lower()
    if any(keyword in text for keyword in ["restaurant", "food", "cafe", "tea", "eat", "dining"]):
        return "food"
    if any(keyword in text for keyword in ["hotel", "inn", "hostel"]):
        return "hotel"
    if any(keyword in text for keyword in ["museum", "gallery", "park", "peak", "temple", "market", "harbour"]):
        return "attraction"
    return "attraction"


def _infer_tags(name: str, raw_type: str, category: str) -> list[str]:
    text = f"{name} {raw_type}".lower()
    tags = OrderedDict()
    if category == "food":
        tags["food"] = None
    if any(keyword in text for keyword in ["view", "harbour", "peak", "promenade", "observation"]):
        tags["view"] = None
    if any(keyword in text for keyword in ["park", "disney", "aquarium", "zoo", "family"]):
        tags["family"] = None
    if any(keyword in text for keyword in ["market", "street", "local", "neighborhood"]):
        tags["local"] = None
    if any(keyword in text for keyword in ["museum", "gallery", "culture", "temple"]):
        tags["culture"] = None
    if any(keyword in text for keyword in ["tram", "ferry", "rail", "boat"]):
        tags["transport_experience"] = None
    return list(tags.keys()) or [category]


def _amap_search(city: str, query: str, limit: int, settings: Settings, profile: dict) -> list[dict]:
    params = {
        "key": settings.amap_api_key,
        "keywords": query,
        "city": city,
        "children": 1,
        "offset": max(1, min(limit, 10)),
        "page": 1,
        "extensions": "all",
    }
    response = requests.get(AMAP_PLACE_TEXT_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    pois = payload.get("pois", [])

    results = []
    for item in pois[:limit]:
        lng, lat = 0.0, 0.0
        location = item.get("location", "")
        if "," in location:
            parts = location.split(",")
            try:
                lng = float(parts[0])
                lat = float(parts[1])
            except ValueError:
                lng, lat = 0.0, 0.0

        biz_ext = item.get("biz_ext") or {}
        ticket_price = 0.0
        raw_cost = biz_ext.get("cost") or item.get("cost") or 0
        try:
            ticket_price = float(raw_cost)
        except Exception:
            ticket_price = 0.0

        raw_type = item.get("type", "")
        category = _infer_category(raw_type, item.get("name", ""))
        results.append(
            {
                "name": item.get("name", query),
                "category": category,
                "district": item.get("adname") or item.get("pname") or city,
                "lat": lat,
                "lon": lng,
                "duration_hours": 1.5 if category != "food" else 1.2,
                "ticket_price": ticket_price,
                "price_level": 1 if ticket_price == 0 else min(5, max(1, int(ticket_price // 80) + 1)),
                "indoor_outdoor": _infer_indoor_outdoor(item.get("name", ""), raw_type, profile),
                "tags": _infer_tags(item.get("name", ""), raw_type, category),
                "source": ["amap"],
                "address": item.get("address", ""),
                "open_hours": biz_ext.get("open_time", ""),
                "rating": None,
                "visit_reason": f"Matched from POI search for '{query}'.",
            }
        )
    return results


def _nominatim_search(city: str, query: str, limit: int, profile: dict) -> list[dict]:
    headers = {"User-Agent": "MSBA7035-Intelligent-Travel-Planner/1.0"}
    params = {"q": f"{query}, {city}", "format": "jsonv2", "limit": limit}
    response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()

    results = []
    for item in payload[:limit]:
        name = item.get("display_name", query).split(",")[0]
        raw_type = item.get("type", "")
        category = _infer_category(raw_type, name)
        results.append(
            {
                "name": name,
                "category": category,
                "district": city,
                "lat": float(item.get("lat", 0) or 0),
                "lon": float(item.get("lon", 0) or 0),
                "duration_hours": 1.5 if category != "food" else 1.2,
                "ticket_price": 0.0,
                "price_level": 2,
                "indoor_outdoor": _infer_indoor_outdoor(name, raw_type, profile),
                "tags": _infer_tags(name, raw_type, category),
                "source": ["nominatim"],
                "address": item.get("display_name", ""),
                "open_hours": "",
                "rating": None,
                "visit_reason": f"Matched from geocoding fallback for '{query}'.",
            }
        )
    return results


def _profile_seed_results(query: str, profile: dict, limit: int) -> list[dict]:
    seeds = profile.get("seed_pois", [])
    query_lower = query.strip().lower()
    query_tokens = {token for token in query_lower.replace("/", " ").split() if token}

    ranked: list[tuple[int, dict]] = []
    for item in seeds:
        haystack = " ".join(
            [
                item.get("name", ""),
                item.get("district", ""),
                " ".join(item.get("tags", [])),
                item.get("category", ""),
            ]
        ).lower()
        overlap = sum(token in haystack for token in query_tokens) if query_tokens else 0
        if query_lower in haystack:
            overlap += 3
        if overlap:
            ranked.append((overlap, item))

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:limit]]


def search_batch_pois(city: str, queries: list[str], limit_per_query: int = 3, settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    profile = load_city_profile(city)
    normalized_queries = _normalize_query_items(queries)

    results: list[dict] = []
    missing_queries: list[str] = []
    seen: set[str] = set()
    provider = "amap" if settings.has_amap_key else "nominatim"

    for query in normalized_queries:
        candidates: list[dict] = []
        if not settings.has_amap_key:
            candidates = _profile_seed_results(query, profile, limit_per_query)
            if candidates:
                provider = "profile_seed"

        if not candidates:
            try:
                candidates = (
                    _amap_search(city, query, limit_per_query, settings, profile)
                    if settings.has_amap_key
                    else _nominatim_search(city, query, limit_per_query, profile)
                )
            except Exception:
                try:
                    candidates = _nominatim_search(city, query, limit_per_query, profile)
                    provider = "mixed"
                except Exception:
                    candidates = _profile_seed_results(query, profile, limit_per_query)
                    provider = "profile_seed"

        if not candidates:
            missing_queries.append(query)
            continue

        for candidate in candidates:
            dedupe_key = f"{candidate['name'].strip().lower()}|{candidate['district'].strip().lower()}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(candidate)

    if not results and profile.get("seed_pois"):
        provider = "profile_seed"
        for candidate in profile["seed_pois"][: max(4, limit_per_query * 2)]:
            dedupe_key = f"{candidate['name'].strip().lower()}|{candidate['district'].strip().lower()}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(candidate)

    return {
        "city": city,
        "provider": provider,
        "queries": normalized_queries,
        "results": results,
        "missing_queries": missing_queries,
    }
