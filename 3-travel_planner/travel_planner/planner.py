## author:SUN Bin
from __future__ import annotations

"""Deterministic itinerary assembly.

This module intentionally does not try to "understand" the user in depth.
That semantic work should happen upstream in the LLM understanding layer.
Here we only:
- score candidate POIs
- arrange them into routeable day plans
- run lightweight review checks
- render the final report
"""

from collections import defaultdict
import math
import re

from .config import Settings
from .city_names import city_name_bundle, normalize_location_display_name, normalize_poi_display_name
from .models import DayPlan, DayPlanItem, ItineraryPlan, POI, ReviewFinding, UserPreferences, WeatherDay
from .tools.routing import optimize_route_order


BUDGET_PRICE_LEVEL_CAP = {"low": 2, "medium": 4, "high": 5}
PACE_SLOT_COUNT = {"slow": 3, "balanced": 4, "packed": 5}
SLOT_LABELS = ["morning", "morning", "afternoon", "evening", "evening"]
PACE_HOUR_CAP = {"slow": 6.0, "balanced": 8.5, "packed": 10.5}
CORE_ATTRACTION_DAY_BUDGET = {"low": 80.0, "medium": 180.0, "high": 320.0}
INTER_STOP_MIN_CAP = {"slow": 70, "balanced": 95, "packed": 125}
PACE_REPLAN_STEP = {"packed": "balanced", "balanced": "slow", "slow": "slow"}
SUPPORT_ONLY_ROLES = {"food", "optional_shop", "optional", "transit", "pitfall"}
ANCHOR_ROLES = {"anchor", "nearby_walk"}
MAX_SUPPORT_STOPS_PER_DAY = 1
NEARBY_CLUSTER_KM = 8.0
MAX_DISTRICTS_PER_DAY = 3
THIRD_DISTRICT_MAX_KM = 5.0
GENERIC_ROUTING_TIP = "Keep this stop grouped with nearby places instead of crossing the city just for one check-in."
GENERIC_RETRIEVAL_TIP = "Recommended by travel-guide retrieval."
TRAVEL_TYPE_LABELS_ZH = {
    "leisure": "轻松游",
    "family": "亲子游",
    "food": "美食游",
    "theme": "主题游",
}
BUDGET_LEVEL_LABELS_ZH = {
    "low": "低预算",
    "medium": "中等预算",
    "high": "高预算",
}
PACE_LABELS_ZH = {
    "slow": "慢节奏",
    "balanced": "适中",
    "packed": "紧凑",
}
TIME_SLOT_LABELS_ZH = {
    "morning": "上午",
    "afternoon": "下午",
    "evening": "晚上",
}
CATEGORY_LABELS_ZH = {
    "attraction": "景点",
    "food": "美食",
    "hotel": "酒店",
    "shopping": "顺路逛店",
}
TRAVELER_LABELS_ZH = {
    "friends": "朋友",
    "family": "家庭",
    "solo": "独自出行",
    "couple": "情侣",
}
DAY_THEME_LABELS_ZH = {
    "Food-led day": "美食主线",
    "Culture and city highlights": "文化与城市亮点",
    "Scenic landmark day": "风景地标日",
    "Leisure": "轻松游览",
    "Family": "亲子出行",
    "Food": "美食探索",
    "Theme": "主题体验",
    "Easy food and neighborhood time": "轻松吃逛",
    "Flexible family buffer": "亲子弹性安排",
    "Open theme extension": "主题延展日",
    "Flexible city wandering": "灵活城市漫游",
}
REASON_TRANSLATIONS_ZH = {
    "matches the stated interests": "符合你提到的兴趣偏好",
    "explicitly requested in must-visit list": "是你明确提出的必去点",
    "works well as a weather-safe anchor": "天气不稳时也适合作为稳妥安排",
    "fits the stronger outdoor weather window": "适合放在天气较好的户外时段",
    "supported by local tip signals": "也得到了本地提示信息支持",
    "repeatedly recommended in retrieved travel guides": "在检索到的攻略里被反复推荐",
    "sits in a neighborhood that the retrieved攻略 often clusters together": "所在片区在检索到的攻略里经常被安排在一起",
    "chosen for geographic fit and itinerary balance": "主要基于地理顺路和整体节奏平衡",
    "Suggested as a revisit option — original candidate pool was exhausted.": "作为回访或补位安排加入，因为原始候选点已经基本用完了",
    "Keep this stop grouped with nearby places instead of crossing the city just for one check-in.": "这个点更适合和附近地点一起安排，不建议为了单独打卡而跨区折返。",
}
REVIEW_TRANSLATIONS_ZH = {
    "Review passed without major routing, weather, or budget issues.": "这版行程在路线、天气和预算上没有明显问题。",
    "Review triggered one automatic replan pass and the safer version replaced the original draft.": "系统触发了一次自动重排，并采用了更稳妥的版本。",
    "Review triggered one automatic replan pass, but the original draft remained the better option after comparison.": "系统触发了一次自动重排，但对比后仍保留了原始版本。",
    "No automatic replan was needed because the first draft passed the review threshold.": "首版行程已经通过检查，因此没有触发自动重排。",
    "A post-planning review checks pace, weather fit, budget pressure, and route coherence.": "系统在出行程后，还会检查节奏、天气适配、预算压力和路线连贯性。",
    "RAG strategy signals now directly affect POI scoring, district priority, and route clustering.": "攻略检索信号会直接影响景点评分、片区优先级和路线聚类。",
    "Review triggered one automatic replan pass to reduce route, weather, or budget risks.": "系统做过一次自动重排，用来降低路线、天气或预算方面的风险。",
    "Planner groups stops by district first, then balances weather fit and preference match.": "规划器会先按片区聚类，再综合天气适配和偏好匹配来排点。",
    "High-risk weather days bias the plan toward indoor or mixed venues.": "如果某天的天气风险较高，行程会更偏向室内或可灵活切换的地点。",
    "Budget pressure lowers the priority of higher-cost attractions unless they are must-visit locations.": "在预算较紧时，高成本景点的优先级会降低，但必去点仍会保留。",
    "Within each day, stop order is optimized against real Amap route durations when coordinates and an Amap key are available.": "如果坐标和高德 Key 可用，系统会根据真实路程时间优化每天的游玩顺序。",
    "Move by district, not by attraction popularity alone.": "尽量按片区移动，不要只按热门程度在城市里来回穿梭。",
    "Book one signature meal and keep the rest flexible for neighborhood discoveries.": "可以先锁定一顿招牌餐，其余时间留给附近随走随吃的发现。",
    "Keep at least one low-effort indoor backup each day for children and sudden weather changes.": "每天最好预留一个轻松的室内备选点，方便照顾孩子和应对临时天气变化。",
    "Visit earlier in the day or near sunset to reduce queue risk while keeping better views.": "这类点更适合安排在上午或临近日落时段，能兼顾景色和排队压力。",
    "Pair market stops with nearby snack or dinner plans instead of treating them as stand-alone visits.": "逛市场类地点时，最好顺手搭配附近的小吃或正餐，不要单独只去这一个点。",
    "Use museums as bad-weather anchors and leave flexible time for nearby cafes or shopping streets.": "博物馆很适合当作坏天气时的核心安排，附近再留一点咖啡馆或逛街的弹性时间。",
    "Hangzhou works best when you leave room for scenic pauses and tea breaks.": "杭州更适合留出看景、喝茶和慢慢停下来的空档。",
    "Budget currently covers hotel, food, and local transport only.": "当前预算只覆盖酒店、餐饮和本地交通。",
    "Long-haul flights and attraction tickets remain outside this estimate unless another provider adds them.": "长途交通和景点门票暂未计入，除非后续有其他数据源补充。",
    "Matches the itinerary's highest-frequency districts.": "与当前行程最集中的活动片区最匹配。",
    "Hotels are ranked by itinerary district match first, then by price visibility and source quality.": "酒店优先按和行程片区的匹配度排序，其次参考价格可见性和数据来源质量。",
    "No live hotel candidates were returned, so use the recommended areas as the fallback stay guide.": "当前没有拿到实时酒店候选，可先按推荐住宿区域作为备选。",
}


