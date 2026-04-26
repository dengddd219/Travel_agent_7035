## author:SUN Bin
from __future__ import annotations

from collections import OrderedDict

import requests

from ..config import Settings
from ..data_store import load_city_profile

"""Travel tips adapter.

This layer should stay lightweight:
- prefer live web search when Tavily is configured
- otherwise fall back to small, city-level heuristics

It should not try to deeply infer user intent from raw language. That semantic
work belongs to the LLM understanding layer upstream.
"""


TAVILY_URL = "https://api.tavily.com/search"


def _heuristic_tip_entries(city: str, poi_names: list[str], travel_type: str, interests: list[str]) -> list[dict]:
    """Generate small fallback tips without relying on web search."""
    profile = load_city_profile(city)
    tips: list[dict] = []
    city_level = OrderedDict()
    city_level["Move by district, not by attraction popularity alone."] = None
    for transport_tip in profile.get("transport", [])[:2]:
        city_level[transport_tip] = None
    for fallback_tip in profile.get("bad_weather_fallbacks", [])[:1]:
        city_level[fallback_tip] = None
    pace_note = str((profile.get("travel_type_guidance", {}).get(travel_type, {}) or {}).get("pace_note", "")).strip()
    if pace_note:
        city_level[pace_note] = None
    if travel_type == "food":
        city_level["Book one signature meal and keep the rest flexible for neighborhood discoveries."] = None
    if "family" in interests or travel_type == "family":
        city_level["Keep at least one low-effort indoor backup each day for children and sudden weather changes."] = None

    for poi_name in poi_names[:4]:
        tips.append(
            {
                "poi_name": poi_name,
                "tip": "Keep this stop grouped with nearby places instead of crossing the city just for one check-in.",
                "source": "heuristic",
            }
        )
    tips.extend({"poi_name": city, "tip": tip, "source": "heuristic"} for tip in city_level.keys())
    return tips


def _tavily_search(city: str, poi_names: list[str], travel_type: str, interests: list[str], settings: Settings) -> list[dict]:
    """Fetch supplementary tips from Tavily when the API key is configured."""
    query = (
        f"{city} travel tips for {travel_type} trip. "
        f"Focus on {', '.join(poi_names[:5])}. "
        f"Interests: {', '.join(interests[:5]) or 'local experiences'}."
    )
    response = requests.post(
        TAVILY_URL,
        json={
            "api_key": settings.tavily_api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": 5,
            "include_answer": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    tips = []
    answer = payload.get("answer")
    if answer:
        tips.append({"poi_name": city, "tip": answer, "source": "tavily-answer"})

    for item in payload.get("results", [])[:5]:
        tips.append(
            {
                "poi_name": city,
                "tip": item.get("content", "")[:280],
                "source": item.get("url", "tavily"),
            }
        )
    return tips


def get_travel_tips(
    city: str,
    poi_names: list[str],
    travel_type: str = "leisure",
    interests: list[str] | None = None,
    settings: Settings | None = None,
) -> dict:
    """Return normalized tip entries regardless of provider source."""
    settings = settings or Settings.from_env()
    interests = interests or []

    try:
        tips = (
            _tavily_search(city, poi_names, travel_type, interests, settings)
            if settings.tavily_api_key
            else _heuristic_tip_entries(city, poi_names, travel_type, interests)
        )
        provider = "tavily" if settings.tavily_api_key else "heuristic"
    except Exception:
        tips = _heuristic_tip_entries(city, poi_names, travel_type, interests)
        provider = "heuristic"

    return {"city": city, "provider": provider, "tips": tips}
