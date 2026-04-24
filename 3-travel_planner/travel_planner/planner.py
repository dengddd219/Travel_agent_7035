## author:SUN Bin
from __future__ import annotations

from collections import defaultdict
import re

from .config import Settings
from .models import DayPlan, DayPlanItem, ItineraryPlan, POI, ReviewFinding, UserPreferences, WeatherDay
from .tools.routing import optimize_route_order


TRAVEL_TYPE_KEYWORDS = {
    "leisure": {"view", "culture", "local", "harbour"},
    "family": {"family", "park", "museum", "aquarium"},
    "food": {"food", "market", "local", "cafe"},
    "theme": {"culture", "design", "niche", "local"},
}

BUDGET_PRICE_LEVEL_CAP = {"low": 2, "medium": 4, "high": 5}
PACE_SLOT_COUNT = {"slow": 3, "balanced": 4, "packed": 5}
SLOT_LABELS = ["morning", "morning", "afternoon", "evening", "evening"]
PACE_HOUR_CAP = {"slow": 6.0, "balanced": 8.5, "packed": 10.5}
CORE_ATTRACTION_DAY_BUDGET = {"low": 80.0, "medium": 180.0, "high": 320.0}
INTER_STOP_MIN_CAP = {"slow": 70, "balanced": 95, "packed": 125}
PACE_REPLAN_STEP = {"packed": "balanced", "balanced": "slow", "slow": "slow"}


def _normalize_text_items(items: list[str]) -> set[str]:
    return {item.strip().lower() for item in items if item.strip()}


def _district_clusters(pois: list[POI]) -> dict[str, list[POI]]:
    grouped: dict[str, list[POI]] = defaultdict(list)
    for poi in pois:
        grouped[poi.district or "Unknown"].append(poi)
    return grouped


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
        str(item).strip().lower()
        for item in strategy_context.get("recommended_pois", [])
        if str(item).strip()
    }
    theme_suggestions = {
        str(item).strip().lower()
        for item in strategy_context.get("theme_suggestions", [])
        if str(item).strip()
    }
    district_priority: dict[str, float] = {}
    for index, note in enumerate(strategy_context.get("neighborhood_notes", []) or []):
        district = str(note.get("district", "")).strip()
        if district:
            district_priority[district] = max(district_priority.get(district, 0.0), 3.0 - index * 0.5)
    return {
        "recommended_pois": recommended_pois,
        "theme_suggestions": theme_suggestions,
        "district_priority": district_priority,
        "local_pitfalls": [str(item).strip() for item in strategy_context.get("local_pitfalls", []) if str(item).strip()],
    }


def _score_poi(
    poi: POI,
    preferences: UserPreferences,
    focus_tags: set[str],
    must_visit: set[str],
    avoid: set[str],
    city_tip_map: dict[str, str],
    strategy_signals: dict,
) -> float:
    name_key = poi.name.lower()
    if any(avoid_item in name_key for avoid_item in avoid):
        return -999.0

    score = 1.0
    if any(must in name_key for must in must_visit):
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
    if any(recommended in name_key or name_key in recommended for recommended in strategy_signals["recommended_pois"]):
        score += 3.2
    if any(tag in " ".join(poi.tags).lower() or tag in name_key for tag in strategy_signals["theme_suggestions"]):
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
    enrichment_target = sum(_parse_day_enrichment_requests(preferences.extra_request, preferences.trip_days).values())
    # Raise the per-trip cap (was 18) so longer trips don't exhaust candidates early.
    target_count = min(max(base_target + enrichment_target, preferences.trip_days * 3), max(24, preferences.trip_days * 4))

    for poi in scored:
        name_key = poi.name.lower()
        if name_key in seen:
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
        if any(must in name_key for must in must_visit) and name_key not in seen:
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
            if any(recommended in name_key or name_key in recommended for recommended in strategy_signals["recommended_pois"]):
                strategy_boost += 2.5
            if any(tag in " ".join(poi.tags).lower() or tag in name_key for tag in strategy_signals["theme_suggestions"]):
                strategy_boost += 1.2
            strategy_boost += strategy_signals["district_priority"].get(poi.district, 0.0)
            return _weather_penalty(poi, weather_day) + strategy_boost

        district_candidates.sort(key=weather_sort_key, reverse=True)
        chosen_pois: list[POI] = []

        for slot_index in range(max_slots_today):
            if not district_candidates:
                # Pull backup candidates from elsewhere if this district is exhausted.
                backup = [poi for poi in selected_pois if poi.name not in used]
                backup.sort(key=weather_sort_key, reverse=True)
                district_candidates = backup
            if not district_candidates:
                break

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
    if any(interest.lower() in poi.name.lower() or interest.lower() in " ".join(poi.tags).lower() for interest in preferences.interests):
        reasons.append("matches the stated interests")
    if preferences.must_visit and any(item.lower() in poi.name.lower() for item in preferences.must_visit):
        reasons.append("explicitly requested in must-visit list")
    if weather_day:
        if poi.indoor_outdoor == "indoor" and weather_day.outdoor_suitability != "good":
            reasons.append("works well as a weather-safe anchor")
        elif poi.indoor_outdoor == "outdoor" and weather_day.outdoor_suitability == "good":
            reasons.append("fits the stronger outdoor weather window")
    if tips_map.get(poi.name.lower()):
        reasons.append("supported by local tip signals")
    name_key = poi.name.lower()
    if any(recommended in name_key or name_key in recommended for recommended in strategy_signals["recommended_pois"]):
        reasons.append("repeatedly recommended in retrieved travel guides")
    if poi.district in strategy_signals["district_priority"]:
        reasons.append("sits in a neighborhood that the retrieved攻略 often clusters together")
    return "; ".join(reasons) or "chosen for geographic fit and itinerary balance"


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
    if any("museum" in item.poi_name.lower() for item in items):
        return "Culture and city highlights"
    if any("peak" in item.poi_name.lower() or "promenade" in item.poi_name.lower() for item in items):
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


