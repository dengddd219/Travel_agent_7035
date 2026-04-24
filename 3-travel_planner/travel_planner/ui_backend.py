## author:SUN Bin
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from .agent import ConversationState, ConversationRunResult
from .city_names import city_name_bundle
from .config import Settings
from .data_store import load_city_profile
from .llm import create_response_client


DAY_COLORS = [
    "#0EA5E9",
    "#F97316",
    "#10B981",
    "#E11D48",
    "#8B5CF6",
]

FOOD_LABELS = {
    "hotpot": "火锅",
    "dan dan noodles": "担担面",
    "zhong dumplings": "钟水饺",
    "rabbit head": "兔头",
    "tea house snacks": "茶馆小吃",
    "soup dumplings": "汤包",
    "roast duck": "烤鸭",
    "morning tea": "早茶",
    "wonton noodles": "云吞面",
}


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


def _humanize_theme(raw_theme: str) -> str:
    return {
        "Leisure": "慢慢逛的城市体验",
        "Food-led day": "吃吃逛逛的一天",
        "Culture and city highlights": "文化和城市地标",
        "Scenic landmark day": "风景和地标体验",
    }.get(raw_theme, raw_theme or "城市体验")


def _humanize_food(food_name: str) -> str:
    return FOOD_LABELS.get(food_name.strip().lower(), food_name)


def _pick_day_foods(city_profile: dict, day_index: int) -> tuple[str, str]:
    foods = [_humanize_food(item) for item in city_profile.get("signature_foods", []) if str(item).strip()]
    if not foods:
        return ("当地人气小店", "本地口味馆子")
    lunch = foods[day_index % len(foods)]
    dinner = foods[(day_index + 1) % len(foods)] if len(foods) > 1 else foods[0]
    return lunch, dinner


def _day_strategy_note(day: dict, strategy_summary: dict, guide_references: list[str]) -> str:
    area = str(day.get("area", "")).strip().lower()
    stop_names = [str(item.get("poi_name", "")).strip() for item in day.get("items", []) if item.get("poi_name")]
    for note in strategy_summary.get("neighborhood_notes", []) or []:
        district = str(note.get("district", "")).strip().lower()
        note_text = str(note.get("note", "")).strip()
        if district and note_text and (district in area or area in district):
            return f"攻略里常把这一区一起玩，主要也是因为：{note_text}"
    for reference in guide_references:
        reference_text = str(reference).strip()
        lowered = reference_text.lower()
        if any(stop.lower() in lowered for stop in stop_names if stop):
            return f"这天我也参考了攻略里的说法：{reference_text}"
        if area and area in lowered:
            return f"这天我也参考了攻略里的说法：{reference_text}"
    if stop_names and strategy_summary.get("recommended_pois"):
        matched = [
            poi for poi in strategy_summary.get("recommended_pois", [])
            if any(poi.lower() in stop.lower() or stop.lower() in poi.lower() for stop in stop_names)
        ]
        if matched:
            return "这天优先保留了攻略里高频出现的点：" + "、".join(matched[:3])
    return ""


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


def _day_evening_suggestion(day: dict, city_profile: dict, travel_type: str) -> str:
    area = day.get("area", "核心区域")
    theme = str(day.get("theme", "")).lower()
    if "food" in theme:
        return f"晚饭后可以继续在{area}附近找夜宵、茶馆或者散步的街区，不用再跑太远。"
    if "culture" in theme:
        return f"吃完晚饭以后，比较适合在{area}附近再补一个夜景、老街或者轻松散步的点。"
    if "food" in travel_type:
        return f"晚饭后建议继续留在{area}附近逛吃，找夜市、小酒馆或者本地小吃会比较顺。"
    if "family" in travel_type:
        return f"晚上尽量留在{area}附近做轻松活动，比如商场、夜景步道，或者早点回酒店休息。"
    if city_profile.get("bad_weather_fallbacks"):
        return f"如果晚上临时下雨，也可以直接切到{area}附近的室内点，不用大改路线。"
    return f"晚饭后可以在{area}附近慢慢逛一圈，把夜景和本地生活气氛补上。"


def polish_user_friendly_report(raw_report: str, itinerary_json: dict) -> str:
    settings = Settings.from_env()
    if not settings.has_llm_credentials or not raw_report.strip():
        return raw_report

    try:
        bundle = create_response_client(settings)
        response = bundle.client.responses.create(
            model=bundle.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "你是一名旅行产品文案编辑。请把用户版行程说明润色成自然、统一、容易理解的简体中文。"
                        "要求：1. 不要中英文混用，专有景点名尽量转成常见中文；"
                        "2. 保留每天安排、天气、餐饮建议、攻略依据；"
                        "3. 语气像真人推荐，不要太硬，不要过度营销；"
                        "4. 不要使用 Markdown 标题或项目符号，输出 4 到 6 段自然短文即可。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"城市：{itinerary_json.get('city', '')}\n"
                        f"天数：{itinerary_json.get('trip_days', '')}\n"
                        f"请润色下面这段用户版说明：\n{raw_report}"
                    ),
                },
            ],
        )
        polished = getattr(response, "output_text", "") or ""
        return polished.strip() or raw_report
    except Exception:
        return raw_report


