## author:SUN Bin
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from .agent import ConversationState, ConversationRunResult
from .city_names import city_name_bundle
from .config import Settings
from .llm import (
    build_user_report_generation_messages,
    build_user_report_polish_messages,
    create_response_client,
)


"""Presentation helpers for the frontend.

This module should focus on transforming already-structured itinerary data into
frontend payloads. It should avoid re-implementing deep travel understanding.
Natural-language polish is delegated to the LLM when available.
"""


DAY_COLORS = [
    "#0EA5E9",
    "#F97316",
    "#10B981",
    "#E11D48",
    "#8B5CF6",
]


@dataclass(slots=True)
class InMemoryConversationStore:
    conversations: dict[str, ConversationState]
    _lock: Lock

    def __init__(self) -> None:
        self.conversations = {}
        self._lock = Lock()

    def create(self, state: ConversationState) -> str:
        conversation_id = f"conv_{uuid4().hex[:12]}"
        with self._lock:
            self.conversations[conversation_id] = state
        return conversation_id

    def get(self, conversation_id: str) -> ConversationState | None:
        return self.conversations.get(conversation_id)

    def set(self, conversation_id: str, state: ConversationState) -> None:
        with self._lock:
            self.conversations[conversation_id] = state


def serialize_conversation_state(state: ConversationState) -> dict:
    return {
        "preference_memory": state.preference_memory,
        "latest_user_profile": state.latest_user_profile,
        "latest_plan": state.latest_plan,
        "latest_hotel_recommendations": state.latest_hotel_recommendations,
        "latest_report": state.latest_report,
        "confirmed_profile_slots": state.confirmed_profile_slots,
        "pending_profile_slots": state.pending_profile_slots,
        "needs_clarification": state.needs_clarification,
        "turn_history": state.turn_history,
    }


def deserialize_conversation_state(payload: dict) -> ConversationState:
    return ConversationState(
        preference_memory=payload.get("preference_memory", {}),
        latest_user_profile=payload.get("latest_user_profile", payload.get("preference_memory", {})),
        latest_plan=payload.get("latest_plan"),
        latest_hotel_recommendations=payload.get("latest_hotel_recommendations"),
        latest_report=payload.get("latest_report", ""),
        confirmed_profile_slots=payload.get("confirmed_profile_slots", []),
        pending_profile_slots=payload.get("pending_profile_slots", []),
        needs_clarification=payload.get("needs_clarification", False),
        turn_history=payload.get("turn_history", []),
    )


def _poi_lookup(itinerary_json: dict) -> dict[str, dict]:
    return {
        poi.get("name", "").strip().lower(): poi
        for poi in itinerary_json.get("selected_pois", [])
        if poi.get("name")
    }


def _plan_center(stops: list[dict]) -> dict:
    geo_stops = [stop for stop in stops if stop.get("lat") is not None and stop.get("lon") is not None]
    if not geo_stops:
        return {"lat": None, "lon": None}
    return {
        "lat": round(sum(stop["lat"] for stop in geo_stops) / len(geo_stops), 6),
        "lon": round(sum(stop["lon"] for stop in geo_stops) / len(geo_stops), 6),
    }


def build_map_payload(itinerary_json: dict) -> dict:
    poi_index = _poi_lookup(itinerary_json)
    all_stops: list[dict] = []
    day_payloads: list[dict] = []
    city_info = city_name_bundle(itinerary_json.get("city", ""))

    for raw_day in itinerary_json.get("days", []):
        color = DAY_COLORS[(raw_day["day_index"] - 1) % len(DAY_COLORS)]
        day_stops: list[dict] = []
        for sequence, item in enumerate(raw_day.get("items", []), start=1):
            poi = poi_index.get(item.get("poi_name", "").strip().lower(), {})
            stop = {
                "sequence": sequence,
                "poi_name": item.get("poi_name", ""),
                "time_slot": item.get("time_slot", ""),
                "category": item.get("category", ""),
                "district": item.get("district", poi.get("district", "")),
                "lat": poi.get("lat"),
                "lon": poi.get("lon"),
                "address": poi.get("address", ""),
                "open_hours": poi.get("open_hours", ""),
                "ticket_price": poi.get("ticket_price", item.get("est_cost", 0)),
                "arrival_mode": item.get("arrival_mode", "start"),
                "arrival_distance_m": item.get("arrival_distance_m", 0),
                "arrival_duration_min": item.get("arrival_duration_min", 0),
                "transport_hint": item.get("transport_hint", ""),
            }
            day_stops.append(stop)
            all_stops.append({**stop, "day_index": raw_day["day_index"], "color": color})

        day_legs: list[dict] = []
        for previous, current in zip(day_stops, day_stops[1:]):
            day_legs.append(
                {
                    "from_poi": previous["poi_name"],
                    "to_poi": current["poi_name"],
                    "mode": current["arrival_mode"],
                    "distance_m": current["arrival_distance_m"],
                    "duration_min": current["arrival_duration_min"],
                    "from_lat": previous.get("lat"),
                    "from_lon": previous.get("lon"),
                    "to_lat": current.get("lat"),
                    "to_lon": current.get("lon"),
                    "transport_hint": current.get("transport_hint", ""),
                }
            )

        day_payloads.append(
            {
                "day_index": raw_day["day_index"],
                "area": raw_day.get("area", ""),
                "theme": raw_day.get("theme", ""),
                "color": color,
                "inter_stop_distance_m": raw_day.get("inter_stop_distance_m", 0),
                "inter_stop_duration_min": raw_day.get("inter_stop_duration_min", 0),
                "stops": day_stops,
                "legs": day_legs,
            }
        )

    return {
        "city": city_info["canonical"],
        "city_en": city_info["city_en"],
        "city_zh": city_info["city_zh"],
        "center": _plan_center(all_stops),
        "days": day_payloads,
        "all_stops": all_stops,
    }


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: object) -> float:
    return round(_as_float(value), 2)