def _normalize_text_items(items: list[str]) -> set[str]:
    # Normalize user preference lists once so matching stays consistent.
    return {item.strip().lower() for item in items if item.strip()}


def _poi_match_text(poi: POI) -> str:
    return " ".join(
        [
            poi.name,
            poi.category,
            " ".join(poi.tags),
            poi.visit_reason,
            poi.address,
        ]
    ).lower()


def _matches_preference_term(term: str, candidate_text: str) -> bool:
    normalized_term = str(term or "").strip().lower()
    normalized_candidate = str(candidate_text or "").strip().lower()
    if not normalized_term or not normalized_candidate:
        return False
    return normalized_term in normalized_candidate or normalized_candidate in normalized_term


def _poi_matches_term(poi: POI, term: str) -> bool:
    return _matches_preference_term(term, _poi_match_text(poi))


def _district_clusters(pois: list[POI]) -> dict[str, list[POI]]:
    grouped: dict[str, list[POI]] = defaultdict(list)
    for poi in pois:
        grouped[poi.district or "Unknown"].append(poi)
    return grouped


def _strategy_key(value: str) -> str:
    return normalize_poi_display_name(str(value or "").strip()).lower()


def _weather_lookup(weather: dict) -> list[WeatherDay]:
    return [WeatherDay.model_validate(item) for item in weather.get("forecast", [])]


def _weather_penalty(poi: POI, day_weather: WeatherDay | None) -> float:
    if not day_weather:
        return 0.0
    if poi.indoor_outdoor == "indoor" and day_weather.outdoor_suitability == "poor":
        return 1.2
    if poi.indoor_outdoor == "outdoor" and day_weather.outdoor_suitability == "poor":
        return -2.5
    if poi.indoor_outdoor == "outdoor" and day_weather.outdoor_suitability == "mixed":
        return -0.8
    if poi.indoor_outdoor == "indoor" and day_weather.outdoor_suitability == "good":
        return -0.2
    return 0.6


def _normalize_strategy_context(strategy_context: dict | None) -> dict:
    strategy_context = strategy_context or {}
    recommended_pois = {
        _strategy_key(str(item).strip())
        for item in strategy_context.get("recommended_pois", [])
        if str(item).strip()
    }
    theme_suggestions = {
        str(item).strip().lower()
        for item in strategy_context.get("theme_suggestions", [])
        if str(item).strip()
    }
    district_priority: dict[str, float] = {}
    poi_evidence: dict[str, dict[str, str]] = {}
    poi_roles: dict[str, str] = {
        _strategy_key(key): str(value).strip()
        for key, value in (strategy_context.get("poi_roles", {}) or {}).items()
        if str(key).strip() and str(value).strip()
    }
    pitfall_map: dict[str, str] = {}
    route_pair_hints: list[dict] = []
    cooccurrence_map: dict[str, set[str]] = defaultdict(set)

    for index, note in enumerate(strategy_context.get("neighborhood_notes", []) or []):
        district = str(note.get("district", "")).strip()
        if district:
            district_priority[district] = max(district_priority.get(district, 0.0), 3.0 - index * 0.5)

    for hint in strategy_context.get("route_pair_hints", []) or []:
        left = normalize_poi_display_name(str(hint.get("from", "")).strip())
        right = normalize_poi_display_name(str(hint.get("to", "")).strip())
        if not left or not right:
            continue
        left_key = _strategy_key(left)
        right_key = _strategy_key(right)
        cooccurrence_map[left_key].add(right_key)
        cooccurrence_map[right_key].add(left_key)
        route_pair_hints.append(
            {
                "from": left,
                "to": right,
                "strength": float(hint.get("strength", 0.0) or 0.0),
                "evidence": str(hint.get("evidence", "")).strip(),
                "source_title": str(hint.get("source_title", "")).strip(),
            }
        )

    for target, entries in (strategy_context.get("strategy_evidence_by_poi", {}) or {}).items():
        if not isinstance(entries, list):
            continue
        for evidence in entries:
            poi_name = normalize_poi_display_name(str(evidence.get("poi_name", target)).strip())
            key = _strategy_key(poi_name)
            if not key or key in poi_evidence:
                continue
            snippet = str(evidence.get("snippet", "")).strip()
            if len(snippet) > 90:
                snippet = snippet[:90].rstrip("，,；;、 ") + "…"
            companions = [
                normalize_poi_display_name(str(name).strip())
                for name in evidence.get("companions", []) or []
                if normalize_poi_display_name(str(name).strip())
            ][:4]
            role = str(evidence.get("role", "") or "").strip()
            if role and key not in poi_roles:
                poi_roles[key] = role
            poi_evidence[key] = {
                "title": str(evidence.get("source_title", "")).strip(),
                "snippet": snippet,
                "companions": "、".join(companions),
                "role": role,
            }

    for evidence in strategy_context.get("pitfall_evidence", []) or []:
        target = normalize_poi_display_name(str(evidence.get("target", "")).strip())
        key = _strategy_key(target)
        snippet = str(evidence.get("snippet", "")).strip()
        if key and snippet and key not in pitfall_map:
            pitfall_map[key] = snippet[:100]

    for result in strategy_context.get("results", []) or []:
        metadata = result.get("metadata", {}) or {}
        title = str(metadata.get("title", "")).strip()
        chunk_text = str(result.get("chunk_text", "")).strip()
        cleaned_text = re.sub(r"^【[^】]+】", "", chunk_text).strip()
        sentence_candidates = []
        for part in re.split(r"[。！？!?;\n]", cleaned_text):
            candidate = part.strip()
            if not candidate:
                continue
            if title and candidate == title:
                continue
            if len(candidate) < 8:
                continue
            sentence_candidates.append(candidate)
        for poi_name in metadata.get("poi_names", []) or []:
            normalized_name = normalize_poi_display_name(str(poi_name).strip())
            key = _strategy_key(normalized_name)
            if key and key not in poi_evidence:
                snippet = ""
                for candidate in sentence_candidates:
                    if normalized_name in candidate:
                        snippet = candidate
                        break
                if not snippet and sentence_candidates:
                    snippet = sentence_candidates[0]
                if len(snippet) > 48:
                    snippet = snippet[:48].rstrip("，,；;、 ") + "…"
                companions = [
                    normalize_poi_display_name(str(name).strip())
                    for name in metadata.get("poi_names", []) or []
                    if normalize_poi_display_name(str(name).strip()) and normalize_poi_display_name(str(name).strip()) != normalized_name
                ][:3]
                poi_evidence[key] = {
                    "title": title,
                    "snippet": snippet,
                    "companions": "、".join(companions),
                    "role": poi_roles.get(key, ""),
                }
    return {
        "recommended_pois": recommended_pois,
        "theme_suggestions": theme_suggestions,
        "district_priority": district_priority,
        "local_pitfalls": [str(item).strip() for item in strategy_context.get("local_pitfalls", []) if str(item).strip()],
        "poi_evidence": poi_evidence,
        "poi_roles": poi_roles,
        "route_pair_hints": route_pair_hints,
        "cooccurrence_map": cooccurrence_map,
        "pitfall_map": pitfall_map,
    }


