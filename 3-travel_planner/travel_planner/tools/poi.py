## author:SUN Bin
from __future__ import annotations

from collections import OrderedDict

import requests

from ..config import Settings
from ..city_names import city_name_bundle, provider_city_name
from ..data_store import load_city_profile


AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MAX_CITY_RADIUS_DEGREES = 1.5
ITINERARY_EXCLUDE_KEYWORDS = {
    "酒店",
    "宾馆",
    "民宿",
    "公寓",
    "停车场",
    "停车",
    "地铁站",
    "公交站",
    "充电站",
    "写字楼",
    "宿舍",
    "委员会",
    "支行",
    "亚朵",
    "atour",
    "hotel",
    "hostel",
    "inn",
    "parking",
    "station",
}


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


def _city_match_tokens(city: str, profile: dict) -> set[str]:
    bundle = city_name_bundle(city)
    tokens = {
        bundle["canonical"].strip().lower(),
        bundle["city_en"].strip().lower(),
        bundle["city_zh"].strip().lower(),
        provider_city_name(city, provider="zh").strip().lower(),
    }
    for alias in profile.get("aliases", []):
        alias_text = str(alias).strip().lower()
        if alias_text:
            tokens.add(alias_text)
    return {token for token in tokens if token}


def _matches_requested_city(item: dict, city: str, profile: dict) -> bool:
    city_tokens = _city_match_tokens(city, profile)
    # Use only the city-level fields for matching; address alone is too ambiguous
    city_fields = [
        item.get("cityname", ""),
        item.get("pname", ""),
        item.get("adname", ""),
    ]
    haystack = " ".join(str(field).strip().lower() for field in city_fields if field)
    if not haystack:
        return True
    return any(token in haystack for token in city_tokens)


def _profile_city_center(profile: dict) -> tuple[float, float] | None:
    seeds = [item for item in profile.get("seed_pois", []) if item.get("lat") is not None and item.get("lon") is not None]
    if not seeds:
        return None
    lat = sum(float(item["lat"]) for item in seeds) / len(seeds)
    lon = sum(float(item["lon"]) for item in seeds) / len(seeds)
    return lat, lon


def _within_city_radius(lat: float, lon: float, profile: dict) -> bool:
    center = _profile_city_center(profile)
    if not center:
        return True
    center_lat, center_lon = center
    return abs(lat - center_lat) <= MAX_CITY_RADIUS_DEGREES and abs(lon - center_lon) <= MAX_CITY_RADIUS_DEGREES


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

    filtered_pois = [item for item in pois if _matches_requested_city(item, city, profile)]
    if not filtered_pois:
        filtered_pois = pois

    results = []
    for item in filtered_pois:
        lng, lat = 0.0, 0.0
        location = item.get("location", "")
        if "," in location:
            parts = location.split(",")
            try:
                lng = float(parts[0])
                lat = float(parts[1])
            except ValueError:
                lng, lat = 0.0, 0.0
        if lat and lng and not _within_city_radius(lat, lng, profile):
            continue

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
        if len(results) >= limit:
            break
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


def _is_strong_seed_match(query: str, candidate: dict) -> bool:
    query_lower = query.strip().lower()
    if not query_lower:
        return False
    haystack = " ".join(
        [
            candidate.get("name", ""),
            candidate.get("district", ""),
            " ".join(candidate.get("tags", [])),
            candidate.get("category", ""),
        ]
    ).lower()
    query_tokens = [token for token in query_lower.replace("/", " ").split() if token]
    return query_lower in haystack or (query_tokens and all(token in haystack for token in query_tokens))


def _is_itinerary_worthy(candidate: dict) -> bool:
    if candidate.get("category") == "hotel":
        return False
    searchable = " ".join(
        [
            candidate.get("name", ""),
            candidate.get("address", ""),
            candidate.get("district", ""),
            " ".join(candidate.get("tags", [])),
            candidate.get("visit_reason", ""),
        ]
    ).lower()
    return not any(keyword in searchable for keyword in ITINERARY_EXCLUDE_KEYWORDS)


def _merge_candidates(primary: list[dict], secondary: list[dict], limit: int) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for candidate in primary + secondary:
        if not _is_itinerary_worthy(candidate):
            continue
        dedupe_key = f"{candidate.get('name', '').strip().lower()}|{candidate.get('district', '').strip().lower()}"
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        merged.append(candidate)
        if len(merged) >= limit:
            break
    return merged


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
        seed_candidates = _profile_seed_results(query, profile, limit_per_query)
        strong_seed_candidates = [candidate for candidate in seed_candidates if _is_strong_seed_match(query, candidate)]

        if not settings.has_amap_key:
            candidates = strong_seed_candidates or seed_candidates
            if candidates:
                provider = "profile_seed"

        if not candidates:
            try:
                if strong_seed_candidates:
                    candidates = _merge_candidates(strong_seed_candidates, [], limit_per_query)
                    provider = "profile_seed"
                else:
                    live_candidates = (
                        _amap_search(city, query, limit_per_query, settings, profile)
                        if settings.has_amap_key
                        else _nominatim_search(city, query, limit_per_query, profile)
                    )
                    candidates = _merge_candidates(seed_candidates, live_candidates, limit_per_query)
                    if seed_candidates and candidates and candidates[0] in seed_candidates:
                        provider = "profile_seed+amap" if settings.has_amap_key else "profile_seed+nominatim"
            except Exception:
                try:
                    live_candidates = _nominatim_search(city, query, limit_per_query, profile)
                    candidates = _merge_candidates(seed_candidates, live_candidates, limit_per_query)
                    provider = "mixed"
                except Exception:
                    candidates = seed_candidates
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