def _range(min_value: object = 0.0, max_value: object | None = None) -> dict:
    low = _money(min_value)
    high = _money(low if max_value is None else max_value)
    if high < low:
        low, high = high, low
    return {
        "min": low,
        "max": high,
        "mid": round((low + high) / 2, 2),
    }


def _normalize_range(payload: dict | None) -> dict:
    payload = payload or {}
    return _range(payload.get("min", 0.0), payload.get("max", payload.get("min", 0.0)))


def _scale_range(payload: dict | None, multiplier: int | float) -> dict:
    base = _normalize_range(payload)
    factor = max(float(multiplier), 0.0)
    return _range(base["min"] * factor, base["max"] * factor)


def _sum_ranges(*ranges: dict) -> dict:
    return _range(
        sum(_normalize_range(item)["min"] for item in ranges),
        sum(_normalize_range(item)["max"] for item in ranges),
    )


def _max_range(left: dict | None, right: dict | None) -> dict:
    left_range = _normalize_range(left)
    right_range = _normalize_range(right)
    return _range(max(left_range["min"], right_range["min"]), max(left_range["max"], right_range["max"]))


def _matches_any_name(name: str, candidates: list[str]) -> bool:
    key = name.strip().lower()
    if not key:
        return False
    return any(key in candidate.strip().lower() or candidate.strip().lower() in key for candidate in candidates if candidate)


def _is_guide_aligned(item: dict, rag_recommended_pois: list[str]) -> bool:
    reasoning = str(item.get("reasoning", ""))
    if "攻略" in reasoning or "检索" in reasoning:
        return True
    return _matches_any_name(str(item.get("poi_name", "")), rag_recommended_pois)


def _route_transport_estimate(days: list[dict]) -> dict:
    min_total = 0.0
    max_total = 0.0
    driving_distance_m = 0
    for day in days:
        for item in day.get("items", []) or []:
            mode = str(item.get("arrival_mode", "")).lower()
            distance_m = int(_as_float(item.get("arrival_distance_m"), 0.0))
            if mode in {"", "start"} or "walk" in mode:
                continue
            distance_km = max(distance_m / 1000, 0.0)
            driving_distance_m += distance_m
            min_total += max(10.0, 8.0 + distance_km * 2.2)
            max_total += max(16.0, 14.0 + distance_km * 3.2)
    estimate = _range(min_total, max_total)
    estimate["driving_distance_km"] = round(driving_distance_m / 1000, 2)
    return estimate


