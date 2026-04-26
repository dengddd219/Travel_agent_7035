from __future__ import annotations

from companion_agent import TOOL_SCHEMAS, CompanionAgent
from config import Settings
from models import CompanionState


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


def _agent() -> CompanionAgent:
    return CompanionAgent(settings=Settings(openai_api_key="", openai_model="", default_city="Beijing"))


def _state() -> CompanionState:
    return CompanionState(city="Beijing", remaining_plan=[dict(node) for node in SAMPLE_PLAN])


def test_replan_without_location_asks_clarification_and_saves_task():
    state = _state()
    result = _agent().run_turn("We only have 4 hours this afternoon, please replan.", state)

    assert result.intent == "replan"
    assert "where" in result.reply.lower() or "在哪里" in result.reply
    assert state.clarification_pending == "current_location"
    assert state.clarification_resume_intent == "replan"
    assert state.current_task is not None
    assert state.current_task["intent"] == "replan"
    assert state.time_budget_hours == 4


def test_replan_clarification_gate_runs_before_llm_client():
    state = _state()
    agent = _agent()
    agent.client = object()

    result = agent.run_turn("We only have 4 hours this afternoon, please replan.", state)

    assert result.intent == "replan"
    assert state.clarification_pending == "current_location"
    assert state.current_task is not None


def test_replan_with_location_in_same_turn_executes_immediately():
    state = _state()
    result = _agent().run_turn("I am at Hotel, we only have 4 hours this afternoon, please replan.", state)

    assert result.intent == "replan"
    assert state.clarification_pending is None
    assert state.current_location == "Hotel"
    assert state.task_status == "completed"
    assert any(log["tool"] == "replan_itinerary" for log in result.tool_logs)


def test_location_answer_resumes_pending_replan_task():
    state = _state()
    agent = _agent()

    first = agent.run_turn("We only have 4 hours this afternoon, please replan.", state)
    assert first.intent == "replan"

    second = agent.run_turn("I am at Hotel", state)
    names = [node["poi_name"] for node in state.remaining_plan]

    assert second.intent == "replan"
    assert state.clarification_pending is None
    assert state.current_location == "Hotel"
    assert state.task_status == "completed"
    assert "Summer Palace" in names
    assert "Nanluoguxiang" not in names
    assert any(log["tool"] == "replan_itinerary" for log in second.tool_logs)


def test_completed_node_is_recorded_before_replan_task():
    state = _state()
    result = _agent().run_turn(
        "We finished Summer Palace. We only have 4 hours this afternoon, please replan.",
        state,
    )

    assert result.intent == "replan"
    assert "Summer Palace" in state.completed_nodes
    assert state.current_task is not None
    assert "Summer Palace" in state.current_task["completed_nodes"]


def test_llm_tool_schema_exposes_replan_itinerary():
    tool_names = {tool["function"]["name"] for tool in TOOL_SCHEMAS}

    assert "replan_itinerary" in tool_names


def test_replan_tool_call_is_source_of_truth_and_updates_state():
    state = _state()
    state.set_current_location("Hotel")
    tool_logs = []

    output = _agent()._run_tool_call(
        "replan_itinerary",
        {"time_budget_hours": 4, "skipped_nodes": ["Nanluoguxiang"]},
        state,
        tool_logs,
    )

    names = [node["poi_name"] for node in state.remaining_plan]

    assert output["source_of_truth"] == "replan_itinerary"
    assert "Nanluoguxiang" not in names
    assert state.skipped_nodes == ["Nanluoguxiang"]
    assert state.self_check_results[-1]["retry_count"] == output["retry_count"]
    assert any(log["tool"] == "replan_itinerary" for log in tool_logs)
