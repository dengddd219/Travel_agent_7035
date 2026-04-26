from __future__ import annotations

from tools.replan_validator import validate_replan


def test_validator_rejects_over_time_budget():
    result = {
        "new_plan": [
            {"poi_name": "A", "duration_hours": 2.5, "priority": 5},
            {"poi_name": "B", "duration_hours": 2.0, "priority": 4},
        ],
        "warnings": [],
    }

    validation = validate_replan(result, {"time_budget_hours": 4})

    assert validation["ok"] is False
    assert "over_time_budget" in validation["reasons"]


def test_validator_rejects_outdoor_nodes_when_indoor_required():
    result = {
        "new_plan": [
            {"poi_name": "Outdoor Park", "duration_hours": 1, "indoor_outdoor": "outdoor", "priority": 5}
        ],
        "warnings": [],
    }

    validation = validate_replan(result, {"prefer_indoor": True})

    assert validation["ok"] is False
    assert "weather_mismatch" in validation["reasons"]


def test_validator_accepts_feasible_core_plan():
    result = {
        "new_plan": [
            {"poi_name": "Museum", "duration_hours": 2, "indoor_outdoor": "indoor", "priority": 5}
        ],
        "warnings": [],
    }

    validation = validate_replan(result, {"time_budget_hours": 4, "prefer_indoor": True})

    assert validation["ok"] is True
    assert validation["reasons"] == []