def build_plan_cost_summary(itinerary_json: dict, hotel_recommendations: dict | None = None) -> dict:
    """Build a cost payload tied to the final itinerary, not only the city envelope."""
    days = itinerary_json.get("days", []) if isinstance(itinerary_json, dict) else []
    if not days:
        return {}

    hotel_recommendations = hotel_recommendations or {}
    cost_summary = (itinerary_json.get("conditions_context") or {}).get("cost_summary") or {}
    strategy_summary = itinerary_json.get("strategy_summary", {}) or {}
    rag_recommended_pois = [str(item).strip() for item in strategy_summary.get("recommended_pois", []) if str(item).strip()]
    guide_references = [str(item).strip() for item in itinerary_json.get("guide_references", []) if str(item).strip()]

    day_costs: list[dict] = []
    paid_items: list[dict] = []
    guide_aligned_items: list[dict] = []
    total_route_distance_m = 0
    total_route_duration_min = 0
    attraction_total = 0.0
    guide_aligned_total = 0.0

    for day in days:
        day_attractions = 0.0
        day_guide_cost = 0.0
        day_paid_items: list[dict] = []
        for item in day.get("items", []) or []:
            item_cost = _money(item.get("est_cost", 0.0))
            is_guide_aligned = _is_guide_aligned(item, rag_recommended_pois)
            day_attractions += item_cost
            if is_guide_aligned:
                day_guide_cost += item_cost
            if item_cost > 0:
                paid_item = {
                    "day_index": day.get("day_index"),
                    "poi_name": item.get("poi_name", ""),
                    "cost": item_cost,
                    "guide_aligned": is_guide_aligned,
                    "reasoning": item.get("reasoning", ""),
                }
                day_paid_items.append(paid_item)
                paid_items.append(paid_item)
            if is_guide_aligned:
                guide_aligned_items.append(
                    {
                        "day_index": day.get("day_index"),
                        "poi_name": item.get("poi_name", ""),
                        "cost": item_cost,
                        "reasoning": item.get("reasoning", ""),
                    }
                )

        route_distance_m = int(_as_float(day.get("inter_stop_distance_m"), 0.0))
        route_duration_min = int(_as_float(day.get("inter_stop_duration_min"), 0.0))
        total_route_distance_m += route_distance_m
        total_route_duration_min += route_duration_min
        attraction_total += day_attractions
        guide_aligned_total += day_guide_cost
        day_costs.append(
            {
                "day_index": day.get("day_index"),
                "area": day.get("area", ""),
                "theme": day.get("theme", ""),
                "attraction_cost": _money(day_attractions),
                "guide_aligned_cost": _money(day_guide_cost),
                "route_distance_km": round(route_distance_m / 1000, 2),
                "route_duration_min": route_duration_min,
                "paid_items": day_paid_items[:5],
            }
        )

    trip_days = int(_as_float(itinerary_json.get("trip_days"), len(days))) or len(days)
    hotel_nights = max(trip_days - 1, 1)
    breakdown = cost_summary.get("breakdown", {}) if isinstance(cost_summary, dict) else {}
    hotel_per_night = _normalize_range(breakdown.get("hotel_per_night"))
    food_per_day = _normalize_range(breakdown.get("food_per_day"))
    city_transport_total = _normalize_range(breakdown.get("local_transport_total"))
    route_transport_total = _route_transport_estimate(days)
    transport_total = _max_range(city_transport_total, route_transport_total)

    hotel_total = _scale_range(hotel_per_night, hotel_nights)
    food_total = _scale_range(food_per_day, trip_days)
    attraction_range = _range(attraction_total)
    base_total = _sum_ranges(hotel_total, food_total, transport_total)
    plan_total = _sum_ranges(base_total, attraction_range)

    hotel_prices = [
        _as_float(hotel.get("min_price"), 0.0)
        for hotel in hotel_recommendations.get("hotel_candidates", [])[:5]
        if _as_float(hotel.get("min_price"), 0.0) > 0
    ]
    hotel_candidate_reference = _range(min(hotel_prices), max(hotel_prices)) if hotel_prices else {}
    recommended_areas = [
        area.get("district", "")
        for area in hotel_recommendations.get("recommended_areas", [])[:3]
        if area.get("district")
    ]

    pricing_notes = [
        "Plan-level total adds final itinerary attraction tickets to the city hotel/food/transport envelope.",
        "Guide-aligned cost is computed from POIs whose planner reasoning or RAG recommendations mention travel-guide evidence.",
        "Route transport uses the planned inter-stop legs; city-level transport remains the fallback when it is higher.",
    ]
    for note in (cost_summary.get("pricing_notes", []) if isinstance(cost_summary, dict) else []):
        if note not in pricing_notes:
            pricing_notes.append(note)

    return {
        "city": itinerary_json.get("city", cost_summary.get("city", "")),
        "days": trip_days,
        "budget_level": cost_summary.get("budget_level", "medium") if isinstance(cost_summary, dict) else "medium",
        "currency": cost_summary.get("currency", "CNY") if isinstance(cost_summary, dict) else "CNY",
        "totals": {
            **plan_total,
            "base_min": base_total["min"],
            "base_max": base_total["max"],
            "attraction_tickets": _money(attraction_total),
            "guide_aligned_attraction_tickets": _money(guide_aligned_total),
        },
        "breakdown": {
            "hotel_per_night": hotel_per_night,
            "hotel_total": hotel_total,
            "food_per_day": food_per_day,
            "food_total": food_total,
            "local_transport_total": transport_total,
            "city_transport_total": city_transport_total,
            "route_transport_total": route_transport_total,
            "attraction_tickets": attraction_range,
            "guide_aligned_attractions": _range(guide_aligned_total),
        },
        "itinerary_costs": {
            "hotel_nights": hotel_nights,
            "attraction_total": _money(attraction_total),
            "guide_aligned_attraction_total": _money(guide_aligned_total),
            "route_distance_km": round(total_route_distance_m / 1000, 2),
            "route_duration_min": total_route_duration_min,
            "daily": day_costs,
            "paid_items": paid_items[:12],
        },
        "guide_alignment": {
            "guide_references": guide_references[:4],
            "rag_recommended_pois": rag_recommended_pois[:8],
            "guide_aligned_items": guide_aligned_items[:12],
            "guide_aligned_count": len(guide_aligned_items),
        },
        "hotel_context": {
            "recommended_areas": recommended_areas,
            "candidate_nightly_reference": hotel_candidate_reference,
            "sample_hotels": hotel_recommendations.get("hotel_candidates", [])[:3],
        },
        "pricing_notes": pricing_notes,
        "sources": [
            "Final itinerary POI ticket estimates",
            "RAG / travel-guide evidence in planner reasoning",
            "Group C city cost envelope",
            "Hotel recommendation candidates and stay areas",
        ],
        "source": "plan_cost_aggregator",
        "base_cost_source": cost_summary.get("source", "") if isinstance(cost_summary, dict) else "",
    }


