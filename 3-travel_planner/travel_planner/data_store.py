## author:SUN Bin
from __future__ import annotations

import json
from pathlib import Path

from .city_names import normalize_poi_display_name, normalize_rag_query_text

"""Load packaged city profiles.

City profiles are our stable knowledge layer:
- recommended areas
- transport heuristics
- default search themes
- seed POIs

They give the system a city-specific baseline before real-time tools and RAG
add more dynamic information.
"""


DATA_DIR = Path(__file__).resolve().parent / "data" / "city_profiles"


def _normalize_profile_display_names(profile: dict) -> dict:
    normalized = json.loads(json.dumps(profile))
    for area in normalized.get("recommended_areas", []):
        if isinstance(area, dict) and area.get("name"):
            area["name"] = normalize_poi_display_name(area["name"])
    for guidance in normalized.get("travel_type_guidance", {}).values():
        queries = guidance.get("suggested_queries", [])
        guidance["suggested_queries"] = [normalize_rag_query_text(item) for item in queries]
    for poi in normalized.get("seed_pois", []):
        if isinstance(poi, dict) and poi.get("name"):
            poi["name"] = normalize_poi_display_name(poi["name"])
    return normalized


def _slugify_city(city: str) -> str:
    """Convert a city label into the filename pattern used by profile JSON files."""
    return city.strip().lower().replace(" ", "_").replace("-", "_")


def load_city_profile(city: str) -> dict:
    """Load a city profile by canonical name or alias.

    If no explicit file is found, return a safe fallback profile so the planner
    can still produce a result instead of crashing.
    """
    city_slug = _slugify_city(city)
    target = DATA_DIR / f"{city_slug}.json"
    if target.exists():
        return _normalize_profile_display_names(json.loads(target.read_text(encoding="utf-8")))

    for path in DATA_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        aliases = [alias.lower() for alias in data.get("aliases", [])]
        if city.lower() in aliases:
            return _normalize_profile_display_names(data)

    return _normalize_profile_display_names({
        "city": city,
        "aliases": [city],
        "recommended_areas": [],
        "transport": [
            "Prioritize metro or rail for cross-district movement.",
            "Keep the day focused on one main area to reduce transfer time.",
        ],
        "bad_weather_fallbacks": [
            "Switch outdoor viewpoints to museums, markets, or indoor cultural venues.",
            "Move shopping streets or waterfront walks to the evening if rain eases.",
        ],
        "signature_foods": [],
        "travel_type_guidance": {
            "leisure": {
                "focus_tags": ["landmark", "view", "culture"],
                "suggested_queries": [f"{city} landmark", f"{city} waterfront", f"{city} museum"],
                "pace_note": "Leave room for scenic breaks and flexible exploration.",
            },
            "family": {
                "focus_tags": ["family", "park", "museum"],
                "suggested_queries": [f"{city} family attraction", f"{city} aquarium", f"{city} park"],
                "pace_note": "Avoid overly dense schedules and reduce cross-city transfers.",
            },
            "food": {
                "focus_tags": ["food", "market", "neighborhood"],
                "suggested_queries": [f"{city} food market", f"{city} local restaurant", f"{city} cafe street"],
                "pace_note": "Group meals by neighborhood and space out high-demand dining stops.",
            },
            "theme": {
                "focus_tags": ["culture", "design", "niche"],
                "suggested_queries": [f"{city} cultural district", f"{city} hidden gem", f"{city} design museum"],
                "pace_note": "Build the itinerary around one strong narrative instead of breadth.",
            },
        },
        "indoor_keywords": ["museum", "mall", "market", "gallery", "temple", "aquarium", "indoor"],
        "outdoor_keywords": ["park", "garden", "peak", "beach", "harbour", "ferry", "promenade", "trail"],
    })
