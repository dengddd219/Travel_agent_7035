from __future__ import annotations

from fastapi.testclient import TestClient

from backend.server import app


def test_companion_route_accepts_day_plan_state():
    client = TestClient(app)
    payload = {
        "message": "We only have 4 hours this afternoon, please replan.",
        "conversation_state": {
            "city": "Beijing",
            "remaining_plan": [
                {
                    "poi_name": "Summer Palace",
                    "time_slot": "afternoon",
                    "duration_hours": 2.5,
                    "priority": 5,
                    "must_visit": True,
                    "indoor_outdoor": "outdoor",
                }
            ],
        },
    }

    response = client.post("/api/companion", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "replan"
    assert data["conversation_state"]["clarification_pending"] == "current_location"
