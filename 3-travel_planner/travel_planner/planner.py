from __future__ import annotations

from collections import defaultdict

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
PACE_SLOT_COUNT = {"slow": 2, "balanced": 3, "packed": 4}
SLOT_LABELS = ["morning", "afternoon", "evening", "evening"]
PACE_HOUR_CAP = {"slow": 6.0, "balanced": 8.5, "packed": 10.5}
CORE_ATTRACTION_DAY_BUDGET = {"low": 80.0, "medium": 180.0, "high": 320.0}
INTER_STOP_MIN_CAP = {"slow": 70, "balanced": 95, "packed": 125}


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


def _score_poi(
    poi: POI,
    preferences: UserPreferences,
    focus_tags: set[str],
    must_visit: set[str],
    avoid: set[str],
    city_tip_map: dict[str, str],
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
    if poi.rating:
        score += min(1.0, poi.rating / 5.0)
    return score


def _select_pois(
    preferences: UserPreferences,
    pois: list[POI],
    focus_tags: set[str],
    city_tip_map: dict[str, str],
) -> list[POI]:
    must_visit = _normalize_text_items(preferences.must_visit)
    avoid = _normalize_text_items(preferences.avoid)
    scored = sorted(
        pois,
        key=lambda poi: _score_poi(poi, preferences, focus_tags, must_visit, avoid, city_tip_map),
        reverse=True,
    )

    selected: list[POI] = []
    seen: set[str] = set()
    target_count = min(max(preferences.trip_days * PACE_SLOT_COUNT[preferences.pace], 5), 14)

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
    settings: Settings | None = None,
) -> list[DayPlan]:
    settings = settings or Settings.from_env()
    grouped = _district_clusters(selected_pois)
    districts = sorted(grouped.keys(), key=lambda key: len(grouped[key]), reverse=True)
    used: set[str] = set()
    plans: list[DayPlan] = []

    for day_index in range(preferences.trip_days):
        weather_day = weather_days[min(day_index, max(len(weather_days) - 1, 0))] if weather_days else None
        preferred_slots = PACE_SLOT_COUNT[preferences.pace]

        if day_index < len(districts):
            main_district = districts[day_index]
        else:
            remaining = [poi for poi in selected_pois if poi.name not in used]
            main_district = remaining[0].district if remaining else (districts[0] if districts else preferences.city)

        district_candidates = [poi for poi in grouped.get(main_district, []) if poi.name not in used]
        if not district_candidates:
            district_candidates = [poi for poi in selected_pois if poi.name not in used]

        def weather_sort_key(poi: POI) -> float:
            return _weather_penalty(poi, weather_day)

        district_candidates.sort(key=weather_sort_key, reverse=True)
        chosen_pois: list[POI] = []

        for slot_index in range(preferred_slots):
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

        route_plan = optimize_route_order(
            [poi.model_dump() for poi in chosen_pois],
            must_visit_names=_normalize_text_items(preferences.must_visit),
            settings=settings,
        )
        ordered_pois = [chosen_pois[index] for index in route_plan["ordered_indices"]]

        items: list[DayPlanItem] = []
        for slot_index, poi in enumerate(ordered_pois):
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
                    reasoning=_compose_reasoning(poi, preferences, weather_day, tips_map),
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

        plans.append(
            DayPlan(
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
        )

    return plans


def _compose_reasoning(
    poi: POI,
    preferences: UserPreferences,
    weather_day: WeatherDay | None,
    tips_map: dict[str, str],
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


def _contains_requested_place(place_name: str, candidate_names: list[str]) -> bool:
    place_key = place_name.strip().lower()
    return any(place_key in candidate.lower() for candidate in candidate_names)


def review_itinerary(plan: dict, user_profile: dict, weather: dict) -> dict:
    itinerary = ItineraryPlan.model_validate(plan)
    preferences = UserPreferences.model_validate(user_profile)
    weather_days = _weather_lookup(weather)
    findings: list[ReviewFinding] = []

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


def plan_itinerary(
    user_profile: dict,
    candidate_pois: list[dict],
    weather: dict,
    city_context: dict,
    travel_tips: dict,
    settings: Settings | None = None,
) -> dict:
    preferences = UserPreferences.model_validate(user_profile)
    pois = [POI.model_validate(item) for item in candidate_pois]
    weather_days = _weather_lookup(weather)
    city_tip_map = {
        entry.get("poi_name", "").strip().lower(): entry.get("tip", "")
        for entry in travel_tips.get("tips", [])
        if entry.get("poi_name")
    }

    focus_tags = set(TRAVEL_TYPE_KEYWORDS.get(preferences.travel_type, set()))
    focus_tags.update(tag.lower() for tag in city_context.get("focus_tags", []))
    selected_pois = _select_pois(preferences, pois, focus_tags, city_tip_map)
    days = _allocate_days(preferences, selected_pois, weather_days, city_context, city_tip_map, settings=settings)
    total_cost = round(sum(day.estimated_cost for day in days), 2)

    plan = ItineraryPlan(
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
    review = review_itinerary(plan.model_dump(), user_profile=user_profile, weather=weather)
    plan.review_summary = review["summary"]
    plan.review_findings = [ReviewFinding.model_validate(item) for item in review["findings"]]
    plan.planning_notes.append("A post-planning review checks pace, weather fit, budget pressure, and route coherence.")
    return plan.model_dump()


def render_markdown_report(plan: dict, user_profile: dict, city_context: dict, weather: dict) -> str:
    itinerary = ItineraryPlan.model_validate(plan)
    preferences = UserPreferences.model_validate(user_profile)
    weather_days = _weather_lookup(weather)

    lines = [
        f"# {itinerary.city} Intelligent Travel Plan",
        "",
        f"**Trip Style**: {preferences.travel_type.title()}",
        f"**Travelers**: {preferences.travelers}",
        f"**Budget**: {preferences.budget_level.title()}",
        f"**Pace**: {preferences.pace.title()}",
        f"**Estimated Core Attraction Cost**: {itinerary.total_estimated_cost:.2f}",
        "",
        "## Planning Summary",
        itinerary.overview,
        "",
    ]

    if preferences.interests:
        lines.append(f"**Interests Used**: {', '.join(preferences.interests)}")
    if preferences.must_visit:
        lines.append(f"**Must-Visit Inputs**: {', '.join(preferences.must_visit)}")
    if preferences.notes:
        lines.append("**Imported Notes**: incorporated into POI lookup and itinerary prioritization.")
    lines.append("")

    lines.append("## Day-by-Day Itinerary")
    for day in itinerary.days:
        lines.extend(
            [
                "",
                f"### Day {day.day_index}: {day.area}",
                f"- Theme: {day.theme}",
                f"- Weather: {day.weather_summary or 'No weather data'}",
                f"- Estimated cost: {day.estimated_cost:.2f}",
                f"- Inter-stop travel: {day.inter_stop_duration_min} min across {day.inter_stop_distance_m / 1000:.1f} km",
            ]
        )
        for item in day.items:
            lines.extend(
                [
                    f"- {item.time_slot.title()}: **{item.poi_name}** ({item.category}, {item.district})",
                    f"  Reason: {item.reasoning}.",
                    f"  Weather fit: {item.weather_fit}",
                    f"  Transport: {item.transport_hint}",
                ]
            )
        for note in day.notes:
            lines.append(f"- Day note: {note}")

    if weather_days:
        lines.extend(["", "## Weather Outlook"])
        for day in weather_days[: preferences.trip_days]:
            lines.append(
                f"- {day.date}: {day.summary}, {day.temp_min:.0f}-{day.temp_max:.0f}C, precipitation risk {day.precipitation_probability}%."
            )

    if city_context.get("transport"):
        lines.extend(["", "## City Logistics"])
        for tip in city_context["transport"][:4]:
            lines.append(f"- {tip}")

    if itinerary.local_tips:
        lines.extend(["", "## Local Tips"])
        for tip in itinerary.local_tips[:6]:
            lines.append(f"- {tip}")

    if itinerary.review_summary or itinerary.review_findings:
        lines.extend(["", "## Review Summary"])
        if itinerary.review_summary:
            lines.append(f"- {itinerary.review_summary}")
        for finding in itinerary.review_findings:
            lines.append(f"- [{finding.level.upper()}] {finding.rule}: {finding.message}")

    lines.extend(["", "## Planner Notes"])
    for note in itinerary.planning_notes:
        lines.append(f"- {note}")

    return "\n".join(lines)
