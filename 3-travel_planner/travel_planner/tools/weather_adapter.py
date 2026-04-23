from __future__ import annotations

import os
import re
from datetime import date, timedelta

from WeatherCost.weather_cost_api import get_weather_api

from ..config import Settings


CITY_NAME_MAP = {
    "beijing": "北京",
    "chengdu": "成都",
    "chongqing": "重庆",
    "guangzhou": "广州",
    "hangzhou": "杭州",
    "nanjing": "南京",
    "shanghai": "上海",
    "shenzhen": "深圳",
    "wuhan": "武汉",
    "xian": "西安",
    "xi'an": "西安",
    "xiamen": "厦门",
}


def _normalize_city_name(city: str) -> str:
    key = city.strip().lower()
    return CITY_NAME_MAP.get(key, city.strip())


def _resolve_dates(trip_days: int, start_date: str = "") -> list[str]:
    if start_date:
        start = date.fromisoformat(start_date)
    else:
        start = date.today()
    return [(start + timedelta(days=index)).isoformat() for index in range(max(trip_days, 1))]


def _parse_number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else default


def _infer_precipitation_probability(condition: str, raw_precip: object) -> int:
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
    text = condition.lower()
    if precipitation_probability >= 70 or any(term in text for term in ["暴雨", "大雨", "雷", "storm", "thunder"]):
        return "poor"
    if precipitation_probability >= 40 or any(term in text for term in ["雨", "雪", "雾", "霾", "rain", "snow", "fog", "haze"]):
        return "mixed"
    return "good"


def _build_suggestions(advice: str, suitability: str) -> list[str]:
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
    if settings and settings.amap_api_key and not os.getenv("AMAP_WEB_SERVICE_KEY"):
        os.environ["AMAP_WEB_SERVICE_KEY"] = settings.amap_api_key

    requested_dates = _resolve_dates(trip_days=trip_days, start_date=start_date)
    source_city = _normalize_city_name(city)
    raw_days = get_weather_api(source_city, requested_dates)

    forecast = []
    for item in raw_days[: max(trip_days, 1)]:
        condition = str(item.get("condition", "Unknown")).strip() or "Unknown"
        precipitation_probability = _infer_precipitation_probability(condition, item.get("precip"))
        suitability = _outdoor_suitability(condition, precipitation_probability)
        forecast.append(
            {
                "date": item.get("date", ""),
                "summary": condition,
                "temp_min": _parse_number(item.get("temp_min")),
                "temp_max": _parse_number(item.get("temp_max")),
                "precipitation_probability": precipitation_probability,
                "outdoor_suitability": suitability,
                "suggestions": _build_suggestions(str(item.get("advice", "")).strip(), suitability),
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
    }