def _day_weather_sentence(weather_payload: dict, day_index: int) -> str:
    forecast = weather_payload.get("forecast", []) or []
    if day_index >= len(forecast):
        return ""
    weather = forecast[day_index]
    summary = str(weather.get("summary", "")).strip()
    temp_min = weather.get("temp_min")
    temp_max = weather.get("temp_max")
    precip = weather.get("precipitation_probability")
    if not summary:
        return ""
    return f"天气大概是{summary}，气温约 {temp_min}°C 到 {temp_max}°C，降水风险 {precip or 0}% 左右。"


def _build_user_report_brief(itinerary_json: dict, hotel_recommendations: dict | None = None) -> dict:
    # Convert the itinerary JSON into a compact structure for LLM copywriting.
    city_info = city_name_bundle(itinerary_json.get("city", ""))
    city = city_info["city_zh"] or city_info["city_en"] or itinerary_json.get("city", "这座城市")
    weather_payload = itinerary_json.get("weather_payload", {})
    strategy_summary = itinerary_json.get("strategy_summary", {})
    guide_references = [str(item).strip() for item in itinerary_json.get("guide_references", []) if str(item).strip()]
    hotel_recommendations = hotel_recommendations or {}

    days: list[dict] = []
    for zero_based_index, day in enumerate(itinerary_json.get("days", [])):
        stop_names = [str(item.get("poi_name", "")).strip() for item in day.get("items", []) if item.get("poi_name")]
        if not stop_names:
            continue
        days.append(
            {
                "day_index": day.get("day_index"),
                "area": day.get("area", ""),
                "theme": day.get("theme", ""),
                "top_stops": stop_names[:4],
                "weather_summary": _day_weather_sentence(weather_payload, zero_based_index),
                "day_notes": [str(note).strip() for note in day.get("notes", []) if str(note).strip()][:2],
            }
        )

    return {
        "city": city,
        "trip_days": itinerary_json.get("trip_days", len(days)),
        "overview": itinerary_json.get("overview", ""),
        "guide_references": guide_references[:4],
        "recommended_pois": strategy_summary.get("recommended_pois", [])[:6],
        "review_summary": itinerary_json.get("review_summary", ""),
        "replan_summary": itinerary_json.get("replan_summary", ""),
        "estimated_core_cost": itinerary_json.get("total_estimated_cost", 0),
        "hotel_areas": [
            area.get("district", "")
            for area in hotel_recommendations.get("recommended_areas", [])[:3]
            if area.get("district")
        ],
        "days": days,
    }