def _strategy_role_for_poi(poi: POI, strategy_signals: dict) -> str:
    key = _strategy_key(poi.name)
    poi_roles = strategy_signals.get("poi_roles", {})
    role = poi_roles.get(key, "")
    if role:
        return role
    for strategy_poi_key, strategy_role in poi_roles.items():
        if strategy_poi_key and strategy_poi_key in key and len(strategy_poi_key) >= 2:
            return strategy_role
    evidence = strategy_signals.get("poi_evidence", {}).get(key, {})
    role = str(evidence.get("role", "") or "").strip()
    if role:
        return role
    for strategy_poi_key, strategy_evidence in strategy_signals.get("poi_evidence", {}).items():
        if strategy_poi_key and strategy_poi_key in key and len(strategy_poi_key) >= 2:
            role = str(strategy_evidence.get("role", "") or "").strip()
            if role:
                return role
    text = " ".join([poi.name, poi.category, poi.address, " ".join(poi.tags), poi.visit_reason]).lower()
    food_terms = ("food", "restaurant", "cafe", "coffee", "餐厅", "小吃", "火锅", "本帮", "融合菜", "咖啡", "茶")
    shop_terms = ("shop", "store", "mall", "market", "商店", "买手店", "书店", "商场", "百货")
    transit_terms = ("station", "airport", "停车", "地铁", "车站", "机场", "码头")
    if any(term in text for term in transit_terms):
        return "transit"
    if poi.category == "food" or any(term in text for term in food_terms):
        return "food"
    if any(term in text for term in shop_terms):
        return "optional_shop"
    return "anchor" if key in strategy_signals.get("recommended_pois", set()) else ""


def _is_support_only_poi(poi: POI, strategy_signals: dict, preferences: UserPreferences) -> bool:
    role = _strategy_role_for_poi(poi, strategy_signals)
    if role == "food" and preferences.travel_type == "food":
        return False
    return role in SUPPORT_ONLY_ROLES or poi.category == "hotel"


def _is_must_visit_poi(poi: POI, must_visit: set[str]) -> bool:
    return any(_poi_matches_term(poi, must) for must in must_visit)


def _poi_distance_km(left: POI, right: POI) -> float | None:
    if not left.lat or not left.lon or not right.lat or not right.lon:
        return None
    radius_km = 6371.0
    lat1 = math.radians(left.lat)
    lat2 = math.radians(right.lat)
    dlat = lat2 - lat1
    dlon = math.radians(right.lon - left.lon)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _related_to_chosen(poi: POI, chosen_pois: list[POI], strategy_signals: dict) -> tuple[bool, float]:
    """Return (is_related, km_to_nearest_chosen)."""
    if not chosen_pois:
        return False, float("inf")
    key = _strategy_key(poi.name)
    cooccurrence = strategy_signals.get("cooccurrence_map", {})
    nearest_km = float("inf")
    has_cooccurrence = False
    for chosen in chosen_pois:
        chosen_key = _strategy_key(chosen.name)
        if key in cooccurrence.get(chosen_key, set()) or chosen_key in cooccurrence.get(key, set()):
            has_cooccurrence = True
        distance = _poi_distance_km(poi, chosen)
        if distance is not None:
            nearest_km = min(nearest_km, distance)
    is_related = has_cooccurrence or nearest_km <= NEARBY_CLUSTER_KM
    return is_related, nearest_km


def _score_poi(
    poi: POI,
    preferences: UserPreferences,
    focus_tags: set[str],
    must_visit: set[str],
    avoid: set[str],
    city_tip_map: dict[str, str],
    strategy_signals: dict,
) -> float:
    # The planner scores candidates using already-structured preferences plus
    # retrieval evidence. It should not reinterpret the user's raw message here.
    name_key = poi.name.lower()
    strategy_match_text = " ".join(
        [
            poi.name,
            " ".join(poi.tags),
            poi.visit_reason,
            poi.address,
        ]
    ).lower()
    if any(_poi_matches_term(poi, avoid_item) for avoid_item in avoid):
        return -999.0

    score = 1.0
    role = _strategy_role_for_poi(poi, strategy_signals)
    if role == "transit":
        score -= 6.0
    if role == "pitfall" and not _is_must_visit_poi(poi, must_visit):
        score -= 3.5
    if role == "anchor":
        score += 2.2
    elif role == "nearby_walk":
        score += 1.2
    elif role == "optional_shop":
        score -= 1.6
    elif role == "optional":
        score -= 0.8
    elif role == "food":
        score += 1.4 if preferences.travel_type == "food" else -2.2
    if strategy_signals.get("poi_evidence", {}).get(_strategy_key(poi.name)):
        score += 0.8
    if any(_poi_matches_term(poi, must) for must in must_visit):
        score += 4.5
    if any(interest.lower() in " ".join(poi.tags).lower() or interest.lower() in name_key for interest in preferences.interests):
        score += 1.8
    if any(tag in focus_tags for tag in poi.tags):
        score += 1.3
    if poi.category == "food" and preferences.travel_type == "food":
        score += 1.8
    if poi.category == "food" and preferences.travel_type != "food":
        score -= 0.2
    if poi.category == "hotel":
        score -= 2.0
    if poi.price_level > BUDGET_PRICE_LEVEL_CAP.get(preferences.budget_level, 4):
        score -= 1.6
    if poi.ticket_price == 0:
        score += 0.4
    if city_tip_map.get(name_key):
        score += 0.6
    if any(
        recommended in strategy_match_text or name_key in recommended
        for recommended in strategy_signals["recommended_pois"]
    ):
        score += 3.2 if role not in {"food", "optional_shop", "optional"} else 0.8
    if any(tag in strategy_match_text or tag in name_key for tag in strategy_signals["theme_suggestions"]):
        score += 1.6
    score += strategy_signals["district_priority"].get(poi.district, 0.0)
    if poi.rating:
        score += min(1.0, poi.rating / 5.0)
    return score


def _select_pois(
    preferences: UserPreferences,
    pois: list[POI],
    focus_tags: set[str],
    city_tip_map: dict[str, str],
    strategy_signals: dict,
) -> list[POI]:
    # Select a trip-sized pool before day allocation so later routing works on a
    # bounded set of candidates instead of the full search result list.
    must_visit = _normalize_text_items(preferences.must_visit)
    avoid = _normalize_text_items(preferences.avoid)
    scored = sorted(
        pois,
        key=lambda poi: _score_poi(poi, preferences, focus_tags, must_visit, avoid, city_tip_map, strategy_signals),
        reverse=True,
    )

    selected: list[POI] = []
    seen: set[str] = set()
    base_target = preferences.trip_days * PACE_SLOT_COUNT[preferences.pace]
    target_count = min(max(base_target, preferences.trip_days * 3), max(24, preferences.trip_days * 4))

    for poi in scored:
        name_key = poi.name.lower()
        if name_key in seen:
            continue
        support_count = sum(1 for selected_poi in selected if _is_support_only_poi(selected_poi, strategy_signals, preferences))
        if (
            _is_support_only_poi(poi, strategy_signals, preferences)
            and support_count >= preferences.trip_days
            and not any(_poi_matches_term(poi, must) for must in must_visit)
        ):
            continue
        if len(selected) >= target_count:
            break
        seen.add(name_key)
        selected.append(poi)

    # Guarantee must-visit POIs if present in the candidate pool.
    for poi in scored:
        if not must_visit:
            break
        name_key = poi.name.lower()
        if any(_poi_matches_term(poi, must) for must in must_visit) and name_key not in seen:
            selected.append(poi)
            seen.add(name_key)

    return selected


