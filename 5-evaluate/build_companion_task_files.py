from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "companion_tasks_10_cities.json"
OUT_DIR = ROOT / "companion_tasks"

CITY_ORDER = [
    "Beijing",
    "Shanghai",
    "Chengdu",
    "Chongqing",
    "Guangzhou",
    "Shenzhen",
    "Hangzhou",
    "Xian",
    "Xiamen",
    "Nanjing",
]

CITY_ZH = {
    "Beijing": "北京",
    "Shanghai": "上海",
    "Chengdu": "成都",
    "Chongqing": "重庆",
    "Guangzhou": "广州",
    "Shenzhen": "深圳",
    "Hangzhou": "杭州",
    "Xian": "西安",
    "Xiamen": "厦门",
    "Nanjing": "南京",
}

FILE_NAMES = {
    "Beijing": "beijing.json",
    "Shanghai": "shanghai.json",
    "Chengdu": "chengdu.json",
    "Chongqing": "chongqing.json",
    "Guangzhou": "guangzhou.json",
    "Shenzhen": "shenzhen.json",
    "Hangzhou": "hangzhou.json",
    "Xian": "xian.json",
    "Xiamen": "xiamen.json",
    "Nanjing": "nanjing.json",
}


def node(
    name: str,
    slot: str,
    hours: float,
    priority: int,
    indoor: str,
    distance: float,
    must: bool = False,
    walking: float = 1.0,
    mobility: str = "medium",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "poi_name": name,
        "time_slot": slot,
        "duration_hours": hours,
        "priority": priority,
        "must_visit": must,
        "indoor_outdoor": indoor,
        "distance_km": distance,
        "walking_km": walking,
        "mobility_level": mobility,
    }
    if extra:
        payload.update(extra)
    return payload


def rubric(key: str, dimension: str, text: str) -> dict[str, str]:
    return {"key": key, "dimension": dimension, "rubric": text}


def make_task(
    *,
    city: str,
    idx: int,
    task_type: str,
    complexity: dict[str, list[str]],
    initial_state: dict[str, Any],
    persona: dict[str, str],
    complete_instruction: str,
    hidden_constraints: list[str],
    disclosure_plan: list[str],
    first_user_message: str,
    expected_trajectory: dict[str, Any],
    rubrics: list[dict[str, str]],
    failure_tags: list[str],
) -> dict[str, Any]:
    city_key = city.lower().replace(" ", "_")
    return {
        "id": f"companion_{city_key}_{idx:03d}",
        "city": city,
        "city_zh": CITY_ZH[city],
        "task_type": task_type,
        "complexity": complexity,
        "initial_state": initial_state,
        "user_scenario": {
            "profile": persona,
            "complete_instruction": complete_instruction,
            "hidden_constraints": hidden_constraints,
            "disclosure_plan": disclosure_plan,
        },
        "first_user_message": first_user_message,
        "expected_trajectory": expected_trajectory,
        "evaluation_criteria": {"required_rubrics": rubrics},
        "failure_tags": failure_tags,
    }


