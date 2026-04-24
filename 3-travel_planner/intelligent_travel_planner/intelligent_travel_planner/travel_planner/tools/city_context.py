## author:SUN Bin
from __future__ import annotations

from ..data_store import load_city_profile

"""Translate a packaged city profile into a runtime-ready context bundle."""


def get_city_context(city: str, travel_type: str = "leisure") -> dict:
    """Return the city-level context that the planner needs immediately.

    This is intentionally smaller than the raw profile file. The agent only gets
    the fields that actually affect decomposition and route planning.
    """
    profile = load_city_profile(city)
    guidance = profile.get("travel_type_guidance", {}).get(
        travel_type,
        profile.get("travel_type_guidance", {}).get("leisure", {}),
    )

    return {
        "city": profile.get("city", city),
        "recommended_areas": profile.get("recommended_areas", []),
        "transport": profile.get("transport", []),
        "bad_weather_fallbacks": profile.get("bad_weather_fallbacks", []),
        "signature_foods": profile.get("signature_foods", []),
        "focus_tags": guidance.get("focus_tags", []),
        "suggested_queries": guidance.get("suggested_queries", []),
        "pace_note": guidance.get("pace_note", ""),
    }
