from __future__ import annotations

import json
from types import SimpleNamespace

from companion_agent import TOOL_SCHEMAS, CompanionAgent
from config import Settings
from constraint_extractor import classify_intent
import tools.amap as amap_tools
from tools.amap import _matches_city, _query_with_city_bias, resolve_location
from models import CompanionState
from tools.emergency import classify_emergency_scene


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


class _FakePlannerClient:
    def __init__(self, responses: list[dict | str]) -> None:
        self.responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.responses.pop(0) if self.responses else "done"
        content = json.dumps(payload) if isinstance(payload, dict) else str(payload)
        message = SimpleNamespace(
            content=content,
            tool_calls=None,
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class _FakeAmapResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


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
    assert "Nanluoguxiang" in names
    assert "National Museum" not in names
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


def test_fall_keywords_are_emergency_not_nearby_search():
    assert classify_intent("我现在在外滩，老人摔跤了怎么办") == "emergency"
    assert classify_emergency_scene("老人摔跤了怎么办") == "medical"


def test_city_bias_filters_same_named_locations_by_current_planning_city():
    off_city_same_name = {
        "city": "成都市",
        "province": "四川省",
        "district": "青羊区",
        "formatted_address": "四川省成都市青羊区人民公园上海路",
    }
    current_city_same_name = {
        "city": [],
        "province": "上海市",
        "district": "黄浦区",
        "formatted_address": "上海市黄浦区人民公园",
    }

    assert not _matches_city(off_city_same_name, "上海")
    assert _matches_city(current_city_same_name, "Shanghai")


def test_same_named_location_query_is_scoped_to_current_planning_city():
    assert _query_with_city_bias("人民公园", "Shanghai") == "上海人民公园"
    assert _query_with_city_bias("成都人民公园", "上海") == "成都人民公园"


def test_resolve_location_uses_current_city_when_geocode_returns_same_name_elsewhere(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append({"url": url, "params": params, "timeout": timeout})
        if url == amap_tools.AMAP_GEOCODE_URL:
            return _FakeAmapResponse(
                {
                    "geocodes": [
                        {
                            "city": "成都市",
                            "province": "四川省",
                            "district": "青羊区",
                            "formatted_address": "四川省成都市青羊区人民公园上海路",
                            "location": "104.063000,30.659000",
                        }
                    ]
                }
            )
        return _FakeAmapResponse(
            {
                "pois": [
                    {
                        "name": "人民公园",
                        "cityname": "上海市",
                        "adname": "黄浦区",
                        "address": "南京西路",
                        "location": "121.469000,31.230000",
                        "adcode": "310101",
                    }
                ]
            }
        )

    monkeypatch.setattr(amap_tools.requests, "get", fake_get)

    location = resolve_location(
        "人民公园",
        settings=Settings(amap_api_key="fake", default_city="北京"),
        city_bias="Shanghai",
    )

    assert calls[0]["params"]["address"] == "上海人民公园"
    assert calls[1]["params"]["citylimit"] == "true"
    assert location["city"] == "上海市"
    assert location["district"] == "黄浦区"


def test_chinese_replan_keywords_trigger_replan_task_flow():
    state = _state()
    state.set_current_location("Hotel")
    result = _agent().run_turn("我们只剩4小时了，帮我重排", state)

    assert result.intent == "replan"
    assert state.time_budget_hours == 4
    assert any(log["tool"] == "replan_itinerary" for log in result.tool_logs)


def test_llm_router_controls_emergency_flow_without_keyword_match():
    state = _state()
    state.set_current_location("Hotel")
    agent = _agent()
    agent.client = _FakePlannerClient(
        [
            {
                "intent": "emergency",
                "goal": "help traveler after a fall",
                "needs_clarification": False,
                "actions": [
                    {
                        "tool": "resolve_emergency_resources",
                        "args": {"scene": "medical", "location": "$state.current_location"},
                        "reason": "fall needs medical support",
                    }
                ],
                "response_policy": "safety_first",
            },
            "先别继续赶路，优先找现场帮助。",
        ]
    )

    result = agent.run_turn("my grandma slipped badly and needs help", state)

    assert result.intent == "emergency"
    assert any(log["tool"] == "resolve_emergency_resources" for log in result.tool_logs)
    assert agent.client.calls


def test_llm_router_controls_replan_flow_without_keyword_match():
    state = _state()
    state.set_current_location("Hotel")
    agent = _agent()
    agent.client = _FakePlannerClient(
        [
            {
                "intent": "replan",
                "goal": "make the rest of today lighter",
                "needs_clarification": False,
                "actions": [
                    {
                        "tool": "replan_itinerary",
                        "args": {"time_budget_hours": 4, "constraints": {}},
                        "reason": "lighter day request",
                    }
                ],
                "response_policy": "replan_summary",
            },
            "已帮你压缩今天剩余行程。",
        ]
    )

    result = agent.run_turn("can you make the rest of today lighter", state)

    assert result.intent == "replan"
    assert any(log["tool"] == "replan_itinerary" for log in result.tool_logs)


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