def build_extra_tasks() -> list[dict[str, Any]]:
    r = rubric
    return [
        make_task(
            city="Beijing",
            idx=2,
            task_type="deadline_coordinate",
            complexity={
                "reasoning": ["route_duration", "appointment_deadline", "optional_stop_tradeoff"],
                "tool": ["get_route", "get_poi_detail"],
                "interaction": ["clear_go_or_skip_advice"],
            },
            initial_state={
                "city": "Beijing",
                "current_time": "2026-05-03T16:20:00+08:00",
                "current_location": "National Museum",
                "base_location": "Hotel near Wangfujing",
                "party": {"adults": 2, "elderly": 0, "children": 0},
                "destination_deadlines": [
                    {"name": "Peking duck dinner near Qianmen", "deadline": "2026-05-03T18:30:00+08:00"}
                ],
                "remaining_plan": [
                    node("Temple of Heaven", "afternoon", 1.5, 4, "outdoor", 4.8, walking=1.5),
                    node("Qianmen Street", "evening", 1.0, 3, "outdoor", 1.2, walking=0.8),
                ],
            },
            persona={
                "persona": "Time-sensitive traveller with dinner reservation.",
                "style": "Wants a direct feasibility answer.",
            },
            complete_instruction=(
                "I am at the National Museum at 16:20. I want to add Temple of Heaven, "
                "but I must reach Qianmen for Peking duck dinner by 18:30."
            ),
            hidden_constraints=["18:30 dinner is fixed", "Temple of Heaven is optional", "do not guess route time"],
            disclosure_plan=["Ask if Temple of Heaven can still fit.", "If asked, say dinner cannot move."],
            first_user_message=(
                "I am at the National Museum now. Can I still go to Temple of Heaven before my 6:30 Qianmen dinner?"
            ),
            expected_trajectory={
                "required_intent": "coordinate",
                "tools_must_call": ["get_route"],
                "tools_should_call": ["get_poi_detail"],
                "state_assertions": [
                    "Agent checks route feasibility before advising.",
                    "Agent treats 18:30 dinner as a hard deadline.",
                    "Agent clearly says go, skip, or only do a shortened visit.",
                ],
            },
            rubrics=[
                r("recognize_deadline", "reasoning", "Agent recognizes the 18:30 dinner as a hard deadline."),
                r("route_checked", "tool", "Agent calls get_route for a relevant leg."),
                r("poi_time_considered", "tool", "Agent checks or accounts for Temple of Heaven visit/opening time."),
                r("clear_feasibility", "interaction", "Final answer gives a clear feasibility recommendation."),
                r("avoid_overcommit", "reasoning", "Agent does not overcommit to a rushed plan without buffer."),
            ],
            failure_tags=["missed_deadline", "no_route_check", "overcommitted_plan"],
        ),
        make_task(
            city="Beijing",
            idx=3,
            task_type="emergency_toilet_family",
            complexity={
                "reasoning": ["urgent_need", "child_context", "nearest_resource"],
                "tool": ["resolve_emergency_resources"],
                "interaction": ["immediate_action"],
            },
            initial_state={
                "city": "Beijing",
                "current_time": "2026-05-04T11:05:00+08:00",
                "current_location": "Forbidden City",
                "base_location": "Hotel near Wangfujing",
                "party": {"adults": 2, "elderly": 0, "children": 1},
                "remaining_plan": [
                    node("Forbidden City", "morning", 2.5, 5, "mixed", 0.0, True),
                    node("Jingshan Park", "afternoon", 1.0, 3, "outdoor", 0.8),
                ],
            },
            persona={"persona": "Parent with urgent child need.", "style": "Short and stressed."},
            complete_instruction=(
                "My child urgently needs a toilet inside or near the Forbidden City. "
                "Stop sightseeing advice and help find the nearest safe facility or staff help point."
            ),
            hidden_constraints=["urgent toilet/help scene", "do not continue normal itinerary", "child safety matters"],
            disclosure_plan=["First say the child urgently needs a restroom.", "If asked, say you are near the central area."],
            first_user_message="My kid urgently needs a toilet in the Forbidden City. Where should we go right now?",
            expected_trajectory={
                "required_intent": "emergency",
                "tools_must_call": ["resolve_emergency_resources"],
                "state_assertions": [
                    "Agent treats this as an urgent toilet/help scene.",
                    "Final answer leads with nearest practical action.",
                ],
            },
            rubrics=[
                r("classify_urgent_toilet", "reasoning", "Agent classifies the message as emergency/toilet."),
                r("call_emergency_resources", "tool", "Agent calls resolve_emergency_resources for toilet/help resources."),
                r("immediate_action_first", "interaction", "Final reply starts with the immediate action."),
                r("child_context", "reasoning", "Agent accounts for the child and prioritizes nearest/safe facility."),
                r("fallback_staff", "interaction", "If exact data is missing, agent suggests staff or visitor center."),
            ],
            failure_tags=["normal_search", "no_resource_lookup", "continues_sightseeing"],
        ),
        make_task(
            city="Shanghai",
            idx=2,
            task_type="same_name_location_scope",
            complexity={
                "reasoning": ["city_bias", "same_name_disambiguation"],
                "tool": ["resolve_location", "retrieve_candidates"],
                "interaction": ["no_unnecessary_clarification"],
            },
            initial_state={
                "city": "Shanghai",
                "current_time": "2026-06-13T10:10:00+08:00",
                "current_location": "People's Square",
                "base_location": "Hotel near People's Square",
                "party": {"adults": 2, "elderly": 0, "children": 0},
                "remaining_plan": [
                    node("Shanghai Museum", "morning", 2.0, 5, "indoor", 0.3, True),
                    node("The Bund", "evening", 1.0, 5, "outdoor", 1.8, True),
                ],
            },
            persona={
                "persona": "Independent traveller using local shorthand.",
                "style": "Expects the agent to use current city context.",
            },
            complete_instruction=(
                "I am near People's Square in Shanghai and want a nearby quiet cafe or rest spot before Shanghai Museum."
            ),
            hidden_constraints=["People's Square should be scoped to Shanghai", "nearby quiet rest spot"],
            disclosure_plan=["First ask for a quiet place near People's Square.", "If asked, say Shanghai Museum is next."],
            first_user_message="Can you find a quiet place to sit near People's Square before we go to Shanghai Museum?",
            expected_trajectory={
                "required_intent": "search",
                "tools_must_call": ["resolve_location", "retrieve_candidates"],
                "tools_should_call": ["score_candidates"],
                "state_assertions": [
                    "Agent scopes People's Square to Shanghai.",
                    "Agent does not ask the user to choose between same-name places in other cities.",
                ],
            },
            rubrics=[
                r("city_scoped_location", "tool", "Agent resolves People's Square using Shanghai as city context."),
                r("retrieve_nearby_rest", "tool", "Agent retrieves nearby quiet cafe/rest candidates."),
                r("no_cross_city_disambiguation", "interaction", "Agent does not ask unnecessary cross-city disambiguation."),
                r("museum_context_kept", "reasoning", "Agent keeps Shanghai Museum as the next-stop context."),
                r("few_ranked_options", "interaction", "Final reply gives a small ranked set of options."),
            ],
            failure_tags=["wrong_city", "unnecessary_clarification", "unranked_options"],
        ),
        make_task(
            city="Shanghai",
            idx=3,
            task_type="emergency_medical_crowd",
            complexity={
                "reasoning": ["crowd_safety", "medical_triage"],
                "tool": ["resolve_emergency_resources"],
                "interaction": ["safety_first"],
            },
            initial_state={
                "city": "Shanghai",
                "current_time": "2026-06-13T20:15:00+08:00",
                "current_location": "The Bund",
                "base_location": "Hotel near People's Square",
                "party": {"adults": 2, "elderly": 1, "children": 0},
                "mobility_risk": "high",
                "remaining_plan": [
                    node("The Bund", "evening", 1.0, 5, "outdoor", 0.0, True),
                    node("Nanjing Road Pedestrian Street", "evening", 1.0, 3, "outdoor", 1.0),
                ],
            },
            persona={"persona": "Anxious traveller in a crowded place.", "style": "Needs immediate instructions."},
            complete_instruction=(
                "At the Bund, an elderly companion feels chest discomfort and the crowd is heavy. "
                "Need immediate help resources and a safe exit/rest plan."
            ),
            hidden_constraints=["possible medical emergency", "crowd makes movement risky", "do not continue nightlife"],
            disclosure_plan=["First report chest discomfort at the Bund.", "If asked, say they can stand but should not walk."],
            first_user_message="We are at the Bund and my elderly companion has chest discomfort. It is crowded. What should I do?",
            expected_trajectory={
                "required_intent": "emergency",
                "tools_must_call": ["resolve_emergency_resources"],
                "state_assertions": [
                    "Agent prioritizes medical help/rest/exit.",
                    "Agent does not recommend continuing to Nanjing Road first.",
                ],
            },
            rubrics=[
                r("medical_emergency", "reasoning", "Agent classifies chest discomfort as medical emergency."),
                r("call_resources", "tool", "Agent calls resolve_emergency_resources from The Bund location."),
                r("crowd_safety", "reasoning", "Agent accounts for crowd and avoids unnecessary walking."),
                r("immediate_steps", "interaction", "Final reply gives immediate steps before itinerary advice."),
                r("no_nightlife_continue", "interaction", "Agent does not suggest continuing sightseeing first."),
            ],
            failure_tags=["medical_misclassified", "continues_plan", "no_exit_plan"],
        ),
        make_search_food_task(
            city="Chengdu",
            idx=2,
            place="Kuanzhai Alley",
            message="Can you pick a nearby Chengdu dinner place around Kuanzhai Alley? I want local food but not too spicy.",
            constraint="not too spicy",
            local_style="Chengdu local flavor",
        ),
        make_rain_replan_task(
            city="Chengdu",
            idx=3,
            current_location="Wuhou Shrine",
            core_interest="Chengdu culture",
            outdoor_stop="Jinli Old Street",
            indoor_stop="Chengdu Museum",
            message="It may rain after Wuhou Shrine. Can you avoid outdoor strolling and keep something cultural?",
        ),
        make_emergency_mobility_task(
            city="Chongqing",
            idx=2,
            location="Hongya Cave",
            base_location="Hotel near Jiefangbei",
            message="At Hongya Cave, the elderly person cannot handle the stairs and crowd. What now?",
            risk_detail="stairs and crowd risk",
        ),
        make_search_food_task(
            city="Chongqing",
            idx=3,
            place="Jiefangbei",
            message="Can you find Chongqing dinner near Jiefangbei? One of us cannot eat very spicy.",
            constraint="mild or non-spicy option",
            local_style="Chongqing local dinner",
        ),
        make_rain_replan_task(
            city="Guangzhou",
            idx=2,
            current_location="Guangdong Provincial Museum",
            core_interest="Canton Tower night view",
            outdoor_stop="Canton Tower",
            indoor_stop="Guangzhou Opera House",
            message="The sky looks bad near Zhujiang New Town. Should I still do Canton Tower tonight or change the plan?",
        ),
        make_deadline_coordinate_task(
            city="Guangzhou",
            idx=3,
            current_location="Shamian Island",
            optional_stop="Yongqing Fang",
            destination="Guangzhou South Railway Station",
            deadline="2026-09-06T18:10:00+08:00",
            message="We are at Shamian. Train from Guangzhou South is 18:10. Can we still add Yongqing Fang?",
            party={"adults": 2, "elderly": 1, "children": 0},
        ),
        make_rain_replan_task(
            city="Shenzhen",
            idx=2,
            current_location="Shenzhen Bay Park",
            core_interest="design/art experience",
            outdoor_stop="Shenzhen Bay Park",
            indoor_stop="Sea World Culture and Arts Center",
            message="It is starting to rain at Shenzhen Bay Park. Can you replan and keep something design/art related?",
        ),
        make_deadline_coordinate_task(
            city="Shenzhen",
            idx=3,
            current_location="OCT Loft",
            optional_stop="Ping An Finance Centre",
            destination="Coco Park dinner",
            deadline="2026-10-04T19:00:00+08:00",
            message="Can I still do Ping An Finance Centre before my 7 pm Coco Park dinner?",
        ),
        make_deadline_coordinate_task(
            city="Hangzhou",
            idx=2,
            current_location="West Lake",
            optional_stop="West Lake Boat",
            destination="Hubin dinner",
            deadline="2026-06-21T18:00:00+08:00",
            message="By West Lake now. Dinner near Hubin is 6 pm. Can we still take a boat?",
            party={"adults": 2, "elderly": 2, "children": 0},
        ),
        make_search_food_task(
            city="Hangzhou",
            idx=3,
            place="China National Tea Museum",
            message="After the Tea Museum, can you find a nearby low-walk tea place for my parents to rest?",
            constraint="low-walk and elderly-friendly",
            local_style="Hangzhou tea experience",
            party={"adults": 2, "elderly": 2, "children": 0},
        ),
        make_rain_replan_task(
            city="Xian",
            idx=2,
            current_location="Muslim Quarter",
            core_interest="history-focused indoor stop",
            outdoor_stop="City Wall",
            indoor_stop="Shaanxi History Museum",
            message="It may rain. Can you avoid the City Wall if it is slippery and keep a history-focused plan?",
        ),
        make_search_food_task(
            city="Xian",
            idx=3,
            place="Bell Tower",
            message="Near Bell Tower, can you pick a local Xian dinner place? One of us does not eat lamb.",
            constraint="no lamb for one traveller",
            local_style="local Xian food",
        ),
        make_deadline_coordinate_task(
            city="Xiamen",
            idx=2,
            current_location="Zhongshan Road Pedestrian Street",
            optional_stop="Shapowei",
            destination="Gulangyu ferry",
            deadline="2026-05-19T17:10:00+08:00",
            message="From Zhongshan Road, can we add Shapowei before our 17:10 Gulangyu ferry?",
            party={"adults": 2, "elderly": 1, "children": 0},
        ),
        make_search_food_task(
            city="Xiamen",
            idx=3,
            place="Zhongshan Road Pedestrian Street",
            message="Can you find dinner near Zhongshan Road? One of us is allergic to seafood.",
            constraint="seafood allergy",
            local_style="Xiamen-style local options",
        ),
        make_task(
            city="Nanjing",
            idx=2,
            task_type="lost_child_help",
            complexity={
                "reasoning": ["lost_person", "safe_meeting_point"],
                "tool": ["resolve_emergency_resources"],
                "interaction": ["immediate_protocol"],
            },
            initial_state={
                "city": "Nanjing",
                "current_time": "2026-11-15T19:30:00+08:00",
                "current_location": "Confucius Temple Nanjing",
                "base_location": "Hotel near Xinjiekou",
                "party": {"adults": 2, "elderly": 0, "children": 1},
                "remaining_plan": [node("Confucius Temple Nanjing", "evening", 1.0, 4, "mixed", 0.0)],
            },
            persona={"persona": "Panicked parent in crowded area.", "style": "Urgent and emotional."},
            complete_instruction=(
                "At Confucius Temple, I cannot find my child in the crowd. Need immediate safety protocol and official help point."
            ),
            hidden_constraints=["lost child emergency", "crowd risk", "official staff/help point"],
            disclosure_plan=["First report child missing at Confucius Temple."],
            first_user_message="At Confucius Temple, I cannot find my child in the crowd. Help me now.",
            expected_trajectory={
                "required_intent": "emergency",
                "tools_must_call": ["resolve_emergency_resources"],
                "state_assertions": ["Lost child handled as emergency.", "Final reply gives immediate protocol."],
            },
            rubrics=[
                r("classify_lost_child", "reasoning", "Agent classifies lost child as emergency/help."),
                r("call_resources", "tool", "Agent calls resolve_emergency_resources."),
                r("immediate_protocol", "interaction", "Final reply gives immediate safety steps."),
                r("crowd_safety", "reasoning", "Agent accounts for crowded environment."),
                r("no_sightseeing", "interaction", "Agent does not continue normal itinerary advice."),
            ],
            failure_tags=["misclassified_search", "no_staff_help", "continues_plan"],
        ),
        make_task(
            city="Nanjing",
            idx=3,
            task_type="night_cruise_weather_coordinate",
            complexity={
                "reasoning": ["weather", "night_activity_optional"],
                "tool": ["get_weather_now", "get_route"],
                "interaction": ["backup_plan"],
            },
            initial_state={
                "city": "Nanjing",
                "current_time": "2026-11-15T18:10:00+08:00",
                "current_location": "Nanjing Museum",
                "base_location": "Hotel near Xinjiekou",
                "party": {"adults": 2, "elderly": 0, "children": 0},
                "remaining_plan": [
                    node("Qinhuai River Night Cruise", "evening", 1.0, 5, "outdoor", 5.5, True),
                    node("Confucius Temple Nanjing", "evening", 1.0, 4, "mixed", 5.0),
                ],
            },
            persona={"persona": "Traveller deciding on night cruise.", "style": "Wants weather-aware risk advice."},
            complete_instruction=(
                "I want Qinhuai River night cruise, but if rain is likely or transfer is too much from Nanjing Museum, give a safer backup."
            ),
            hidden_constraints=["cruise is weather-sensitive", "route from museum matters", "backup around Confucius Temple acceptable"],
            disclosure_plan=["Ask whether to do cruise tonight from museum."],
            first_user_message="From Nanjing Museum, should we still do the Qinhuai River night cruise tonight?",
            expected_trajectory={
                "required_intent": "coordinate",
                "tools_must_call": ["get_weather_now", "get_route"],
                "state_assertions": ["Weather and route checked.", "Backup proposed if risky."],
            },
            rubrics=[
                r("weather_checked", "tool", "Agent checks Nanjing weather."),
                r("route_checked", "tool", "Agent calls get_route from museum to cruise/Confucius Temple area."),
                r("weather_sensitive", "reasoning", "Agent treats night cruise as weather-sensitive."),
                r("clear_recommendation", "interaction", "Final reply clearly recommends do/defer/backup."),
                r("backup_nearby", "reasoning", "Backup remains practical and nearby."),
            ],
            failure_tags=["weather_guess", "no_route", "no_backup"],
        ),
    ]