def _allocate_days(
    preferences: UserPreferences,
    selected_pois: list[POI],
    weather_days: list[WeatherDay],
    city_context: dict,
    tips_map: dict[str, str],
    strategy_signals: dict,
    settings: Settings | None = None,
) -> list[DayPlan]:
    # Day allocation stays intentionally geometric:
    # cluster by district first, then let weather and guide evidence bias order.
    settings = settings or Settings.from_env()
    grouped = _district_clusters(selected_pois)
    districts = sorted(
        grouped.keys(),
        key=lambda key: (strategy_signals["district_priority"].get(key, 0.0), len(grouped[key])),
        reverse=True,
    )
    used: set[str] = set()
    plans: list[DayPlan] = []

    for day_index in range(preferences.trip_days):
        weather_day = weather_days[min(day_index, max(len(weather_days) - 1, 0))] if weather_days else None
        preferred_slots = PACE_SLOT_COUNT[preferences.pace]
        remaining_unused = [poi for poi in selected_pois if poi.name not in used]
        must_visit = _normalize_text_items(preferences.must_visit)
        remaining_days = preferences.trip_days - day_index
        if not remaining_unused:
            # Recycle POIs with lowest scores rather than leaving the day blank.
            # This ensures multi-day itineraries always have content on every day.
            recycled = selected_pois[:preferred_slots] if selected_pois else []
            recycled_items = [
                DayPlanItem(
                    time_slot=["morning", "afternoon", "evening"][i % 3],
                    poi_name=poi.name,
                    category=poi.category,
                    district=poi.district,
                    duration_hours=poi.duration_hours,
                    est_cost=poi.ticket_price or 0.0,
                    transport_hint="Revisit or explore nearby options.",
                    arrival_mode="start" if i == 0 else "walk",
                    arrival_distance_m=0,
                    arrival_duration_min=0,
                    reasoning="Suggested as a revisit option — original candidate pool was exhausted.",
                    weather_fit="flexible mixed-environment stop.",
                )
                for i, poi in enumerate(recycled)
            ]
            plans.append(
                DayPlan(
                    day_index=day_index + 1,
                    area=districts[min(day_index, len(districts) - 1)] if districts else preferences.city,
                    theme=_empty_day_theme(preferences.travel_type),
                    estimated_cost=round(sum(item.est_cost for item in recycled_items), 2),
                    weather_summary=weather_day.summary if weather_day else "",
                    inter_stop_distance_m=0,
                    inter_stop_duration_min=0,
                    items=recycled_items,
                    notes=["All unique candidates covered; this day suggests revisiting highlights or exploring nearby spots."],
                )
            )
            continue
        min_reserved_for_future = max(0, remaining_days - 1)
        max_slots_today = min(preferred_slots, max(1, len(remaining_unused) - min_reserved_for_future))

        if day_index < len(districts):
            main_district = districts[day_index]
        else:
            main_district = remaining_unused[0].district if remaining_unused else (districts[0] if districts else preferences.city)

        district_candidates = [poi for poi in grouped.get(main_district, []) if poi.name not in used]
        if not district_candidates:
            district_candidates = [poi for poi in selected_pois if poi.name not in used]

        def weather_sort_key(poi: POI) -> float:
            strategy_boost = 0.0
            name_key = poi.name.lower()
            role = _strategy_role_for_poi(poi, strategy_signals)
            if any(recommended in name_key or name_key in recommended for recommended in strategy_signals["recommended_pois"]):
                strategy_boost += 2.5 if role not in {"food", "optional_shop", "optional"} else 0.6
            if any(tag in " ".join(poi.tags).lower() or tag in name_key for tag in strategy_signals["theme_suggestions"]):
                strategy_boost += 1.2
            if role == "anchor":
                strategy_boost += 1.8
            elif role == "nearby_walk":
                strategy_boost += 1.0
            elif role == "food" and preferences.travel_type != "food":
                strategy_boost -= 2.0
            elif role in {"optional_shop", "optional", "transit", "pitfall"}:
                strategy_boost -= 1.4
            # cooccurrence_boost: reward POIs that share route_pair with top candidates
            cooccurrence = strategy_signals.get("cooccurrence_map", {})
            poi_key = _strategy_key(poi.name)
            reference_names = [_strategy_key(p.name) for p in district_candidates[:2]]
            if any(
                poi_key in cooccurrence.get(ref, set()) or ref in cooccurrence.get(poi_key, set())
                for ref in reference_names
            ):
                strategy_boost += 0.8
            strategy_boost += strategy_signals["district_priority"].get(poi.district, 0.0)
            return _weather_penalty(poi, weather_day) + strategy_boost

        district_candidates.sort(key=weather_sort_key, reverse=True)
        chosen_pois: list[POI] = []

        for slot_index in range(max_slots_today):
            if not district_candidates:
                # Pull backup candidates from elsewhere if this district is exhausted.
                backup = [poi for poi in selected_pois if poi.name not in used]
                chosen_districts = {poi.district for poi in chosen_pois if poi.district}
                chosen_districts.add(main_district)
                support_count = sum(1 for poi in chosen_pois if _is_support_only_poi(poi, strategy_signals, preferences))
                filtered_backup = []
                for candidate in backup:
                    is_must = _is_must_visit_poi(candidate, must_visit)
                    support_only = _is_support_only_poi(candidate, strategy_signals, preferences)
                    if not chosen_pois and support_only and not is_must:
                        continue
                    if support_only and support_count >= MAX_SUPPORT_STOPS_PER_DAY and not is_must:
                        continue
                    if is_must:
                        filtered_backup.append(candidate)
                        continue
                    if candidate.district in chosen_districts:
                        filtered_backup.append(candidate)
                        continue
                    new_district_count = len(chosen_districts) + (0 if candidate.district in chosen_districts else 1)
                    if new_district_count > MAX_DISTRICTS_PER_DAY:
                        continue
                    is_related, nearest_km = _related_to_chosen(candidate, chosen_pois, strategy_signals)
                    if not is_related:
                        continue
                    if new_district_count == MAX_DISTRICTS_PER_DAY:
                        cooccurrence = strategy_signals.get("cooccurrence_map", {})
                        poi_key = _strategy_key(candidate.name)
                        has_cooccurrence = any(
                            poi_key in cooccurrence.get(_strategy_key(chosen.name), set())
                            or _strategy_key(chosen.name) in cooccurrence.get(poi_key, set())
                            for chosen in chosen_pois
                        )
                        if nearest_km > THIRD_DISTRICT_MAX_KM or not has_cooccurrence:
                            continue
                    filtered_backup.append(candidate)
                if filtered_backup:
                    backup = filtered_backup
                backup.sort(key=weather_sort_key, reverse=True)
                district_candidates = backup
            if not district_candidates:
                break

            if not chosen_pois:
                anchor_index = next(
                    (
                        index
                        for index, candidate in enumerate(district_candidates)
                        if not _is_support_only_poi(candidate, strategy_signals, preferences)
                        or _is_must_visit_poi(candidate, must_visit)
                    ),
                    0,
                )
                poi = district_candidates.pop(anchor_index)
            else:
                poi = district_candidates.pop(0)
            used.add(poi.name)
            chosen_pois.append(poi)

        plans.append(
            _build_day_plan(
                day_index=day_index,
                main_district=main_district,
                ordered_pois=chosen_pois,
                weather_day=weather_day,
                preferences=preferences,
                city_context=city_context,
                tips_map=tips_map,
                strategy_signals=strategy_signals,
                settings=settings,
            )
        )

    return plans


