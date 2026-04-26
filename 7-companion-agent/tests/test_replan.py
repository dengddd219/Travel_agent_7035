from __future__ import annotations

from tools.replan import replan_itinerary


SAMPLE_PLAN = [
    {
        "poi_name": "Summer Palace",
        "time_slot": "afternoon",
        "duration_hours": 2.5,
        "priority": 5,
        "must_visit": True,
        "indoor_outdoor": "outdoor",
        "distance_km": 1.0,
    },
    {
        "poi_name": "National Museum",
        "time_slot": "afternoon",
        "duration_hours": 2.0,
        "priority": 4,
        "indoor_outdoor": "indoor",
        "distance_km": 2.0,
    },
    {
        "poi_name": "Nanluoguxiang",
        "time_slot": "evening",
        "duration_hours": 1.5,
        "priority": 1,
        "indoor_outdoor": "outdoor",
        "distance_km": 4.0,
    },
]


def test_replan_fits_four_hour_budget_and_preserves_core_pois():
    result = replan_itinerary(
        remaining_plan=SAMPLE_PLAN,
        current_location="Hotel",
        time_budget_hours=4,
    )

    names = [node["poi_name"] for node in result["new_plan"]]
    total_hours = sum(node["duration_hours"] for node in result["new_plan"])

    assert result["status"] == "ok"
    assert total_hours <= 4
    assert "Summer Palace" in names
    assert "Nanluoguxiang" not in names
    assert any(node["poi_name"] == "Nanluoguxiang" for node in result["deferred_nodes"])


def test_replan_removes_completed_nodes():
    result = replan_itinerary(
        remaining_plan=SAMPLE_PLAN,
        current_location="Summer Palace",
        time_budget_hours=4,
        completed_nodes=["Summer Palace"],
    )

    names = [node["poi_name"] for node in result["new_plan"]]
    assert "Summer Palace" not in names
    assert "National Museum" in names
    assert any(node["remove_reason"] == "completed" for node in result["removed_nodes"])


def test_replan_removes_skipped_nodes():
    result = replan_itinerary(
        remaining_plan=SAMPLE_PLAN,
        current_location="Hotel",
        time_budget_hours=4,
        skipped_nodes=["National Museum"],
    )

    names = [node["poi_name"] for node in result["new_plan"]]
    assert "National Museum" not in names
    assert any(node["remove_reason"] == "skipped" for node in result["removed_nodes"])


def test_replan_can_filter_outdoor_when_indoor_is_required():
    result = replan_itinerary(
        remaining_plan=SAMPLE_PLAN,
        current_location="Hotel",
        time_budget_hours=4,
        constraints={"prefer_indoor": True},
    )

    assert result["new_plan"]
    assert all(node["indoor_outdoor"] != "outdoor" for node in result["new_plan"])
    assert any(node["remove_reason"] == "outdoor_filtered" for node in result["removed_nodes"])


def test_replan_self_check_retries_when_first_plan_is_too_far():
    result = replan_itinerary(
        remaining_plan=[
            {
                "poi_name": "Nearby Museum",
                "time_slot": "afternoon",
                "duration_hours": 1.5,
                "priority": 5,
                "must_visit": True,
                "indoor_outdoor": "indoor",
                "distance_km": 1.0,
            },
            {
                "poi_name": "Far Gallery",
                "time_slot": "afternoon",
                "duration_hours": 1.0,
                "priority": 4,
                "indoor_outdoor": "indoor",
                "distance_km": 8.0,
            },
        ],
        current_location="Hotel",
        time_budget_hours=4,
        constraints={"max_distance_km": 3},
    )

    names = [node["poi_name"] for node in result["new_plan"]]

    assert result["retry_count"] == 1
    assert result["self_check"]["ok"] is True
    assert "Nearby Museum" in names
    assert "Far Gallery" not in names
    assert any(node["remove_reason"] == "too_far" for node in result["removed_nodes"])