def make_search_food_task(
    *,
    city: str,
    idx: int,
    place: str,
    message: str,
    constraint: str,
    local_style: str,
    party: dict[str, int] | None = None,
) -> dict[str, Any]:
    return make_task(
        city=city,
        idx=idx,
        task_type="nearby_food_or_rest_search",
        complexity={
            "reasoning": ["preference_constraint", "nearby_priority", "local_experience"],
            "tool": ["retrieve_candidates", "score_candidates"],
            "interaction": ["ranked_recommendation"],
        },
        initial_state={
            "city": city,
            "current_time": "2026-07-01T18:00:00+08:00",
            "current_location": place,
            "base_location": f"Hotel near {place}",
            "party": party or {"adults": 2, "elderly": 0, "children": 0},
            "food_constraints": [constraint],
            "remaining_plan": [node(place, "evening", 1.0, 4, "mixed", 0.0)],
        },
        persona={"persona": "Traveller asking the agent to choose a practical local option.", "style": "Prefers a short ranked recommendation."},
        complete_instruction=f"Find a nearby option around {place}. Preserve {local_style}, but respect this constraint: {constraint}.",
        hidden_constraints=[constraint, "nearby matters", local_style],
        disclosure_plan=[f"Ask for a nearby option around {place}.", f"If asked, repeat the constraint: {constraint}."],
        first_user_message=message,
        expected_trajectory={
            "required_intent": "search",
            "tools_must_call": ["retrieve_candidates", "score_candidates"],
            "state_assertions": ["Search is scoped to the current city/location.", "Ranking uses the stated constraint."],
        },
        rubrics=[
            rubric("retrieve_candidates", "tool", "Agent retrieves nearby candidates in the correct city."),
            rubric("score_constraints", "tool", "Agent scores candidates with the stated preference or dietary constraint."),
            rubric("respect_constraint", "reasoning", f"Final recommendation respects: {constraint}."),
            rubric("preserve_local_style", "reasoning", f"Recommendation preserves {local_style}."),
            rubric("few_actionable_options", "interaction", "Final reply gives 1-3 actionable options with reasons."),
        ],
        failure_tags=["constraint_ignored", "wrong_area", "unranked_list"],
    )


