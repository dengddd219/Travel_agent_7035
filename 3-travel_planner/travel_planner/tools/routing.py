from __future__ import annotations

from itertools import permutations
from math import asin, cos, radians, sin, sqrt

import requests

from ..config import Settings


AMAP_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"


def _coordinates(poi: dict) -> tuple[float, float]:
    return float(poi.get("lat", 0.0) or 0.0), float(poi.get("lon", 0.0) or 0.0)


def _has_valid_coordinates(poi: dict) -> bool:
    lat, lon = _coordinates(poi)
    return abs(lat) > 0.01 and abs(lon) > 0.01


def _coord_text(poi: dict) -> str:
    lat, lon = _coordinates(poi)
    return f"{lon:.6f},{lat:.6f}"


def _haversine_meters(origin: dict, destination: dict) -> int:
    lat1, lon1 = _coordinates(origin)
    lat2, lon2 = _coordinates(destination)
    if not all([lat1, lon1, lat2, lon2]):
        return 0

    radius = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return int(radius * c)


def _fallback_leg(origin: dict, destination: dict) -> dict:
    straight_line_m = max(150, _haversine_meters(origin, destination))
    same_district = origin.get("district", "").strip().lower() == destination.get("district", "").strip().lower()
    if same_district and straight_line_m <= 2500:
        mode = "walking"
        road_distance_m = int(straight_line_m * 1.18)
        duration_min = max(4, round(road_distance_m / 75))
        instruction = "Walk within the same district using the shortest pedestrian route."
    else:
        mode = "driving"
        road_distance_m = int(straight_line_m * 1.35)
        duration_min = max(8, round(road_distance_m / 380) + 4)
        instruction = f"Take a taxi or rideshare from {origin.get('district', 'the previous stop')} to {destination.get('district', 'the next stop')}."

    return {
        "mode": mode,
        "distance_m": road_distance_m,
        "duration_min": duration_min,
        "instruction": instruction,
        "provider": "fallback",
    }


def _parse_route_response(payload: dict, *, mode: str, fallback_instruction: str) -> dict:
    route = payload.get("route") or {}
    paths = route.get("paths") or []
    if not paths:
        raise ValueError("Amap route payload did not include any paths.")

    path = paths[0]
    distance_m = int(float(path.get("distance", 0) or 0))
    duration_s = int(float(path.get("duration", 0) or 0))
    steps = path.get("steps") or []
    if steps:
        first_instruction = steps[0].get("instruction", "").strip()
        last_instruction = steps[-1].get("instruction", "").strip()
        instruction = " -> ".join(part for part in [first_instruction, last_instruction] if part) or fallback_instruction
    else:
        instruction = fallback_instruction

    return {
        "mode": mode,
        "distance_m": distance_m,
        "duration_min": max(1, round(duration_s / 60)),
        "instruction": instruction,
        "provider": "amap",
    }


def _should_use_walking(origin: dict, destination: dict) -> bool:
    same_district = origin.get("district", "").strip().lower() == destination.get("district", "").strip().lower()
    return same_district and _haversine_meters(origin, destination) <= 2800


def get_leg_route(origin: dict, destination: dict, settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    if not settings.has_amap_key or not (_has_valid_coordinates(origin) and _has_valid_coordinates(destination)):
        return _fallback_leg(origin, destination)

    use_walking = _should_use_walking(origin, destination)
    endpoint = AMAP_WALKING_URL if use_walking else AMAP_DRIVING_URL
    params = {
        "key": settings.amap_api_key,
        "origin": _coord_text(origin),
        "destination": _coord_text(destination),
    }
    if not use_walking:
        params["extensions"] = "base"

    fallback_instruction = (
        "Walk between nearby stops in the same district."
        if use_walking
        else f"Drive or take a taxi from {origin.get('district', 'the previous stop')} to {destination.get('district', 'the next stop')}."
    )

    try:
        response = requests.get(endpoint, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "1":
            raise ValueError(payload.get("info", "Amap route request failed."))
        return _parse_route_response(
            payload,
            mode="walking" if use_walking else "driving",
            fallback_instruction=fallback_instruction,
        )
    except Exception:
        return _fallback_leg(origin, destination)


def optimize_route_order(pois: list[dict], *, must_visit_names: set[str] | None = None, settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    if len(pois) <= 1:
        return {
            "ordered_indices": list(range(len(pois))),
            "legs": [],
            "total_distance_m": 0,
            "total_duration_min": 0,
        }

    must_visit_names = {name.strip().lower() for name in must_visit_names or set() if name.strip()}
    leg_cache: dict[tuple[int, int], dict] = {}

    def leg(i: int, j: int) -> dict:
        cache_key = (i, j)
        if cache_key not in leg_cache:
            leg_cache[cache_key] = get_leg_route(pois[i], pois[j], settings=settings)
        return leg_cache[cache_key]

    best_order: tuple[int, ...] | None = None
    best_score: tuple[float, float, float] | None = None
    original_index = {index: index for index in range(len(pois))}

    for order in permutations(range(len(pois))):
        duration = sum(leg(order[pos], order[pos + 1])["duration_min"] for pos in range(len(order) - 1))
        distance = sum(leg(order[pos], order[pos + 1])["distance_m"] for pos in range(len(order) - 1))
        original_order_penalty = sum(abs(original_index[idx] - position) for position, idx in enumerate(order))
        must_visit_penalty = 0.0
        if must_visit_names and pois[order[0]].get("name", "").strip().lower() not in must_visit_names:
            must_visit_penalty = 0.25

        score = (duration + must_visit_penalty, distance / 1000, original_order_penalty)
        if best_score is None or score < best_score:
            best_score = score
            best_order = order

    ordered_indices = list(best_order or range(len(pois)))
    legs = [
        leg(ordered_indices[pos], ordered_indices[pos + 1])
        for pos in range(len(ordered_indices) - 1)
    ]
    return {
        "ordered_indices": ordered_indices,
        "legs": legs,
        "total_distance_m": sum(item["distance_m"] for item in legs),
        "total_duration_min": sum(item["duration_min"] for item in legs),
    }