def _parse_day_enrichment_requests(extra_request: str, trip_days: int) -> dict[int, int]:
    requests: dict[int, int] = {}
    if not extra_request:
        return requests
    day_aliases = {
        1: ["1", "一"],
        2: ["2", "二", "两"],
        3: ["3", "三"],
        4: ["4", "四"],
        5: ["5", "五"],
        6: ["6", "六"],
        7: ["7", "七"],
        8: ["8", "八"],
        9: ["9", "九"],
        10: ["10", "十"],
    }
    for day_index in range(1, trip_days + 1):
        aliases = day_aliases.get(day_index, [str(day_index)])
        for alias in aliases:
            match = re.search(
                rf"第\s*{alias}\s*天.*?(简单|太少|不够|空|单薄).*(增加|加|丰富|多安排|充实|加点)|第\s*{alias}\s*天.*?(增加|加|丰富|多安排|充实|加点).*(景点|安排|行程)",
                extra_request,
                flags=re.IGNORECASE,
            )
            if match:
                if re.search(r"(一些|一些新的|几个|更多|丰富|充实|多安排)", extra_request, flags=re.IGNORECASE):
                    requests[day_index] = 2
                else:
                    requests[day_index] = 1
                break
    return requests


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
    route_plan = optimize_route_order(
        [poi.model_dump() for poi in ordered_pois],
        must_visit_names=_normalize_text_items(preferences.must_visit),
        settings=settings,
    )
    reordered_pois = [ordered_pois[index] for index in route_plan["ordered_indices"]]

    items: list[DayPlanItem] = []
    for slot_index, poi in enumerate(reordered_pois):
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
                category=poi.category,
                district=poi.district,
                duration_hours=poi.duration_hours,
                est_cost=poi.ticket_price,
                reasoning=_compose_reasoning(poi, preferences, weather_day, tips_map, strategy_signals),
                weather_fit=_weather_fit_text(poi, weather_day),
                transport_hint=transport_hint,
                arrival_mode=arrival_mode,
                arrival_distance_m=arrival_distance_m,
                arrival_duration_min=arrival_duration_min,
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