def build_user_friendly_report(itinerary_json: dict, hotel_recommendations: dict | None = None) -> str:
    city_info = city_name_bundle(itinerary_json.get("city", ""))
    city = city_info["city_zh"] or city_info["city_en"] or itinerary_json.get("city", "这座城市")
    city_profile = load_city_profile(city_info["canonical"] or itinerary_json.get("city", ""))
    trip_days = itinerary_json.get("trip_days", len(itinerary_json.get("days", [])))
    travel_type = str(itinerary_json.get("overview", "")).lower()
    trip_label = "轻松逛逛"
    if "food" in travel_type:
        trip_label = "吃喝逛吃"
    elif "family" in travel_type:
        trip_label = "亲子友好"
    elif "theme" in travel_type:
        trip_label = "主题体验"
    opening = f"我先帮你排了一版 {city}{trip_days}天的行程，整体会更偏{trip_label}，尽量让路线顺一点、节奏松一点，走起来不会太累。"
    guide_references = [str(item).strip() for item in itinerary_json.get("guide_references", []) if str(item).strip()]
    strategy_summary = itinerary_json.get("strategy_summary", {})
    weather_payload = itinerary_json.get("weather_payload", {})
    reference_intro = ""
    if guide_references:
        reference_intro = "我不是只按地图生排的，这版会参考攻略里反复提到的点和片区。"

    day_lines: list[str] = []
    for zero_based_index, day in enumerate(itinerary_json.get("days", [])):
        stop_names = [item.get("poi_name", "") for item in day.get("items", []) if item.get("poi_name")]
        if not stop_names:
            continue
        top_stops = "、".join(stop_names[:3])
        theme = _humanize_theme(str(day.get("theme", "当日路线")))
        lunch, dinner = _pick_day_foods(city_profile, zero_based_index)
        guide_note = _day_strategy_note(day, strategy_summary, guide_references)
        weather_sentence = _day_weather_sentence(weather_payload, zero_based_index)
        evening_note = _day_evening_suggestion(day, city_profile, travel_type)
        day_lines.append(
            " ".join(
                part
                for part in [
                    f"第{day.get('day_index', '?')}天我会建议你主要待在{day.get('area', '核心区域')}附近，这一天更偏{theme}，可以把 {top_stops} 串起来走。",
                    weather_sentence,
                    guide_note,
                    f"中午可以优先吃 {lunch}，尽量放在线路中段；晚上更适合安排 {dinner}，吃完就在附近继续逛。",
                    evening_note,
                ]
                if part
            )
        )

    review_summary = itinerary_json.get("review_summary", "")
    replan_summary = itinerary_json.get("replan_summary", "")
    budget = itinerary_json.get("total_estimated_cost", 0)
    closing_lines = [f"这版行程里，核心景点门票我先按大约 CNY {float(budget):.0f} 来估。"]
    if hotel_recommendations and hotel_recommendations.get("recommended_areas"):
        top_areas = "、".join(area.get("district", "") for area in hotel_recommendations["recommended_areas"][:2] if area.get("district"))
        if top_areas:
            closing_lines.append(f"如果你住宿还没定，优先住在 {top_areas} 会更顺路。")
    if review_summary:
        if "passed without major" in review_summary.lower():
            closing_lines.append("我已经顺手帮你检查过一轮，路线、天气和预算目前都没有特别明显的问题。")
        else:
            closing_lines.append(f"我这边又检查过一轮，目前需要你特别留意的是：{review_summary}")
    if replan_summary and "No automatic replan was needed" not in replan_summary:
        closing_lines.append("另外我已经自动帮你重排过一轮，最后保留的是更稳、更顺路的那个版本。")

    paragraphs = [opening]
    if reference_intro:
        paragraphs.append(reference_intro)
        paragraphs.append("我参考到的攻略信号包括：" + "；".join(guide_references[:3]) + "。")
    if strategy_summary.get("recommended_pois"):
        recommended = "、".join(strategy_summary.get("recommended_pois", [])[:4])
        paragraphs.append(f"所以这次我会优先把这些攻略里高频出现的点放进路线里：{recommended}。")
    if day_lines:
        paragraphs.append("\n".join(day_lines))
    paragraphs.append(" ".join(closing_lines))
    return "\n\n".join(part for part in paragraphs if part.strip())


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
        user_friendly_report = build_user_friendly_report(
            itinerary_json,
            run_result.state.latest_hotel_recommendations or {},
        )
        if polish_user_report:
            user_friendly_report = polish_user_friendly_report(user_friendly_report, itinerary_json)
    return {
        "conversation_id": conversation_id,
        "conversation_state": serialize_conversation_state(run_result.state),
        "user_profile": run_result.state.latest_user_profile,
        "itinerary_json": itinerary_json,
        "weather_payload": itinerary_json.get("weather_payload", {}),
        "strategy_summary": itinerary_json.get("strategy_summary", {}),
        "guide_references": itinerary_json.get("guide_references", []),
        "hotel_recommendations": run_result.state.latest_hotel_recommendations or {},
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
    }
