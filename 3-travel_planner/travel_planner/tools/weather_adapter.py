## author:SUN Bin
from __future__ import annotations

import os
import re
from datetime import date, timedelta

from ._group_c_loader import load_group_c_weather_cost_api
from ..config import Settings
from ..city_names import provider_city_name

"""Adapter from Group C weather output into our planner-facing weather schema."""


def _resolve_dates(trip_days: int, start_date: str = "") -> list[str]:
    """Expand a start date and trip length into a date list."""
    if start_date:
        start = date.fromisoformat(start_date)
    else:
        start = date.today()
    return [(start + timedelta(days=index)).isoformat() for index in range(max(trip_days, 1))]


def _resolve_weather_request_window(trip_days: int, start_date: str = "") -> tuple[list[str], str]:
    """
    Group C's provider only guarantees a short Amap forecast window.
    For routing purposes we prefer a real near-term forecast over mock data,
    so requests outside the supported window are normalized back to the nearest
    live window and marked with a note in the payload.
    """
    today = date.today()
    requested_start = date.fromisoformat(start_date) if start_date else today
    max_live_days = 4
    requested_dates = _resolve_dates(trip_days=trip_days, start_date=start_date)
    latest_live_date = today + timedelta(days=max_live_days - 1)

    if today <= requested_start <= latest_live_date:
        capped_end = min(requested_start + timedelta(days=max(trip_days, 1) - 1), latest_live_date)
        live_dates = [
            (requested_start + timedelta(days=index)).isoformat()
            for index in range((capped_end - requested_start).days + 1)
        ]
        if len(live_dates) == max(trip_days, 1):
            return live_dates, ""

    shifted_dates = [(today + timedelta(days=index)).isoformat() for index in range(min(max(trip_days, 1), max_live_days))]
    note = "Requested travel dates are outside the provider's live forecast window, so the planner used the nearest available weather window as a planning proxy."
    return shifted_dates, note


def _parse_number(value: object, default: float = 0.0) -> float:
    """Extract the first numeric value from a provider field."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else default


def _infer_precipitation_probability(condition: str, raw_precip: object) -> int:
    """Derive a precipitation probability even when the provider is incomplete."""
    parsed = int(_parse_number(raw_precip, default=-1))
    if parsed >= 0:
        return max(0, min(parsed, 100))

    text = condition.lower()
    if any(term in text for term in ["暴雨", "大雨", "雷", "storm", "thunder"]):
        return 85
    if any(term in text for term in ["中雨", "小雨", "阵雨", "雨", "snow", "雪"]):
        return 60
    if any(term in text for term in ["阴", "多云", "雾", "霾", "cloud", "fog", "haze"]):
        return 35
    return 10


def _outdoor_suitability(condition: str, precipitation_probability: int) -> str:
    """Translate weather severity into planner-friendly routing labels."""
    text = condition.lower()
    if precipitation_probability >= 70 or any(term in text for term in ["暴雨", "大雨", "雷", "storm", "thunder"]):
        return "poor"
    if precipitation_probability >= 40 or any(term in text for term in ["雨", "雪", "雾", "霾", "rain", "snow", "fog", "haze"]):
        return "mixed"
    return "good"


def _build_suggestions(advice: str, suitability: str) -> list[str]:
    """Convert provider advice into a compact list of action-oriented suggestions."""
    suggestions = []
    if advice:
        suggestions.append(advice)
    if suitability == "poor":
        suggestions.append("Bias the day toward indoor venues and reduce exposed walking.")
    elif suitability == "mixed":
        suggestions.append("Keep one indoor backup and front-load outdoor stops.")
    else:
        suggestions.append("Good weather window for outdoor districts and viewpoints.")
    return suggestions


def get_group_c_weather_forecast(
    city: str,
    trip_days: int = 3,
    start_date: str = "",
    settings: Settings | None = None,
) -> dict:
    """Call Group C weather and return a stable normalized forecast payload."""
    get_weather_api = load_group_c_weather_cost_api().get_weather_api
    if settings and settings.amap_api_key and not os.getenv("AMAP_WEB_SERVICE_KEY"):
        os.environ["AMAP_WEB_SERVICE_KEY"] = settings.amap_api_key

    requested_dates, window_note = _resolve_weather_request_window(trip_days=trip_days, start_date=start_date)
    source_city = provider_city_name(city, provider="zh")
    raw_days = get_weather_api(source_city, requested_dates)

    forecast = []
    padded_days = list(raw_days[: max(trip_days, 1)])
    while padded_days and len(padded_days) < max(trip_days, 1):
        template = dict(padded_days[-1])
        template["date"] = _resolve_dates(trip_days=trip_days, start_date=start_date or requested_dates[0])[len(padded_days)]
        template["source"] = f"{template.get('source', 'group_c_weather')}_extended"
        padded_days.append(template)

    for index, item in enumerate(padded_days[: max(trip_days, 1)]):
        condition = str(item.get("condition", "Unknown")).strip() or "Unknown"
        precipitation_probability = _infer_precipitation_probability(condition, item.get("precip"))
        suitability = _outdoor_suitability(condition, precipitation_probability)
        final_date = _resolve_dates(trip_days=trip_days, start_date=start_date)[index]
        suggestions = _build_suggestions(str(item.get("advice", "")).strip(), suitability)
        if window_note and index == 0:
            suggestions.append(window_note)
        forecast.append(
            {
                "date": final_date,
                "summary": condition,
                "temp_min": _parse_number(item.get("temp_min")),
                "temp_max": _parse_number(item.get("temp_max")),
                "precipitation_probability": precipitation_probability,
                "outdoor_suitability": suitability,
                "suggestions": suggestions,
                "source": item.get("source", "group_c_weather"),
            }
        )

    return {
        "city": city,
        "start_date": start_date,
        "forecast": forecast,
        "best_outdoor_days": [item["date"] for item in forecast if item["outdoor_suitability"] == "good"],
        "risky_days": [item["date"] for item in forecast if item["outdoor_suitability"] == "poor"],
        "source": "group_c_weather_adapter",
        "provider_city": source_city,
        "window_note": window_note,
    }
