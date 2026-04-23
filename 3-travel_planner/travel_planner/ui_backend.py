from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from .agent import ConversationState, ConversationRunResult


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
        "turn_history": state.turn_history,
    }


def deserialize_conversation_state(payload: dict) -> ConversationState:
    return ConversationState(
        preference_memory=payload.get("preference_memory", {}),
        latest_user_profile=payload.get("latest_user_profile", payload.get("preference_memory", {})),
        latest_plan=payload.get("latest_plan"),
        latest_hotel_recommendations=payload.get("latest_hotel_recommendations"),
        latest_report=payload.get("latest_report", ""),
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
        "center": _plan_center(all_stops),
        "days": day_payloads,
        "all_stops": all_stops,
    }


def build_frontend_response(
    *,
    conversation_id: str,
    run_result: ConversationRunResult,
) -> dict:
    itinerary_json = run_result.plan or {}
    return {
        "conversation_id": conversation_id,
        "conversation_state": serialize_conversation_state(run_result.state),
        "user_profile": run_result.state.latest_user_profile,
        "itinerary_json": itinerary_json,
        "hotel_recommendations": run_result.state.latest_hotel_recommendations or {},
        "report": run_result.answer,
        "tool_logs": run_result.tool_logs,
        "review_summary": itinerary_json.get("review_summary", ""),
        "review_findings": itinerary_json.get("review_findings", []),
        "map_payload": build_map_payload(itinerary_json),
    }