def _build_user_report_fallback(report_brief: dict) -> str:
    # Offline fallback if LLM copywriting is unavailable.
    city = report_brief.get("city", "这座城市")
    trip_days = report_brief.get("trip_days", len(report_brief.get("days", [])))
    paragraphs = [
        f"我先帮你排了一版 {city}{trip_days} 天的行程，整体会尽量让路线更顺、节奏更稳。"
    ]
    if report_brief.get("guide_references"):
        paragraphs.append("这版路线也参考了攻略里反复提到的信号：" + "；".join(report_brief["guide_references"][:3]) + "。")
    if report_brief.get("recommended_pois"):
        paragraphs.append("优先保留的高频点包括：" + "、".join(report_brief["recommended_pois"][:4]) + "。")
    for day in report_brief.get("days", []):
        weather = day.get("weather_summary", "")
        notes = " ".join(day.get("day_notes", []))
        paragraphs.append(
            " ".join(
                part for part in [
                    f"第{day.get('day_index', '?')}天建议主要待在{day.get('area', '核心区域')}附近，主题偏{day.get('theme', '城市体验')}，核心点位可以串联 { '、'.join(day.get('top_stops', [])) }。",
                    weather,
                    notes,
                ] if part
            )
        )
    closing = [f"核心景点门票我先按大约 CNY {float(report_brief.get('estimated_core_cost', 0)):.0f} 来估。"]
    if report_brief.get("hotel_areas"):
        closing.append("住宿优先住在 " + "、".join(report_brief["hotel_areas"][:2]) + " 会更顺路。")
    if report_brief.get("review_summary"):
        closing.append(str(report_brief["review_summary"]))
    paragraphs.append(" ".join(closing))
    return "\n\n".join(part for part in paragraphs if part.strip())


def generate_user_friendly_report(itinerary_json: dict, hotel_recommendations: dict | None = None) -> str:
    # Preferred path: build a structured brief, then let the LLM write the prose.
    report_brief = _build_user_report_brief(itinerary_json, hotel_recommendations)
    settings = Settings.from_env()
    if not settings.has_llm_credentials:
        return _build_user_report_fallback(report_brief)
    try:
        bundle = create_response_client(settings)
        response = bundle.client.responses.create(
            model=bundle.model,
            input=build_user_report_generation_messages(report_brief=report_brief),
        )
        generated = getattr(response, "output_text", "") or ""
        return generated.strip() or _build_user_report_fallback(report_brief)
    except Exception:
        return _build_user_report_fallback(report_brief)


def polish_user_friendly_report(raw_report: str, itinerary_json: dict) -> str:
    settings = Settings.from_env()
    if not settings.has_llm_credentials or not raw_report.strip():
        return raw_report

    try:
        bundle = create_response_client(settings)
        response = bundle.client.responses.create(
            model=bundle.model,
            input=build_user_report_polish_messages(raw_report=raw_report, itinerary_json=itinerary_json),
        )
        polished = getattr(response, "output_text", "") or ""
        return polished.strip() or raw_report
    except Exception:
        return raw_report


def build_frontend_response(
    *,
    conversation_id: str,
    run_result: ConversationRunResult,
    polish_user_report: bool = False,
) -> dict:
    itinerary_json = run_result.plan or {}
    if run_result.needs_clarification or not itinerary_json:
        user_friendly_report = run_result.answer
    else:
        user_friendly_report = generate_user_friendly_report(
            itinerary_json,
            run_result.state.latest_hotel_recommendations or {},
        )
        if polish_user_report:
            user_friendly_report = polish_user_friendly_report(user_friendly_report, itinerary_json)
    hotel_recommendations = run_result.state.latest_hotel_recommendations or {}
    cost_summary = (itinerary_json.get("conditions_context") or {}).get("cost_summary") or {}
    plan_cost_summary = build_plan_cost_summary(itinerary_json, hotel_recommendations)
    return {
        "conversation_id": conversation_id,
        "conversation_state": serialize_conversation_state(run_result.state),
        "user_profile": run_result.state.latest_user_profile,
        "itinerary_json": itinerary_json,
        "weather_payload": itinerary_json.get("weather_payload", {}),
        "strategy_summary": itinerary_json.get("strategy_summary", {}),
        "guide_references": itinerary_json.get("guide_references", []),
        "hotel_recommendations": hotel_recommendations,
        "user_friendly_report": user_friendly_report,
        "report": run_result.answer,
        "needs_clarification": run_result.needs_clarification,
        "missing_profile_slots": run_result.missing_profile_slots,
        "pending_profile_slots": run_result.state.pending_profile_slots,
        "tool_logs": run_result.tool_logs,
        "review_summary": itinerary_json.get("review_summary", ""),
        "review_findings": itinerary_json.get("review_findings", []),
        "replan_summary": itinerary_json.get("replan_summary", ""),
        "replan_metadata": itinerary_json.get("replan_metadata", {}),
        "map_payload": build_map_payload(itinerary_json),
        "cost_summary": cost_summary,
        "plan_cost_summary": plan_cost_summary,
    }