def _apply_day_enrichment_requests(
    plans: list[DayPlan],
    preferences: UserPreferences,
    selected_pois: list[POI],
    weather_days: list[WeatherDay],
    city_context: dict,
    tips_map: dict[str, str],
    strategy_signals: dict,
    settings: Settings,
) -> list[DayPlan]:
    requests = _parse_day_enrichment_requests(preferences.extra_request, preferences.trip_days)
    if not requests:
        return plans

    poi_lookup = {poi.name: poi for poi in selected_pois}
    scheduled_names = {item.poi_name for day in plans for item in day.items}

    for target_day, extra_needed in requests.items():
        if target_day < 1 or target_day > len(plans):
            continue
        current_day = plans[target_day - 1]
        desired_count = min(PACE_SLOT_COUNT[preferences.pace] + extra_needed, 5)
        if len(current_day.items) >= desired_count:
            continue

        day_weather = weather_days[min(target_day - 1, len(weather_days) - 1)] if weather_days else None
        current_pois = [poi_lookup[item.poi_name] for item in current_day.items if item.poi_name in poi_lookup]

        def enrichment_score(poi: POI) -> float:
            score = _weather_penalty(poi, day_weather) + strategy_signals["district_priority"].get(poi.district, 0.0)
            if poi.district == current_day.area:
                score += 2.5
            name_key = poi.name.lower()
            if any(recommended in name_key or name_key in recommended for recommended in strategy_signals["recommended_pois"]):
                score += 2.0
            if poi.category == "food":
                score += 0.5
            return score

        backups = [
            poi for poi in selected_pois
            if poi.name not in scheduled_names and poi.name not in {item.poi_name for item in current_day.items}
        ]
        backups.sort(key=enrichment_score, reverse=True)
        additions = backups[: max(0, desired_count - len(current_day.items))]
        if len(additions) < max(0, desired_count - len(current_day.items)):
            donor_candidates = [
                (index, day)
                for index, day in enumerate(plans)
                if index != target_day - 1 and len(day.items) > 1
            ]
            donor_candidates.sort(key=lambda pair: len(pair[1].items), reverse=True)
            for donor_index, donor_day in donor_candidates:
                if len(current_day.items) + len(additions) >= desired_count:
                    break
                movable = donor_day.items[-1]
                movable_poi = poi_lookup.get(movable.poi_name)
                donor_remaining = [
                    poi_lookup[item.poi_name]
                    for item in donor_day.items[:-1]
                    if item.poi_name in poi_lookup
                ]
                if not movable_poi or not donor_remaining:
                    continue
                plans[donor_index] = _build_day_plan(
                    day_index=donor_index,
                    main_district=donor_day.area,
                    ordered_pois=donor_remaining,
                    weather_day=weather_days[min(donor_index, len(weather_days) - 1)] if weather_days else None,
                    preferences=preferences,
                    city_context=city_context,
                    tips_map=tips_map,
                    strategy_signals=strategy_signals,
                    settings=settings,
                )
                additions.append(movable_poi)
            if not additions:
                continue

        for poi in additions:
            scheduled_names.add(poi.name)
        plans[target_day - 1] = _build_day_plan(
            day_index=target_day - 1,
            main_district=current_day.area,
            ordered_pois=current_pois + additions,
            weather_day=day_weather,
            preferences=preferences,
            city_context=city_context,
            tips_map=tips_map,
            strategy_signals=strategy_signals,
            settings=settings,
        )

    return plans


def _contains_requested_place(place_name: str, candidate_names: list[str]) -> bool:
    place_key = place_name.strip().lower()
    return any(place_key in candidate.lower() for candidate in candidate_names)


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

    focus_tags = set(TRAVEL_TYPE_KEYWORDS.get(preferences.travel_type, set()))
    focus_tags.update(tag.lower() for tag in city_context.get("focus_tags", []))
    focus_tags.update(strategy_signals["theme_suggestions"])
    selected_pois = _select_pois(preferences, pois, focus_tags, city_tip_map, strategy_signals)
    days = _allocate_days(preferences, selected_pois, weather_days, city_context, city_tip_map, strategy_signals, settings=settings)
    days = _apply_day_enrichment_requests(
        days,
        preferences,
        selected_pois,
        weather_days,
        city_context,
        city_tip_map,
        strategy_signals,
        settings or Settings.from_env(),
    )
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
    allow_outdoor = "weather_fit" not in warning_rules
    allow_high_cost = "budget_pressure" not in warning_rules
    poor_weather_days = any(day.outdoor_suitability == "poor" for day in _weather_lookup(weather))
    budget_cap = CORE_ATTRACTION_DAY_BUDGET[preferences.budget_level]

    filtered: list[POI] = []
    for poi in pois:
        name_key = poi.name.strip().lower()
        is_must_visit = any(must in name_key for must in must_visit)
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


def _is_chinese_input(user_profile: dict) -> bool:
    """Return True when the user's request appears to be primarily Chinese."""
    # Heuristic: check notes or extra_request for Chinese characters.
    sample = " ".join(filter(None, [
        user_profile.get("notes", ""),
        user_profile.get("extra_request", ""),
        user_profile.get("travelers", ""),
    ]))
    chinese_chars = sum(1 for ch in sample if "一" <= ch <= "鿿")
    return chinese_chars >= 3


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