def _compose_reasoning(
    poi: POI,
    preferences: UserPreferences,
    weather_day: WeatherDay | None,
    tips_map: dict[str, str],
    strategy_signals: dict,
) -> str:
    reasons = []
    if preferences.must_visit and any(item.lower() in poi.name.lower() for item in preferences.must_visit):
        reasons.append("这是你明确提出的必去点")
    if any(interest.lower() in poi.name.lower() or interest.lower() in " ".join(poi.tags).lower() for interest in preferences.interests):
        reasons.append("和你提到的兴趣偏好一致")
    if weather_day:
        if poi.indoor_outdoor == "indoor" and weather_day.outdoor_suitability != "good":
            reasons.append("这一天天气一般，安排这里会更稳妥")
        elif poi.indoor_outdoor == "outdoor" and weather_day.outdoor_suitability == "good":
            reasons.append("当天更适合安排户外点，这里能吃到较好的天气窗口")
    if tips_map.get(poi.name.lower()):
        local_tip = tips_map.get(poi.name.lower(), "").strip()
        if local_tip in {GENERIC_RETRIEVAL_TIP, GENERIC_ROUTING_TIP}:
            local_tip = ""
        else:
            local_tip = local_tip.replace(
                GENERIC_ROUTING_TIP,
                "这个点更适合和附近地点一起安排，不建议为了单独打卡而跨区折返。",
            )
        local_tip = re.split(r"[。！？!?;\n]", local_tip, maxsplit=1)[0].strip()
        if local_tip:
            reasons.append(f"本地提示里也特别提到：{local_tip}")
    name_key = poi.name.lower()
    strategy_key = _strategy_key(poi.name)
    role = _strategy_role_for_poi(poi, strategy_signals)
    evidence = strategy_signals.get("poi_evidence", {}).get(strategy_key)
    if evidence:
        title = evidence.get("title", "")
        snippet = evidence.get("snippet", "")
        companions = evidence.get("companions", "")
        if role == "anchor":
            reasons.append("它是攻略路线里的核心停靠点")
        elif role == "nearby_walk":
            reasons.append("它适合和同片区点位一起顺路串联")
        elif role == "food" and preferences.travel_type == "food":
            reasons.append("它可作为这天的本地餐饮重点")
        if title and companions:
            reasons.append(f"攻略《{title}》把它和{companions}放在同一条路线里")
        elif title:
            reasons.append(f"攻略《{title}》把这里放进了推荐路线")
        elif snippet:
            reasons.append("检索到的攻略证据支持这个安排")
    elif any(recommended in name_key or name_key in recommended for recommended in strategy_signals["recommended_pois"]):
        reasons.append("在检索到的攻略里被多次提到")
    if poi.district in strategy_signals["district_priority"]:
        reasons.append("它所在的片区经常和当天其他点位一起被安排，路线更顺")
    return "；".join(reasons) or "主要基于地理顺路和整体节奏平衡"


def _guide_fields_for_poi(poi: POI, strategy_signals: dict) -> dict[str, str]:
    evidence = strategy_signals.get("poi_evidence", {}).get(_strategy_key(poi.name), {})
    pitfall = strategy_signals.get("pitfall_map", {}).get(_strategy_key(poi.name), "")
    role = _strategy_role_for_poi(poi, strategy_signals)
    snippet = str(evidence.get("snippet", "") or "").strip()
    source = str(evidence.get("title", "") or "").strip()
    local_note = ""
    if role == "food":
        local_note = "作为餐饮或休息点处理，建议贴近当天路线安排，不要单独跨区前往。"
    elif role == "optional_shop":
        local_note = "这是顺路逛店点，适合有余力时加入，不建议压过主景点。"
    elif role == "nearby_walk":
        local_note = "更适合作为同片区步行串联点，减少跨区折返。"
    elif role == "anchor":
        local_note = "可作为当天主轴停靠点，再搭配附近顺路点。"
    return {
        "guide_evidence": snippet,
        "guide_source": source,
        "local_note": local_note,
        "pitfall_note": pitfall,
    }


def _category_for_plan_item(poi: POI, strategy_signals: dict) -> str:
    role = _strategy_role_for_poi(poi, strategy_signals)
    if role == "food":
        return "food"
    if role == "optional_shop":
        return "shopping"
    return poi.category


def _weather_fit_text(poi: POI, weather_day: WeatherDay | None) -> str:
    if not weather_day:
        return "No weather constraint applied."
    if poi.indoor_outdoor == "indoor":
        return f"{weather_day.summary}: indoor-friendly choice."
    if poi.indoor_outdoor == "outdoor":
        return f"{weather_day.summary}: outdoor plan, monitor rain risk."
    return f"{weather_day.summary}: flexible mixed-environment stop."