def make_rain_replan_task(
    *,
    city: str,
    idx: int,
    current_location: str,
    core_interest: str,
    outdoor_stop: str,
    indoor_stop: str,
    message: str,
) -> dict[str, Any]:
    return make_task(
        city=city,
        idx=idx,
        task_type="weather_indoor_replan",
        complexity={
            "reasoning": ["weather_branch", "indoor_substitution", "core_interest_preservation"],
            "tool": ["get_weather_now", "replan_itinerary"],
            "interaction": ["conditional_plan"],
        },
        initial_state={
            "city": city,
            "current_time": "2026-07-01T14:00:00+08:00",
            "current_location": current_location,
            "base_location": f"Hotel near {current_location}",
            "party": {"adults": 2, "elderly": 0, "children": 0},
            "remaining_plan": [
                node(outdoor_stop, "afternoon", 1.5, 4, "outdoor", 1.0, outdoor_stop == core_interest),
                node(indoor_stop, "afternoon", 1.5, 5, "indoor", 3.0, indoor_stop == core_interest),
            ],
        },
        persona={"persona": "Weather-sensitive traveller.", "style": "Accepts tradeoffs if the reason is clear."},
        complete_instruction=f"Rain may affect the plan. Avoid exposed outdoor activity and preserve {core_interest}.",
        hidden_constraints=["check weather before deciding", "prefer indoor if raining", f"preserve {core_interest}"],
        disclosure_plan=["Mention rain/weather concern.", f"If asked priority, say {core_interest} matters most."],
        first_user_message=message,
        expected_trajectory={
            "required_intent": "replan",
            "tools_must_call": ["get_weather_now", "replan_itinerary"],
            "state_assertions": ["Weather is checked.", "Indoor preference or conditional outdoor decision is used."],
        },
        rubrics=[
            rubric("weather_checked", "tool", f"Agent checks {city} weather."),
            rubric("indoor_constraint", "reasoning", "Agent turns rain into an indoor or conditional-outdoor constraint."),
            rubric("call_replan", "tool", "Agent calls replan_itinerary."),
            rubric("preserve_core_interest", "interaction", f"Final reply preserves {core_interest}."),
            rubric("avoid_exposed_outdoor", "reasoning", "Agent avoids or makes exposed outdoor stops conditional."),
        ],
        failure_tags=["weather_guess", "drops_core_interest", "keeps_bad_weather_outdoor"],
    )


