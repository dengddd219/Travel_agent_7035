from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from WeatherCost.weather_cost_api import search_hotels_api


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


def _resolve_stay_window(start_date: str, trip_days: int) -> tuple[str, str]:
    if start_date:
        check_in = date.fromisoformat(start_date)
    else:
        check_in = date.today()
    hotel_nights = max(trip_days - 1, 1)
    check_out = check_in + timedelta(days=hotel_nights)
    return check_in.isoformat(), check_out.isoformat()


def _budget_cap(cost_summary: dict | None) -> float | None:
    if not cost_summary:
        return None
    return cost_summary.get("breakdown", {}).get("hotel_per_night", {}).get("max")


def _score_hotel(hotel: dict, target_districts: list[str], nightly_cap: float | None) -> tuple:
    district = (hotel.get("district") or "").strip()
    district_hit = 1 if district and district in target_districts else 0
    has_price = 1 if hotel.get("min_price") is not None else 0
    price = hotel.get("min_price")
    within_budget = 1 if nightly_cap is None or price is None or float(price) <= float(nightly_cap) else 0
    source_rank = {
        "hotel_playwright_scraper": 3,
        "hotel_init_data": 2,
        "hotel_scraper": 1,
    }.get(hotel.get("source"), 0)
    star_rate = float(hotel.get("star_rate") or 0)
    normalized_price = float(price) if price is not None else 10**9
    return (district_hit, has_price, within_budget, source_rank, star_rate, -normalized_price)


def get_hotel_candidates(
    city: str,
    trip_days: int,
    start_date: str = "",
    target_districts: list[str] | None = None,
    budget_level: str = "medium",
    cost_summary: dict | None = None,
    keyword: str | None = None,
    star_rate: int | None = None,
    limit: int = 5,
) -> dict:
    source_city = _normalize_city_name(city)
    check_in_date, check_out_date = _resolve_stay_window(start_date=start_date, trip_days=trip_days)
    target_districts = [district for district in (target_districts or []) if district]
    nightly_cap = _budget_cap(cost_summary)

    raw_hotels = search_hotels_api(
        city=source_city,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        keyword=keyword,
        star_rate=star_rate,
    )

    normalized = []
    for hotel in raw_hotels:
        normalized.append(
            {
                "hotel_id": hotel.get("hotel_id"),
                "name": hotel.get("name"),
                "district": hotel.get("district"),
                "address": hotel.get("address"),
                "business": hotel.get("business"),
                "star_rate": hotel.get("star_rate"),
                "min_price": hotel.get("min_price"),
                "source": hotel.get("source"),
                "source_url": hotel.get("source_url"),
                "price_note": hotel.get("price_note"),
            }
        )

    normalized.sort(key=lambda item: _score_hotel(item, target_districts, nightly_cap), reverse=True)
    top_candidates = normalized[:limit]

    district_counter = Counter(
        district for district in ([hotel.get("district") for hotel in top_candidates] + target_districts) if district
    )
    recommended_areas = []
    for district, _ in district_counter.most_common(3):
        reason = "Close to the itinerary's core activity districts."
        if district in target_districts:
            reason = "Matches the itinerary's highest-frequency districts."
        recommended_areas.append({"district": district, "reason": reason})

    selection_notes = [
        "Hotels are ranked by itinerary district match first, then by price visibility and source quality.",
    ]
    if nightly_cap is not None:
        selection_notes.append(f"Current hotel budget reference is up to CNY {float(nightly_cap):.0f} per night.")
    if not top_candidates:
        selection_notes.append("No live hotel candidates were returned, so use the recommended areas as the fallback stay guide.")

    return {
        "city": city,
        "provider_city": source_city,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "budget_level": budget_level,
        "target_districts": target_districts,
        "recommended_areas": recommended_areas,
        "hotel_candidates": top_candidates,
        "selection_notes": selection_notes,
        "source": "hotel_adapter",
    }
