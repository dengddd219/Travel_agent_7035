from __future__ import annotations

import re

from WeatherCost.weather_cost_api import estimate_cost_api


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


def _normalize_city_name(city: str) -> str:
    key = city.strip().lower()
    return CITY_NAME_MAP.get(key, city.strip())


def _normalize_budget_level(budget_level: str) -> str:
    key = budget_level.strip().lower()
    return BUDGET_LEVEL_MAP.get(key, "medium")


def _extract_range(value: object) -> dict[str, float]:
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
    source_city = _normalize_city_name(city)
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
