## author:SUN Bin
from __future__ import annotations

import re

from WeatherCost.weather_cost_api import estimate_cost_api
from ..city_names import provider_city_name

"""Adapter from Group C cost output into our own normalized schema."""

BUDGET_LEVEL_MAP = {
    "economy": "low",
    "low": "low",
    "budget": "low",
    "medium": "medium",
    "mid": "medium",
    "balanced": "medium",
    "high": "high",
    "luxury": "high",
    "auto": "auto",
}


def _normalize_budget_level(budget_level: str) -> str:
    """Map loose user budget words into the small set Group C expects."""
    key = budget_level.strip().lower()
    return BUDGET_LEVEL_MAP.get(key, "medium")


def _extract_range(value: object) -> dict[str, float]:
    """Parse a text range like `150-250` into numeric min/max fields."""
    matches = re.findall(r"\d+(?:\.\d+)?", str(value))
    if not matches:
        return {"min": 0.0, "max": 0.0}
    if len(matches) == 1:
        amount = float(matches[0])
        return {"min": amount, "max": amount}
    low, high = float(matches[0]), float(matches[1])
    return {"min": min(low, high), "max": max(low, high)}


def get_group_c_cost_summary(
    city: str,
    days: int,
    budget_level: str,
    user_budget: float | None = None,
) -> dict:
    """Call Group C's estimator and reshape the response for our planner/UI."""
    source_city = provider_city_name(city, provider="zh")
    normalized_budget_level = _normalize_budget_level(budget_level)
    raw = estimate_cost_api(source_city, days, normalized_budget_level, user_budget=user_budget)

    hotel_per_night = _extract_range(raw.get("酒店每晚", ""))
    food_per_day = _extract_range(raw.get("餐饮每天", ""))
    local_transport_total = _extract_range(raw.get("交通合计", ""))

    total_min = float(raw.get("总计最低", 0))
    total_max = float(raw.get("总计最高", 0))
    total_mid = round((total_min + total_max) / 2, 2) if total_max or total_min else 0.0

    within_budget = None if user_budget is None else total_max <= float(user_budget)
    minimum_feasible = None if user_budget is None else total_min <= float(user_budget)
    budget_fit = {
        "user_budget": user_budget,
        "within_budget": within_budget,
        "minimum_feasible": minimum_feasible,
    }

    return {
        "city": city,
        "days": days,
        "budget_level": normalized_budget_level,
        "currency": "CNY",
        "breakdown": {
            "hotel_per_night": hotel_per_night,
            "food_per_day": food_per_day,
            "local_transport_total": local_transport_total,
        },
        "totals": {
            "min": total_min,
            "max": total_max,
            "mid": total_mid,
        },
        "budget_fit": budget_fit,
        "pricing_notes": [
            "Budget currently covers hotel, food, and local transport only.",
            "Long-haul flights and attraction tickets remain outside this estimate unless another provider adds them.",
        ],
        "source": "group_c_cost_adapter",
        "provider_city": source_city,
        "raw_response": raw,
    }