_REPORT_LABELS_EN = {
    "title_suffix": "Intelligent Travel Plan",
    "trip_style": "Trip Style",
    "travelers": "Travelers",
    "budget": "Budget",
    "pace": "Pace",
    "est_cost": "Estimated Core Attraction Cost",
    "planning_summary": "Planning Summary",
    "itinerary": "Day-by-Day Itinerary",
    "day": "Day {n}",
    "theme": "Theme",
    "weather": "Weather",
    "day_cost": "Estimated cost",
    "transit": "Inter-stop travel",
    "weather_outlook": "Weather Outlook",
    "city_logistics": "City Logistics",
    "local_tips": "Local Tips",
    "review_summary": "Review Summary",
    "replan_summary": "Replan Summary",
    "planner_notes": "Planner Notes",
    "interests_used": "Interests Used",
    "must_visit_inputs": "Must-Visit Inputs",
    "imported_notes": "incorporated into POI lookup and itinerary prioritization.",
}


def render_markdown_report(plan: dict, user_profile: dict, city_context: dict, weather: dict) -> str:
    itinerary = ItineraryPlan.model_validate(plan)
    preferences = UserPreferences.model_validate(user_profile)
    weather_days = _weather_lookup(weather)

    zh = _is_chinese_input(user_profile)
    L = _REPORT_LABELS_ZH if zh else _REPORT_LABELS_EN

    no_weather = "暂无天气数据" if zh else "No weather data"

    lines = [
        f"# {itinerary.city} {L['title_suffix']}",
        "",
        f"**{L['trip_style']}**: {preferences.travel_type.title()}",
        f"**{L['travelers']}**: {preferences.travelers}",
        f"**{L['budget']}**: {preferences.budget_level.title()}",
        f"**{L['pace']}**: {preferences.pace.title()}",
        f"**{L['est_cost']}**: {itinerary.total_estimated_cost:.2f}",
        "",
        f"## {L['planning_summary']}",
        itinerary.overview,
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
                f"### {day_label}: {day.area}",
                f"- {L['theme']}: {day.theme}",
                f"- {L['weather']}: {day.weather_summary or no_weather}",
                f"- {L['day_cost']}: {day.estimated_cost:.2f}",
                f"- {L['transit']}: {day.inter_stop_duration_min} min across {day.inter_stop_distance_m / 1000:.1f} km",
            ]
        )
        for item in day.items:
            lines.extend(
                [
                    f"- {item.time_slot.title()}: **{item.poi_name}** ({item.category}, {item.district})",
                    f"  {'原因' if zh else 'Reason'}: {item.reasoning}.",
                    f"  {'天气适配' if zh else 'Weather fit'}: {item.weather_fit}",
                    f"  {'交通' if zh else 'Transport'}: {item.transport_hint}",
                ]
            )
        for note in day.notes:
            lines.append(f"- {'备注' if zh else 'Day note'}: {note}")

    if weather_days:
        lines.extend(["", f"## {L['weather_outlook']}"])
        for day in weather_days[: preferences.trip_days]:
            lines.append(
                f"- {day.date}: {day.summary}, {day.temp_min:.0f}-{day.temp_max:.0f}C, {'降水概率' if zh else 'precipitation risk'} {day.precipitation_probability}%."
            )

    if city_context.get("transport"):
        lines.extend(["", f"## {L['city_logistics']}"])
        for tip in city_context["transport"][:4]:
            lines.append(f"- {tip}")

    if itinerary.local_tips:
        lines.extend(["", f"## {L['local_tips']}"])
        for tip in itinerary.local_tips[:6]:
            lines.append(f"- {tip}")

    if itinerary.review_summary or itinerary.review_findings:
        lines.extend(["", f"## {L['review_summary']}"])
        if itinerary.review_summary:
            lines.append(f"- {itinerary.review_summary}")
        for finding in itinerary.review_findings:
            lines.append(f"- [{finding.level.upper()}] {finding.rule}: {finding.message}")

    if itinerary.replan_summary:
        lines.extend(["", f"## {L['replan_summary']}", f"- {itinerary.replan_summary}"])
        trigger_rules = itinerary.replan_metadata.get("trigger_rules", [])
        if trigger_rules:
            lines.append(f"- {'触发规则' if zh else 'Trigger rules'}: {', '.join(trigger_rules)}")

    lines.extend(["", f"## {L['planner_notes']}"])
    for note in itinerary.planning_notes:
        lines.append(f"- {note}")

    return "\n".join(lines)
