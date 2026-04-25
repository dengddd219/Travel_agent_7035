from __future__ import annotations

from typing import Any

import requests

from config import Settings
from tools.amap import resolve_location


AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"


def get_weather_now(city: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    if not settings.has_amap_key:
        return {
            "city": city,
            "summary": "Unknown",
            "temp_min": 0.0,
            "temp_max": 0.0,
            "precipitation_probability": 0,
            "outdoor_suitability": "unknown",
            "suggestions": ["No live weather key configured."],
            "source": "fallback",
        }

    location = resolve_location(city, settings=settings)
    adcode = location.get("adcode", "")
    params = {
        "key": settings.amap_api_key,
        "city": adcode,
        "extensions": "base",
    }
    response = requests.get(AMAP_WEATHER_URL, params=params, timeout=settings.request_timeout_s)
    response.raise_for_status()
    payload = response.json()
    lives = payload.get("lives") or []
    if not lives:
        raise ValueError(f"No live weather returned for '{city}'.")

    item = lives[0]
    weather = str(item.get("weather", "")).strip() or "Unknown"
    temperature = float(item.get("temperature", 0) or 0)
    lower = weather.lower()
    if any(token in lower for token in ["雨", "storm", "雷"]):
        suitability = "poor"
        precip = 75
    elif any(token in lower for token in ["阴", "云", "雾", "霾", "cloud", "fog", "haze"]):
        suitability = "mixed"
        precip = 35
    else:
        suitability = "good"
        precip = 10

    suggestions = []
    if suitability == "poor":
        suggestions.append("优先改为室内点位，并减少暴露步行。")
    elif suitability == "mixed":
        suggestions.append("保留室内备选，优先完成室外核心点位。")
    else:
        suggestions.append("适合安排室外行程。")

    return {
        "city": city,
        "summary": weather,
        "temp_min": temperature,
        "temp_max": temperature,
        "precipitation_probability": precip,
        "outdoor_suitability": suitability,
        "suggestions": suggestions,
        "source": "amap_live_weather",
    }