def make_deadline_coordinate_task(
    *,
    city: str,
    idx: int,
    current_location: str,
    optional_stop: str,
    destination: str,
    deadline: str,
    message: str,
    party: dict[str, int] | None = None,
) -> dict[str, Any]:
    return make_task(
        city=city,
        idx=idx,
        task_type="deadline_coordinate",
        complexity={
            "reasoning": ["deadline", "route_feasibility", "optional_stop_tradeoff"],
            "tool": ["get_route", "get_poi_detail"],
            "interaction": ["clear_go_or_skip"],
        },
        initial_state={
            "city": city,
            "current_time": "2026-07-01T16:00:00+08:00",
            "current_location": current_location,
            "base_location": f"Hotel near {current_location}",
            "party": party or {"adults": 2, "elderly": 0, "children": 0},
            "destination_deadlines": [{"name": destination, "deadline": deadline}],
            "remaining_plan": [
                node(optional_stop, "afternoon", 1.0, 4, "mixed", 2.5),
                node(destination, "evening", 0.5, 5, "mixed", 0.0, True),
            ],
        },
        persona={"persona": "Traveller with a fixed departure or reservation.", "style": "Needs a conservative answer."},
        complete_instruction=f"Decide whether {optional_stop} can fit before {destination} at {deadline}. If risky, skip it.",
        hidden_constraints=[f"{deadline} is fixed", f"{optional_stop} is optional", "route and buffer matter"],
        disclosure_plan=["Ask whether the optional stop fits.", "If asked, say the deadline cannot move."],
        first_user_message=message,
        expected_trajectory={
            "required_intent": "coordinate",
            "tools_must_call": ["get_route"],
            "tools_should_call": ["get_poi_detail"],
            "state_assertions": ["Deadline is treated as hard.", "Route/time is checked.", "Optional stop is skipped if risky."],
        },
        rubrics=[
            rubric("deadline_recognized", "reasoning", "Agent recognizes the fixed deadline."),
            rubric("route_checked", "tool", "Agent calls get_route for a relevant leg."),
            rubric("duration_or_buffer", "tool", "Agent checks or accounts for visit duration and buffer."),
            rubric("clear_recommendation", "interaction", "Final reply clearly says go or skip."),
            rubric("avoid_overpack", "reasoning", "Agent does not squeeze in the optional stop if it risks the deadline."),
        ],
        failure_tags=["missed_deadline", "no_route_check", "overpacked_plan"],
    )


