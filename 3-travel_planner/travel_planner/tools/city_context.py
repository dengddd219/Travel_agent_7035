from __future__ import annotations

from ..data_store import load_city_profile


def get_city_context(city: str, travel_type: str = "leisure") -> dict:
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