def _day_theme(items: list[DayPlanItem], travel_type: str) -> str:
    if not items:
        return travel_type.title()
    categories = [item.category for item in items]
    if categories.count("food") >= max(1, len(categories) // 2):
        return "Food-led day"
    if any(item.category == "attraction" and "museum" in item.poi_name.lower() for item in items):
        return "Culture and city highlights"
    if any(item.category == "attraction" for item in items):
        return "Scenic landmark day"
    return travel_type.title()


def _empty_day_theme(travel_type: str) -> str:
    if travel_type == "food":
        return "Easy food and neighborhood time"
    if travel_type == "family":
        return "Flexible family buffer"
    if travel_type == "theme":
        return "Open theme extension"
    return "Flexible city wandering"


def _build_day_plan(
    *,
    day_index: int,
    main_district: str,
    ordered_pois: list[POI],
    weather_day: WeatherDay | None,
    preferences: UserPreferences,
    city_context: dict,
    tips_map: dict[str, str],
    strategy_signals: dict,
    settings: Settings,
) -> DayPlan:
    # Route within a day after the candidate set is fixed. This keeps the
    # routing adapter separate from semantic preference understanding.
    route_plan = optimize_route_order(
        [poi.model_dump() for poi in ordered_pois],
        must_visit_names=_normalize_text_items(preferences.must_visit),
        settings=settings,
    )
    reordered_pois = [ordered_pois[index] for index in route_plan["ordered_indices"]]

    items: list[DayPlanItem] = []
    for slot_index, poi in enumerate(reordered_pois):
        guide_fields = _guide_fields_for_poi(poi, strategy_signals)
        if slot_index == 0:
            arrival_mode = "start"
            arrival_distance_m = 0
            arrival_duration_min = 0
            transport_hint = f"Start the day in {poi.district}."
        else:
            leg = route_plan["legs"][slot_index - 1]
            arrival_mode = leg["mode"]
            arrival_distance_m = int(leg["distance_m"])
            arrival_duration_min = int(leg["duration_min"])
            distance_km = arrival_distance_m / 1000
            transport_hint = (
                f"{leg['mode'].title()} about {arrival_duration_min} min ({distance_km:.1f} km). {leg['instruction']}"
            )

        items.append(
            DayPlanItem(
                time_slot=SLOT_LABELS[min(slot_index, len(SLOT_LABELS) - 1)],
                poi_name=poi.name,
                category=_category_for_plan_item(poi, strategy_signals),
                district=poi.district,
                duration_hours=poi.duration_hours,
                est_cost=poi.ticket_price,
                reasoning=_compose_reasoning(poi, preferences, weather_day, tips_map, strategy_signals),
                weather_fit=_weather_fit_text(poi, weather_day),
                transport_hint=transport_hint,
                arrival_mode=arrival_mode,
                arrival_distance_m=arrival_distance_m,
                arrival_duration_min=arrival_duration_min,
                guide_evidence=guide_fields["guide_evidence"],
                local_note=guide_fields["local_note"],
                pitfall_note=guide_fields["pitfall_note"],
                guide_source=guide_fields["guide_source"],
            )
        )

    day_cost = round(sum(item.est_cost for item in items), 2)
    day_notes = []
    if weather_day:
        day_notes.extend(weather_day.suggestions[:1])
    if day_index == 0 and city_context.get("pace_note"):
        day_notes.append(city_context["pace_note"])
    if route_plan["total_duration_min"]:
        day_notes.append(
            f"Inter-stop travel time is about {route_plan['total_duration_min']} min across {route_plan['total_distance_m'] / 1000:.1f} km."
        )

    return DayPlan(
        day_index=day_index + 1,
        area=main_district,
        theme=_day_theme(items, preferences.travel_type),
        estimated_cost=day_cost,
        weather_summary=weather_day.summary if weather_day else "",
        inter_stop_distance_m=int(route_plan["total_distance_m"]),
        inter_stop_duration_min=int(route_plan["total_duration_min"]),
        items=items,
        notes=day_notes,
    )


def _contains_requested_place(place_name: str, candidate_names: list[str]) -> bool:
    place_key = place_name.strip().lower()
    return any(_matches_preference_term(place_key, candidate) for candidate in candidate_names)


def review_itinerary(plan: dict, user_profile: dict, weather: dict) -> dict:
    itinerary = ItineraryPlan.model_validate(plan)
    preferences = UserPreferences.model_validate(user_profile)
    weather_days = _weather_lookup(weather)
    findings: list[ReviewFinding] = []

    # Hard constraint 1: city must match.
    if itinerary.city and preferences.city and itinerary.city.lower() != preferences.city.lower():
        findings.append(
            ReviewFinding(
                level="error",
                rule="city_mismatch",
                message=(
                    f"Itinerary city '{itinerary.city}' does not match requested city '{preferences.city}'. "
                    "The plan must be regenerated for the correct destination."
                ),
            )
        )

    # Hard constraint 2: day count must match.
    actual_days = len(itinerary.days)
    if actual_days != preferences.trip_days:
        findings.append(
            ReviewFinding(
                level="error",
                rule="day_count_mismatch",
                message=(
                    f"Itinerary has {actual_days} day(s) but user requested {preferences.trip_days} day(s). "
                    "The plan must be extended or regenerated to cover the full trip."
                ),
            )
        )

    scheduled_names = [item.poi_name for day in itinerary.days for item in day.items]
    missing_must_visit = [
        place
        for place in preferences.must_visit
        if not _contains_requested_place(place, scheduled_names)
    ]
    if missing_must_visit:
        findings.append(
            ReviewFinding(
                level="warning",
                rule="must_visit_coverage",
                message=(
                    "These must-visit requests are not clearly covered in the scheduled stops: "
                    + ", ".join(missing_must_visit)
                    + "."
                ),
            )
        )

    violated_avoid = [
        place
        for place in preferences.avoid
        if _contains_requested_place(place, scheduled_names)
    ]
    if violated_avoid:
        findings.append(
            ReviewFinding(
                level="warning",
                rule="avoid_violation",
                message=(
                    "These avoided places or patterns still appear in the scheduled stops: "
                    + ", ".join(violated_avoid)
                    + "."
                ),
            )
        )

    for index, day in enumerate(itinerary.days):
        day_weather = weather_days[min(index, len(weather_days) - 1)] if weather_days else None
        active_hours = round(sum(item.duration_hours for item in day.items) + day.inter_stop_duration_min / 60.0, 1)
        district_count = len({item.district for item in day.items if item.district})
        outdoor_items = [item.poi_name for item in day.items if "outdoor" in item.weather_fit.lower()]

        if active_hours > PACE_HOUR_CAP[preferences.pace]:
            findings.append(
                ReviewFinding(
                    level="warning",
                    rule="pace_balance",
                    message=(
                        f"Day {day.day_index} looks heavy for a {preferences.pace} pace "
                        f"at about {active_hours} hours including transit."
                    ),
                )
            )

        if district_count >= 3:
            findings.append(
                ReviewFinding(
                    level="warning",
                    rule="district_spread",
                    message=(
                        f"Day {day.day_index} spans {district_count} districts, which may feel fragmented."
                    ),
                )
            )

        if day.inter_stop_duration_min > INTER_STOP_MIN_CAP[preferences.pace]:
            findings.append(
                ReviewFinding(
                    level="warning",
                    rule="route_efficiency",
                    message=(
                        f"Day {day.day_index} spends about {day.inter_stop_duration_min} minutes in inter-stop travel; "
                        "consider tightening the cluster."
                    ),
                )
            )

        if day.estimated_cost > CORE_ATTRACTION_DAY_BUDGET[preferences.budget_level]:
            findings.append(
                ReviewFinding(
                    level="warning",
                    rule="budget_pressure",
                    message=(
                        f"Day {day.day_index} has about {day.estimated_cost:.0f} in core attraction spend, "
                        f"which is high for a {preferences.budget_level} budget."
                    ),
                )
            )

        if day_weather and day_weather.outdoor_suitability == "poor" and outdoor_items:
            findings.append(
                ReviewFinding(
                    level="warning",
                    rule="weather_fit",
                    message=(
                        f"Day {day.day_index} has poor outdoor weather but still includes outdoor-heavy stops: "
                        + ", ".join(outdoor_items)
                        + "."
                    ),
                )
            )

    if findings:
        summary = f"Review flagged {len(findings)} itinerary risks that may need adjustment."
    else:
        summary = "Review passed without major routing, weather, or budget issues."

    return {
        "summary": summary,
        "findings": [finding.model_dump() for finding in findings],
    }


def _warning_count(review: dict) -> int:
    return sum(1 for finding in review.get("findings", []) if finding.get("level") == "warning")


def _generate_plan_once(
    preferences: UserPreferences,
    pois: list[POI],
    weather: dict,
    city_context: dict,
    travel_tips: dict,
    strategy_context: dict | None = None,
    settings: Settings | None = None,
) -> ItineraryPlan:
    weather_days = _weather_lookup(weather)
    city_tip_map = {
        entry.get("poi_name", "").strip().lower(): entry.get("tip", "")
        for entry in travel_tips.get("tips", [])
        if entry.get("poi_name")
    }
    strategy_signals = _normalize_strategy_context(strategy_context)

    focus_tags = {tag.lower() for tag in city_context.get("focus_tags", [])}
    focus_tags.update(strategy_signals["theme_suggestions"])
    selected_pois = _select_pois(preferences, pois, focus_tags, city_tip_map, strategy_signals)
    days = _allocate_days(preferences, selected_pois, weather_days, city_context, city_tip_map, strategy_signals, settings=settings)
    total_cost = round(sum(day.estimated_cost for day in days), 2)

    return ItineraryPlan(
        city=preferences.city,
        trip_days=preferences.trip_days,
        overview=(
            f"A {preferences.trip_days}-day {preferences.travel_type} itinerary in {preferences.city} "
            f"with a {preferences.pace} pace and {preferences.budget_level} budget profile."
        ),
        total_estimated_cost=total_cost,
        selected_pois=selected_pois,
        days=days,
        planning_notes=[
            "Planner groups stops by district first, then balances weather fit and preference match.",
            "High-risk weather days bias the plan toward indoor or mixed venues.",
            "Budget pressure lowers the priority of higher-cost attractions unless they are must-visit locations.",
            "Within each day, stop order is optimized against real Amap route durations when coordinates and an Amap key are available.",
        ],
        local_tips=[entry.get("tip", "") for entry in travel_tips.get("tips", [])[:6] if entry.get("tip")],
    )


def _prepare_replan_preferences(preferences: UserPreferences, review: dict) -> UserPreferences:
    warning_rules = {finding.get("rule") for finding in review.get("findings", [])}
    updated = preferences.model_copy(deep=True)
    if warning_rules & {"pace_balance", "route_efficiency", "district_spread"}:
        updated.pace = PACE_REPLAN_STEP.get(preferences.pace, preferences.pace)
    return updated


def _prepare_replan_candidates(
    pois: list[POI],
    preferences: UserPreferences,
    review: dict,
    weather: dict,
) -> list[POI]:
    warning_rules = {finding.get("rule") for finding in review.get("findings", [])}
    must_visit = _normalize_text_items(preferences.must_visit)
    avoid = _normalize_text_items(preferences.avoid)
    allow_outdoor = "weather_fit" not in warning_rules
    allow_high_cost = "budget_pressure" not in warning_rules
    poor_weather_days = any(day.outdoor_suitability == "poor" for day in _weather_lookup(weather))
    budget_cap = CORE_ATTRACTION_DAY_BUDGET[preferences.budget_level]

    filtered: list[POI] = []
    for poi in pois:
        name_key = poi.name.strip().lower()
        is_must_visit = any(_poi_matches_term(poi, must) for must in must_visit)
        if any(_poi_matches_term(poi, avoid_item) for avoid_item in avoid):
            continue
        if not allow_outdoor and poor_weather_days and poi.indoor_outdoor == "outdoor" and not is_must_visit:
            continue
        if not allow_high_cost and poi.ticket_price > budget_cap * 0.6 and not is_must_visit:
            continue
        filtered.append(poi)

    return filtered or pois


def plan_itinerary(
    user_profile: dict,
    candidate_pois: list[dict],
    weather: dict,
    city_context: dict,
    travel_tips: dict,
    strategy_context: dict | None = None,
    settings: Settings | None = None,
) -> dict:
    preferences = UserPreferences.model_validate(user_profile)
    pois = [POI.model_validate(item) for item in candidate_pois]
    plan = _generate_plan_once(preferences, pois, weather, city_context, travel_tips, strategy_context=strategy_context, settings=settings)
    review = review_itinerary(plan.model_dump(), user_profile=user_profile, weather=weather)

    replan_attempted = False
    replanned = False
    if _warning_count(review) > 0:
        replan_attempted = True
        replan_preferences = _prepare_replan_preferences(preferences, review)
        replan_pois = _prepare_replan_candidates(pois, preferences, review, weather)
        replan_plan = _generate_plan_once(
            replan_preferences,
            replan_pois,
            weather,
            city_context,
            travel_tips,
            strategy_context=strategy_context,
            settings=settings,
        )
        replan_review = review_itinerary(
            replan_plan.model_dump(),
            user_profile=replan_preferences.model_dump(),
            weather=weather,
        )
        if _warning_count(replan_review) < _warning_count(review):
            plan = replan_plan
            review = replan_review
            replanned = True

    plan.review_summary = review["summary"]
    plan.review_findings = [ReviewFinding.model_validate(item) for item in review["findings"]]
    plan.planning_notes.append("A post-planning review checks pace, weather fit, budget pressure, and route coherence.")
    if strategy_context:
        plan.planning_notes.append("RAG strategy signals now directly affect POI scoring, district priority, and route clustering.")
    warning_rules = sorted({finding.get("rule") for finding in review.get("findings", []) if finding.get("rule")})
    plan.replan_metadata = {
        "attempted": replan_attempted,
        "applied": replanned,
        "trigger_rules": warning_rules,
    }
    if replan_attempted and replanned:
        plan.replan_summary = "Review triggered one automatic replan pass and the safer version replaced the original draft."
        plan.planning_notes.append(
            "Review triggered one automatic replan pass to reduce route, weather, or budget risks."
        )
    elif replan_attempted:
        plan.replan_summary = "Review triggered one automatic replan pass, but the original draft remained the better option after comparison."
        plan.planning_notes.append(
            "Review triggered one automatic replan pass, but the original draft remained the better option after comparison."
        )
    else:
        plan.replan_summary = "No automatic replan was needed because the first draft passed the review threshold."
    return plan.model_dump()


_REPORT_LABELS_ZH = {
    "title_suffix": "智能旅行规划",
    "trip_style": "出行风格",
    "travelers": "同行人员",
    "budget": "预算等级",
    "pace": "行程节奏",
    "est_cost": "景点费用预估",
    "planning_summary": "规划摘要",
    "itinerary": "每日行程",
    "day": "第 {n} 天",
    "theme": "主题",
    "weather": "天气",
    "day_cost": "预计费用",
    "transit": "路途时间",
    "weather_outlook": "天气预报",
    "city_logistics": "城市出行贴士",
    "local_tips": "本地攻略",
    "review_summary": "行程审查",
    "replan_summary": "重规划说明",
    "planner_notes": "规划说明",
    "interests_used": "兴趣偏好",
    "must_visit_inputs": "必去景点",
    "imported_notes": "参考攻略已融入 POI 检索与优先级排序。",
}


def _display_city_name(city: str, zh: bool) -> str:
    bundle = city_name_bundle(city)
    return bundle["city_zh"] if zh and bundle["city_zh"] else city


def _display_travel_type(value: str, zh: bool) -> str:
    return TRAVEL_TYPE_LABELS_ZH.get(value, value) if zh else value.title()


def _display_budget(value: str, zh: bool) -> str:
    return BUDGET_LEVEL_LABELS_ZH.get(value, value) if zh else value.title()


def _display_pace(value: str, zh: bool) -> str:
    return PACE_LABELS_ZH.get(value, value) if zh else value.title()


def _display_travelers(value: str, zh: bool) -> str:
    return TRAVELER_LABELS_ZH.get(value, value) if zh else value


def _display_time_slot(value: str, zh: bool) -> str:
    return TIME_SLOT_LABELS_ZH.get(value, value.title()) if zh else value.title()


def _display_category(value: str, zh: bool) -> str:
    return CATEGORY_LABELS_ZH.get(value, value) if zh else value


def _display_theme(value: str, zh: bool) -> str:
    return DAY_THEME_LABELS_ZH.get(value, value) if zh else value


def _display_location(value: str, zh: bool) -> str:
    return normalize_location_display_name(value) if zh else value


def _localize_reasoning(text: str, zh: bool) -> str:
    if not zh:
        return text
    parts = [part.strip() for part in text.split(";") if part.strip()]
    translated = [REASON_TRANSLATIONS_ZH.get(part, part) for part in parts]
    return "；".join(translated)


def _localize_weather_fit(text: str, zh: bool) -> str:
    if not zh:
        return text
    translated = text
    translated = translated.replace("No weather constraint applied.", "暂无额外天气限制。")
    translated = translated.replace("flexible mixed-environment stop.", "适合作为室内外都能灵活调整的安排。")
    translated = translated.replace(": indoor-friendly choice.", "：更适合安排室内活动。")
    translated = translated.replace(": outdoor plan, monitor rain risk.", "：适合户外活动，但要留意降雨变化。")
    translated = translated.replace(": flexible mixed-environment stop.", "：适合作为室内外都能灵活调整的安排。")
    translated = re.sub(r":\s*", "：", translated)
    return translated


def _localize_transport_hint(text: str, zh: bool) -> str:
    if not zh:
        return text
    translated = text
    translated = translated.replace("Revisit or explore nearby options.", "可作为回访安排，或在周边灵活补点。")
    translated = re.sub(
        r"^Start the day in (.+?)\.$",
        lambda match: f"从{normalize_location_display_name(match.group(1))}开始当天行程。",
        translated,
    )
    translated = re.sub(r"^Driving about (\d+) min \(([\d.]+) km\)\. ?", r"驾车约\1分钟（\2公里）。", translated)
    translated = re.sub(r"^Walking about (\d+) min \(([\d.]+) km\)\. ?", r"步行约\1分钟（\2公里）。", translated)
    translated = re.sub(r"^Transit about (\d+) min \(([\d.]+) km\)\. ?", r"公共交通约\1分钟（\2公里）。", translated)
    translated = re.sub(r"^Taxi about (\d+) min \(([\d.]+) km\)\. ?", r"打车约\1分钟（\2公里）。", translated)
    translated = re.sub(r"^Bike about (\d+) min \(([\d.]+) km\)\. ?", r"骑行约\1分钟（\2公里）。", translated)
    translated = translated.replace("Walk within the same district using the shortest pedestrian route.", "同一区域内步行为主，按最短路径前往。")
    return translated


def _localize_overview(itinerary: ItineraryPlan, preferences: UserPreferences, zh: bool) -> str:
    if not zh:
        return itinerary.overview
    city_name = _display_city_name(itinerary.city, zh=True)
    return (
        f"这是一版为 {city_name} 设计的 {preferences.trip_days} 天"
        f"{_display_travel_type(preferences.travel_type, zh=True)}行程，整体节奏偏"
        f"{_display_pace(preferences.pace, zh=True)}，预算按照{_display_budget(preferences.budget_level, zh=True)}来控制。"
    )


def _localize_review_text(text: str, zh: bool) -> str:
    if not zh:
        return text
    translated = REVIEW_TRANSLATIONS_ZH.get(text, text)
    translated = translated.replace(
        "Keep this stop grouped with nearby places instead of crossing the city just for one check-in.",
        "这个点更适合和附近地点一起安排，不建议为了单独打卡而跨区折返。",
    )
    translated = re.sub(
        r"^Review flagged (\d+) itinerary risks that may need adjustment\.$",
        r"系统检查出 \1 处可能需要调整的行程风险。",
        translated,
    )
    translated = re.sub(
        r"^Day (\d+) spans (\d+) districts, which may feel fragmented\.$",
        r"第 \1 天跨了 \2 个片区，整体上可能会显得有些分散。",
        translated,
    )
    translated = re.sub(
        r"^Day (\d+) looks heavy for a (.+?) pace at about ([\d.]+) hours including transit\.$",
        r"第 \1 天对\2节奏来说偏满，连同通勤在内大约有 \3 小时活动量。",
        translated,
    )
    translated = re.sub(
        r"^Day (\d+) spends about (\d+) minutes in inter-stop travel; consider tightening the cluster\.$",
        r"第 \1 天点位之间通勤约 \2 分钟，建议把路线再收紧一些。",
        translated,
    )
    translated = re.sub(
        r"^Day (\d+) has about ([\d.]+) in core attraction spend, which is high for a (.+?) budget\.$",
        r"第 \1 天核心景点支出约为 \2，对\3预算来说偏高。",
        translated,
    )
    translated = re.sub(
        r"^These must-visit requests are not clearly covered in the scheduled stops: (.+)\.$",
        r"这些必去点在当前行程里还没有被明确覆盖：\1。",
        translated,
    )
    translated = re.sub(
        r"^Current hotel budget reference is up to CNY ([\d.]+)\.?$",
        r"当前酒店预算参考上限约为每晚 ¥ \1。",
        translated,
    )
    translated = re.sub(
        r"^Inter-stop travel time is about (\d+) min across ([\d.]+) km\.$",
        r"点位之间的路途时间约为\1分钟，总路程约\2公里。",
        translated,
    )
    translated = re.sub(
        r"^Current hotel budget reference is up to CNY ([\d.]+) per night\.$",
        r"当前酒店预算参考上限约为每晚 ¥ \1。",
        translated,
    )
    return translated


def _should_show_zh_text(text: str, zh: bool) -> bool:
    if not text:
        return False
    if not zh:
        return True
    localized = _localize_review_text(text, zh=True)
    return localized != text or any("一" <= ch <= "鿿" for ch in localized)


def render_markdown_report(plan: dict, user_profile: dict, city_context: dict, weather: dict) -> str:
    itinerary = ItineraryPlan.model_validate(plan)
    preferences = UserPreferences.model_validate(user_profile)
    weather_days = _weather_lookup(weather)

    zh = True
    L = _REPORT_LABELS_ZH

    no_weather = "暂无天气数据"
    city_name = _display_city_name(itinerary.city, zh)

    lines = [
        f"# {city_name} {L['title_suffix']}",
        "",
        f"**{L['trip_style']}**: {_display_travel_type(preferences.travel_type, zh)}",
        f"**{L['travelers']}**: {_display_travelers(preferences.travelers, zh)}",
        f"**{L['budget']}**: {_display_budget(preferences.budget_level, zh)}",
        f"**{L['pace']}**: {_display_pace(preferences.pace, zh)}",
        f"**{L['est_cost']}**: {itinerary.total_estimated_cost:.2f}",
        "",
        f"## {L['planning_summary']}",
        _localize_overview(itinerary, preferences, zh),
        "",
    ]

    if preferences.interests:
        lines.append(f"**{L['interests_used']}**: {', '.join(preferences.interests)}")
    if preferences.must_visit:
        lines.append(f"**{L['must_visit_inputs']}**: {', '.join(preferences.must_visit)}")
    if preferences.notes:
        lines.append(f"**{'参考攻略' if zh else 'Imported Notes'}**: {L['imported_notes']}")
    lines.append("")

    lines.append(f"## {L['itinerary']}")
    for day in itinerary.days:
        day_label = L["day"].format(n=day.day_index)
        lines.extend(
            [
                "",
                f"### {day_label}: {_display_location(day.area, zh)}",
                f"- {L['theme']}: {_display_theme(day.theme, zh)}",
                f"- {L['weather']}: {day.weather_summary or no_weather}",
                f"- {L['day_cost']}: {day.estimated_cost:.2f}",
                (
                    f"- {L['transit']}: 约 {day.inter_stop_duration_min} 分钟 / {day.inter_stop_distance_m / 1000:.1f} 公里"
                    if zh
                    else f"- {L['transit']}: {day.inter_stop_duration_min} min across {day.inter_stop_distance_m / 1000:.1f} km"
                ),
            ]
        )
        for item in day.items:
            lines.extend(
                [
                    f"- {_display_time_slot(item.time_slot, zh)}: **{item.poi_name}** ({_display_category(item.category, zh)}, {_display_location(item.district, zh)})",
                    f"  {'原因' if zh else 'Reason'}: {_localize_reasoning(item.reasoning, zh)}。",
                    f"  {'天气适配' if zh else 'Weather fit'}: {_localize_weather_fit(item.weather_fit, zh)}",
                    f"  {'交通' if zh else 'Transport'}: {_localize_transport_hint(item.transport_hint, zh)}",
                ]
            )
            if item.guide_evidence:
                source = f"（{item.guide_source}）" if item.guide_source else ""
                lines.append(f"  {'攻略依据' if zh else 'Guide evidence'}: {item.guide_evidence}{source}")
            if item.local_note:
                lines.append(f"  {'本地提醒' if zh else 'Local note'}: {item.local_note}")
            if item.pitfall_note:
                lines.append(f"  {'避坑提醒' if zh else 'Pitfall'}: {item.pitfall_note}")
        for note in day.notes:
            localized_note = _localize_review_text(note, zh)
            if _should_show_zh_text(localized_note, zh):
                lines.append(f"- {'备注' if zh else 'Day note'}: {localized_note}")

    if weather_days:
        lines.extend(["", f"## {L['weather_outlook']}"])
        for day in weather_days[: preferences.trip_days]:
            lines.append(
                (
                    f"- {day.date}: {day.summary}，{day.temp_min:.0f}-{day.temp_max:.0f}℃，降水概率 {day.precipitation_probability}%。"
                    if zh
                    else f"- {day.date}: {day.summary}, {day.temp_min:.0f}-{day.temp_max:.0f}C, precipitation risk {day.precipitation_probability}%."
                )
            )

    if city_context.get("transport"):
        lines.extend(["", f"## {L['city_logistics']}"])
        for tip in city_context["transport"][:4]:
            if _should_show_zh_text(tip, zh):
                lines.append(f"- {_localize_review_text(tip, zh)}")

    if itinerary.local_tips:
        lines.extend(["", f"## {L['local_tips']}"])
        for tip in itinerary.local_tips[:6]:
            if _should_show_zh_text(tip, zh):
                lines.append(f"- {_localize_review_text(tip, zh)}")

    if itinerary.review_summary or itinerary.review_findings:
        lines.extend(["", f"## {L['review_summary']}"])
        if itinerary.review_summary:
            lines.append(f"- {_localize_review_text(itinerary.review_summary, zh)}")
        for finding in itinerary.review_findings:
            lines.append(
                f"- [{'提示' if zh else finding.level.upper()}] {finding.rule}: {_localize_review_text(finding.message, zh)}"
            )

    if itinerary.replan_summary:
        lines.extend(["", f"## {L['replan_summary']}", f"- {_localize_review_text(itinerary.replan_summary, zh)}"])
        trigger_rules = itinerary.replan_metadata.get("trigger_rules", [])
        if trigger_rules:
            lines.append(f"- {'触发规则' if zh else 'Trigger rules'}: {', '.join(trigger_rules)}")

    lines.extend(["", f"## {L['planner_notes']}"])
    for note in itinerary.planning_notes:
        if _should_show_zh_text(note, zh):
            lines.append(f"- {_localize_review_text(note, zh)}")

    return "\n".join(lines)