def make_emergency_mobility_task(
    *,
    city: str,
    idx: int,
    location: str,
    base_location: str,
    message: str,
    risk_detail: str,
) -> dict[str, Any]:
    return make_task(
        city=city,
        idx=idx,
        task_type="emergency_mobility",
        complexity={
            "reasoning": ["mobility_risk", "safe_exit"],
            "tool": ["resolve_emergency_resources"],
            "interaction": ["group_split_or_fallback"],
        },
        initial_state={
            "city": city,
            "current_time": "2026-07-01T20:00:00+08:00",
            "current_location": location,
            "base_location": base_location,
            "party": {"adults": 2, "elderly": 1, "children": 0},
            "mobility_risk": "high",
            "remaining_plan": [node(location, "evening", 1.0, 5, "outdoor", 0.0, True, mobility="high")],
        },
        persona={"persona": "Stressed traveller with elderly companion.", "style": "Needs a safe exit plan."},
        complete_instruction=f"At {location}, an elderly companion has a mobility problem. Handle {risk_detail} and find rest/exit/help.",
        hidden_constraints=[risk_detail, "need exit/rest/help", "do not continue attraction plan"],
        disclosure_plan=[f"First say the elderly companion cannot continue at {location}."],
        first_user_message=message,
        expected_trajectory={
            "required_intent": "emergency",
            "tools_must_call": ["resolve_emergency_resources"],
            "state_assertions": ["Agent prioritizes rest/exit/help.", "Agent avoids continuing sightseeing."],
        },
        rubrics=[
            rubric("classify_mobility_emergency", "reasoning", "Agent classifies as mobility/emergency."),
            rubric("call_resources", "tool", "Agent calls resolve_emergency_resources."),
            rubric("risk_accounted", "reasoning", f"Agent accounts for {risk_detail}."),
            rubric("exit_or_rest", "interaction", "Final reply gives exit/rest/help guidance."),
            rubric("no_continue_tour", "interaction", "Agent does not recommend continuing sightseeing first."),
        ],
        failure_tags=["mobility_ignored", "no_exit_plan", "continues_sightseeing"],
    )


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    source_payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    tasks_by_city: dict[str, list[dict[str, Any]]] = {city: [] for city in CITY_ORDER}
    for task in source_payload["tasks"]:
        tasks_by_city[task["city"]].append(task)
    for task in build_extra_tasks():
        tasks_by_city[task["city"]].append(task)

    metadata = {
        "version": "0.2",
        "benchmark": "travel_agent_7035_companion_tasks",
        "agent": "companion",
        "description": (
            "Per-city VitaBench-style companion-agent task files. "
            "Each city currently contains 3 tasks for a 30-task benchmark seed set."
        ),
        "evaluator": {
            "window_turns": 10,
            "overlap_turns": 2,
            "success_policy": "all_required_rubrics",
            "recommended_trials": 4,
            "metrics": ["avg_at_4", "pass_at_4", "pass_all_4", "rubric_completion_rate"],
        },
    }

    index = {**metadata, "total_tasks": 0, "cities": []}
    for city in CITY_ORDER:
        tasks = tasks_by_city[city]
        payload = {
            **metadata,
            "city": city,
            "city_zh": CITY_ZH[city],
            "task_count": len(tasks),
            "tasks": tasks,
        }
        path = OUT_DIR / FILE_NAMES[city]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        index["cities"].append(
            {
                "city": city,
                "city_zh": CITY_ZH[city],
                "path": FILE_NAMES[city],
                "task_count": len(tasks),
                "task_ids": [task["id"] for task in tasks],
            }
        )
        index["total_tasks"] += len(tasks)

    (OUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {index['total_tasks']} tasks into {OUT_DIR}")


if __name__ == "__main__":
    main()
