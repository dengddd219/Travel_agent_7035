from __future__ import annotations

import json
import re
import sys
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import companion_tracer as trace
from config import Settings
from constraint_extractor import get_known_pois, classify_intent, extract_constraints
from models import AgentAction, AgentObservation, AgentPlan, AgentTurnResult, CompanionState
from token_costing import aggregate_token_usage, token_usage_from_response, with_token_cost, zero_token_usage
from tools import (
    check_time_feasibility,
    classify_emergency_scene,
    get_route,
    get_weather_now,
    replan_itinerary,
    resolve_emergency_resources,
    resolve_location,
    retrieve_candidates,
    score_candidates,
)
from tools.mock_data import get_poi_detail

try:
    from openai import AzureOpenAI, OpenAI
except Exception:  # pragma: no cover - optional dependency
    AzureOpenAI = None
    OpenAI = None


_TURN_TOKEN_USAGES: ContextVar[list[dict[str, Any]] | None] = ContextVar("turn_token_usages", default=None)


SYSTEM_PROMPT = """
你是一个旅行当天 Companion Agent。

你的目标：
1. 理解用户当前处境
2. 选择最少但必要的工具
3. 保持回复可执行，优先给出下一步动作
4. 不要假装知道实时路线、天气和周边资源，优先调用工具
5. 推荐类问题默认返回 2 个主候选，可补最多 3 个备选
6. 应急类问题优先返回安全动作与回撤路径
"""

TOOL_POLICY_PROMPT = """
工具使用硬规则：
1. 只要用户问题涉及当前位置、去哪、附近推荐、路线/时间是否来得及、天气变化或应急资源，就必须先调用至少一个工具，再给自然语言答复。
2. 未调用工具前，不能假设实时位置、天气、路线、POI 或营业信息。
3. 如果用户提到了地名、景点、商圈或“我在某地”，优先调用 `resolve_location`。
4. 如果是找吃饭/找地方/找替代点位，先用 `retrieve_candidates`，必要时再补 `score_candidates` 和 `get_route`。
5. 如果是时间协调，必须补 `get_route`，涉及景区时再补 `get_poi_detail`。
6. 如果是下雨、天气变化或应急，优先调用 `get_weather_now` 或 `resolve_emergency_resources`。
7. 如果已经有当天 `remaining_plan`，用户要求压缩、重排或保留核心体验时，调用 `replan_itinerary`，不要直接编造新行程。
8. `CompanionState.city` 是当前旅程城市。用户只说“外滩/南京路/春熙路”这类同名地点时，默认按当前城市解析；除非用户明确说了另一个城市，不要把跨城市同名地点交给用户判断。
"""

INTENT_ROUTER_PROMPT = """
You are the semantic router for an in-trip travel companion.
Classify the latest user message by meaning, not by keyword matching.

Return only a JSON object:
{"intent":"emergency|replan|coordinate|search","confidence":0.0-1.0,"reason":"short reason"}

Intent definitions:
- emergency: medical risk, injury, fall, lost, urgent toilet, safety, battery/network/help, cannot walk, needs immediate support.
- replan: change, shorten, skip, replace, delay, rain/weather disruption, closed venue, queue too long, time budget for the remaining itinerary.
- coordinate: asks whether the current route/timing can make it, route duration, latest arrival/departure, ordering feasibility.
- search: nearby food/place recommendation or general local question.

When uncertain between emergency and search, choose emergency. When uncertain between replan and search with an existing remaining_plan, choose replan.
"""

VALID_INTENTS = {"emergency", "replan", "coordinate", "search"}


ACTION_PLANNER_PROMPT = """
You are the planner/policy layer for an in-trip travel companion agent.
Use the given CompanionState and latest user message to produce a structured action plan.
Do not answer the user directly.

Return only a JSON object with this schema:
{
  "intent": "emergency|replan|coordinate|search|info",
  "goal": "short operational goal",
  "needs_clarification": true|false,
  "clarification_question": "question to ask if required",
  "state_updates": {"field": "value"},
  "actions": [
    {"tool": "tool_name", "args": {}, "reason": "why", "save_as": "optional_key"}
  ],
  "response_policy": "safety_first|replan_summary|route_advice|recommendation|answer",
  "self_check_focus": ["time_budget", "weather", "mobility", "core_experience"]
}

Available tools:
- resolve_location: args {"query": "...", "city_bias": "..."}
- get_weather_now: args {"city": "..."}
- retrieve_candidates: args {"query": "...", "city": "...", "current_location": optional object}
- score_candidates: args {"candidates": [], "context": {}}
- get_route: args {"origin": object, "dest": object, "mode": "walking|driving"}
- get_poi_detail: args {"name": "...", "city": "..."}
- replan_itinerary: args {"time_budget_hours": optional number, "completed_nodes": [], "skipped_nodes": [], "constraints": {}}
- resolve_emergency_resources: args {"scene": "medical|mobility|toilet|power|network|help|evacuate", "location": object, "base_location": optional object}

Planning rules:
- If user appears injured, unsafe, lost, unable to walk, urgently needs help, or a companion fell down, intent must be emergency.
- Emergency plans should usually call resolve_emergency_resources. If current_location is already in state, use that as location; otherwise call resolve_location first if the user gave a place, or ask for clarification.
- If user asks to change/shorten/skip/reorder today's remaining itinerary, use replan_itinerary.
- If replan needs current location and state has none and user gave none, ask a clarification question.
- If user asks for nearby food/place, use retrieve_candidates then score_candidates.
- If user asks whether timing works or route is feasible, use get_route and/or get_poi_detail.
- Prefer fewer actions, but include every tool needed to avoid guessing.
- Treat CompanionState.city as the authoritative city context. For ambiguous POI names, pass this city as city_bias and do not ask the user to choose between cities unless no city is available or the user explicitly names another city.
"""


RESPONSE_GENERATOR_PROMPT = """
You write the final user-facing reply for an in-trip travel companion.
Use only the provided action plan, observations, verification result, and state.
Do not invent routes, venues, prices, opening hours, weather, hospitals, or distances that are not in observations.

Style rules:
- Emergency: lead with immediate safety action, then nearest reliable resources or fallback safety advice.
- Replan: state the new order, deferred/removed stops, and the reason.
- Search: give 1-3 options with why they fit.
- Coordinate: answer feasibility clearly and mention uncertainty.
- Keep it concise and actionable.
- Use structured Markdown, not a dense paragraph.
- Prefer this shape:
  **结论**
  One short answer.

  **依据**
  - Route / venue / weather facts from observations.

  **下一步**
  1. The next concrete action.
  2. Optional backup action.
- If a clarification is truly needed, use **需要你确认** and ask only the missing operational detail.
- Do not ask the user to decide between same-name locations in different cities when state.city is present; silently use state.city.
"""


REPAIR_PLANNER_PROMPT = """
You repair a failed or risky in-trip companion action plan.
Given the original plan, observations, verification result, and state, return only a JSON AgentPlan object.

Use repair actions only when they materially improve the result.
Typical repairs:
- If replan has no feasible/core experience, search for a nearby replacement with retrieve_candidates and score_candidates.
- If weather or mobility constraints removed too much, search for indoor/accessibility-friendly alternatives.
- If emergency resources are missing, search broader help resources or ask for clarification.

Return the same JSON schema as the action planner. If no repair is useful, return {"intent":"info","actions":[]}.
"""


INDOOR_REPLAN_INCLUDE_KEYWORDS = [
    "博物馆",
    "美术馆",
    "艺术馆",
    "纪念馆",
    "展览馆",
    "购物中心",
    "商场",
    "书店",
    "影城",
]

INDOOR_REPLAN_EXCLUDE_KEYWORDS = [
    "广场",
    "公园",
    "景区",
    "遗址",
    "城楼",
    "河",
    "湖",
    "山",
    "园林",
]


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_location",
            "description": "Resolve a user-mentioned place into structured coordinates.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_candidates",
            "description": "Retrieve candidate POIs using expanded text queries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "city": {"type": "string"},
                    "current_location": {"type": "object"},
                },
                "required": ["query", "city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_candidates",
            "description": "Rank candidate places using deterministic constraints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidates": {"type": "array", "items": {"type": "object"}},
                    "context": {"type": "object"},
                },
                "required": ["candidates", "context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replan_itinerary",
            "description": "Deterministically replan the selected day's remaining itinerary from CompanionState. This is the source of truth for itinerary mutation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_budget_hours": {"type": "number"},
                    "completed_nodes": {"type": "array", "items": {"type": "string"}},
                    "skipped_nodes": {"type": "array", "items": {"type": "string"}},
                    "constraints": {"type": "object"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_route",
            "description": "Get route distance and duration between origin and destination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "object"},
                    "dest": {"type": "object"},
                    "mode": {"type": "string"},
                },
                "required": ["origin", "dest", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_poi_detail",
            "description": "Get detail for a scenic spot: opening hours and ticket price (from Amap), plus accessible and recommended visit duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "city": {"type": "string", "description": "City name to narrow the Amap search, e.g. '北京'"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_now",
            "description": "Get current same-day weather snapshot for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_emergency_resources",
            "description": "Resolve emergency resources for a scene near a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {"type": "string"},
                    "location": {"type": "object"},
                    "base_location": {"type": "object"},
                },
                "required": ["scene", "location"],
            },
        },
    },
]


class CompanionAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.tool_impls = {
            "resolve_location": self._tool_resolve_location,
            "retrieve_candidates": self._tool_retrieve_candidates,
            "score_candidates": self._tool_score_candidates,
            "get_route": self._tool_get_route,
            "get_poi_detail": self._tool_get_poi_detail,
            "get_weather_now": self._tool_get_weather_now,
            "resolve_emergency_resources": self._tool_resolve_emergency_resources,
            "replan_itinerary": self._tool_replan_itinerary,
        }
        self.client = None
        if self.settings.has_llm_credentials and OpenAI is not None:
            if self.settings.openai_base_url:
                client_kwargs = {
                    "api_key": self.settings.openai_api_key,
                    "base_url": self.settings.openai_base_url,
                    "timeout": self.settings.request_timeout_s,
                }
                self.client = OpenAI(**client_kwargs)
            elif self.settings.is_azure_openai and AzureOpenAI is not None:
                client_kwargs = {
                    "api_key": self.settings.openai_api_key,
                    "api_version": self.settings.openai_api_version,
                    "timeout": self.settings.request_timeout_s,
                }
                if self.settings.azure_endpoint:
                    client_kwargs["azure_endpoint"] = self.settings.azure_endpoint
                self.client = AzureOpenAI(**client_kwargs)
            else:
                client_kwargs = {
                    "api_key": self.settings.openai_api_key,
                    "timeout": self.settings.request_timeout_s,
                }
                if self.settings.openai_base_url:
                    client_kwargs["base_url"] = self.settings.openai_base_url
                self.client = OpenAI(**client_kwargs)

    def _chat_completion_create(self, **kwargs: Any) -> Any:
        response = self.client.chat.completions.create(**kwargs)
        turn_usages = _TURN_TOKEN_USAGES.get()
        if turn_usages is not None:
            turn_usages.append(
                token_usage_from_response(
                    response,
                    model=str(kwargs.get("model") or self.settings.openai_model),
                )
            )
        return response

    @staticmethod
    def _ensure_structured_reply(reply: str) -> str:
        text = (reply or "").strip()
        if not text:
            return text
        structured_markers = ("**结论**", "**依据**", "**下一步**", "**需要你确认**", "### ")
        if any(marker in text for marker in structured_markers):
            return text
        if "?" in text or "？" in text:
            return f"**需要你确认**\n{text}"
        return (
            "**结论**\n"
            f"{text}\n\n"
            "**下一步**\n"
            "1. 如果这个建议可行，就按上面第一步执行。\n"
            "2. 如果你要改目标或出行方式，直接发新的地点或“步行/打车”。"
        )

    def run_turn(self, user_input: str, state: CompanionState | None = None) -> AgentTurnResult:
        state = state or CompanionState(city=self.settings.default_city)
        token_context = _TURN_TOKEN_USAGES.set([])
        trace.event(
            "Companion turn start",
            {
                "user_input": user_input,
                "city": state.city,
                "current_location": state.current_location,
                "remaining_plan_count": len(state.remaining_plan),
                "has_llm_client": self.client is not None,
            },
            color="cyan",
        )
        state.update_time()
        self._apply_structured_constraints(user_input, state)
        state.add_turn("user", user_input)
        self._apply_progress_updates(user_input, state)
        trace.event(
            "Companion state after input parsing",
            {
                "intent": state.intent,
                "goal": state.current_goal,
                "avoid_pois": state.avoid_pois,
                "prefer_indoor": state.prefer_indoor,
                "party": state.party,
                "mobility_risk": state.mobility_risk,
                "weather_preference": state.weather_preference,
                "completed_nodes": state.completed_nodes,
                "skipped_nodes": state.skipped_nodes,
                "router_state": self._router_state_payload(state),
            },
            color="blue",
        )

        try:
            task_result = self._maybe_handle_task_flow(user_input, state)
            if task_result is not None:
                trace.event(
                    "Companion execution path",
                    {"path": "pending_task_flow", "intent": task_result.intent},
                    color="yellow",
                )
                result = task_result
            elif self.client is not None:
                try:
                    trace.event(
                        "Companion execution path",
                        {"path": "agentic_llm"},
                        color="yellow",
                    )
                    result = self._run_agentic_turn(user_input=user_input, state=state)
                except Exception as llm_exc:
                    trace.event(
                        "Companion LLM fallback",
                        {"error": f"{type(llm_exc).__name__}: {llm_exc}"},
                        color="red",
                    )
                    result = self._run_fallback_turn(user_input=user_input, state=state)
                    result.tool_logs.append(
                        {
                            "tool": "llm_fallback",
                            "arguments": {},
                            "preview": f"LLM tool-calling 不可用，已自动回退到本地规则流：{llm_exc}",
                        }
                    )
                    state.mobility_state["_llm_fallback_notified"] = True
            else:
                trace.event(
                    "Companion execution path",
                    {"path": "deterministic_fallback"},
                    color="yellow",
                )
                result = self._run_fallback_turn(user_input=user_input, state=state)
        except Exception as exc:
            trace.event(
                "Companion turn error",
                {"error": f"{type(exc).__name__}: {exc}"},
                color="red",
            )
            result = AgentTurnResult(
                reply=f"这轮请求没有成功执行：{exc}",
                intent="error",
                warnings=["已返回保守错误信息。"],
                error={"code": "turn_failed", "message": str(exc), "retryable": True},
                state=state,
            )

        if result.intent != "error":
            result.reply = self._ensure_structured_reply(result.reply)
        state.add_turn("assistant", result.reply)
        result.state = state
        turn_token_usages = _TURN_TOKEN_USAGES.get() or []
        if turn_token_usages:
            result.token_usage = aggregate_token_usage(
                turn_token_usages,
                model=self.settings.openai_model,
                source="companion_agent_turn",
            )
        elif result.token_usage:
            result.token_usage = with_token_cost(result.token_usage, model=self.settings.openai_model)
        else:
            result.token_usage = zero_token_usage(model=self.settings.openai_model, source="no_llm_call")
        _TURN_TOKEN_USAGES.reset(token_context)
        trace.event(
            "Companion turn done",
            {
                "intent": result.intent,
                "reply": result.reply,
                "warnings": result.warnings,
                "tool_logs": result.tool_logs,
                "token_usage": result.token_usage,
                "next_state": self._router_state_payload(state),
            },
            color="green",
        )
        return result

    def _apply_structured_constraints(self, user_input: str, state: CompanionState) -> None:
        extracted = extract_constraints(user_input, previous_state=state.to_dict())
        state.intent = extracted.get("intent", state.intent)
        state.current_goal = extracted.get("current_goal", state.current_goal)
        state.avoid_pois = extracted.get("avoid_pois", state.avoid_pois)
        state.prefer_indoor = bool(extracted.get("prefer_indoor", state.prefer_indoor))
        state.party = extracted.get("party", state.party)
        state.budget_level = extracted.get("budget_level", state.budget_level)
        state.food_constraints = extracted.get("food_constraints", state.food_constraints)
        state.mobility_risk = extracted.get("mobility_risk", state.mobility_risk)
        state.weather_preference = extracted.get("weather_preference", state.weather_preference)
        state.replan_reason = extracted.get("replan_reason", state.replan_reason)

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
        text = (raw_text or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _router_state_payload(state: CompanionState) -> dict[str, Any]:
        return {
            "city": state.city,
            "current_location": state.current_location,
            "remaining_plan": [
                {
                    "poi_name": node.get("poi_name") or node.get("name"),
                    "time_slot": node.get("time_slot"),
                    "duration_hours": node.get("duration_hours"),
                    "indoor_outdoor": node.get("indoor_outdoor"),
                }
                for node in state.remaining_plan[:8]
            ],
            "completed_nodes": state.completed_nodes,
            "skipped_nodes": state.skipped_nodes,
            "party": state.party,
            "mobility_risk": state.mobility_risk,
            "prefer_indoor": state.prefer_indoor,
        }

    def _llm_route_intent(self, user_input: str, state: CompanionState) -> str | None:
        if self.client is None:
            return None
        response = self._chat_completion_create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": INTENT_ROUTER_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "latest_user_message": user_input,
                            "state": self._router_state_payload(state),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        parsed = self._extract_json_object(content) or {}
        intent = str(parsed.get("intent", "")).strip().lower()
        return intent if intent in VALID_INTENTS else None

    def _route_intent(self, user_input: str, state: CompanionState) -> str | None:
        try:
            return self._llm_route_intent(user_input, state)
        except Exception as exc:
            state.mobility_state["_intent_router_error"] = str(exc)
            return None

    @classmethod
    def _coerce_agent_plan(cls, payload: dict[str, Any] | None) -> AgentPlan:
        payload = payload or {}
        intent = str(payload.get("intent") or "search").strip().lower()
        if intent not in VALID_INTENTS and intent != "info":
            intent = "search"
        actions: list[AgentAction] = []
        for item in payload.get("actions") or []:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "").strip()
            if not tool:
                continue
            args = item.get("args") if isinstance(item.get("args"), dict) else {}
            actions.append(
                AgentAction(
                    tool=tool,
                    args=dict(args),
                    reason=str(item.get("reason") or ""),
                    save_as=str(item.get("save_as") or ""),
                )
            )
        return AgentPlan(
            intent=intent,
            goal=str(payload.get("goal") or ""),
            needs_clarification=bool(payload.get("needs_clarification")),
            clarification_question=str(payload.get("clarification_question") or ""),
            state_updates=payload.get("state_updates") if isinstance(payload.get("state_updates"), dict) else {},
            actions=actions,
            response_policy=str(payload.get("response_policy") or "default"),
            self_check_focus=[str(item) for item in payload.get("self_check_focus") or [] if str(item)],
            raw=dict(payload),
        )

    def _llm_plan_actions(self, user_input: str, state: CompanionState) -> AgentPlan:
        response = self._chat_completion_create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": ACTION_PLANNER_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "latest_user_message": user_input,
                            "companion_state": self._router_state_payload(state),
                            "recent_turns": state.turn_history[-6:],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        plan = self._coerce_agent_plan(self._extract_json_object(content))
        trace.event(
            "Companion LLM action plan",
            {
                "raw_output": content,
                "coerced_plan": plan.raw,
                "intent": plan.intent,
                "goal": plan.goal,
                "needs_clarification": plan.needs_clarification,
                "actions": [
                    {
                        "tool": action.tool,
                        "args": action.args,
                        "reason": action.reason,
                        "save_as": action.save_as,
                    }
                    for action in plan.actions
                ],
            },
            color="blue",
        )
        return plan

    def _apply_plan_state_updates(self, plan: AgentPlan, state: CompanionState) -> None:
        allowed_scalars = {
            "intent",
            "current_goal",
            "prefer_indoor",
            "budget_level",
            "mobility_risk",
            "weather_preference",
            "replan_reason",
            "time_budget_hours",
            "base_location",
        }
        for key, value in plan.state_updates.items():
            if key not in allowed_scalars:
                continue
            if key == "time_budget_hours" and value is not None:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            setattr(state, key, value)
        if plan.intent:
            state.intent = plan.intent

    def _current_location_payload(self, state: CompanionState) -> dict[str, Any] | None:
        if not state.current_location:
            return None
        payload = {
            "name": state.current_location,
            "city": state.city or self.settings.default_city,
            "lat": state.current_coords[0] if state.current_coords else 0.0,
            "lon": state.current_coords[1] if state.current_coords else 0.0,
        }
        return payload

    def _resolve_action_value(self, value: Any, state: CompanionState, saved: dict[str, Any]) -> Any:
        if isinstance(value, str):
            if value == "$state.current_location":
                return self._current_location_payload(state)
            if value == "$state.city":
                return state.city
            if value == "$state.remaining_plan":
                return state.remaining_plan
            if value == "$state.completed_nodes":
                return state.completed_nodes
            if value == "$state.skipped_nodes":
                return state.skipped_nodes
            if value == "$state.time_budget_hours":
                return state.time_budget_hours
            if value.startswith("$obs."):
                return saved.get(value[5:])
            return value
        if isinstance(value, dict):
            return {key: self._resolve_action_value(item, state, saved) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_action_value(item, state, saved) for item in value]
        return value

    def _prepare_action_args(self, action: AgentAction, state: CompanionState, saved: dict[str, Any]) -> dict[str, Any]:
        args = self._resolve_action_value(dict(action.args), state, saved)
        if action.tool == "resolve_location":
            args.setdefault("city_bias", state.city or self.settings.default_city)
        elif action.tool == "resolve_emergency_resources":
            args.setdefault("scene", "help")
            args.setdefault("location", self._current_location_payload(state) or {"name": state.city, "city": state.city, "lat": 0.0, "lon": 0.0})
        elif action.tool == "retrieve_candidates":
            args.setdefault("city", state.city or self.settings.default_city)
            args.setdefault("current_location", self._current_location_payload(state))
        elif action.tool == "score_candidates":
            args.setdefault("candidates", saved.get("candidates") or [])
            args.setdefault("context", self._context_payload(state, self._current_location_payload(state)))
        elif action.tool == "get_weather_now":
            args.setdefault("city", state.city or self.settings.default_city)
        elif action.tool == "replan_itinerary":
            args.setdefault("time_budget_hours", state.time_budget_hours)
            args.setdefault("completed_nodes", state.completed_nodes)
            args.setdefault("skipped_nodes", state.skipped_nodes)
            constraints = self._replan_constraints(state, args.get("time_budget_hours"))
            constraints.update(args.get("constraints") or {})
            args["constraints"] = constraints
        return args

    def _execute_action_plan(
        self,
        plan: AgentPlan,
        state: CompanionState,
        tool_logs: list[dict[str, Any]],
    ) -> list[AgentObservation]:
        saved: dict[str, Any] = {}
        observations: list[AgentObservation] = []
        for action in plan.actions:
            args = self._prepare_action_args(action, state, saved)
            trace.event(
                "Companion action",
                {
                    "tool": action.tool,
                    "reason": action.reason,
                    "save_as": action.save_as or action.tool,
                    "prepared_args": args,
                },
                color="yellow",
            )
            output = self._run_tool_call(action.tool, args, state, tool_logs)
            save_as = action.save_as or action.tool
            saved[save_as] = output
            if action.tool == "resolve_location" and isinstance(output, dict):
                saved.setdefault("current_location", output)
                state.city = output.get("city") or state.city
                state.set_current_location(
                    output.get("name", state.current_location),
                    (output.get("lat", 0.0), output.get("lon", 0.0)),
                )
            elif action.tool == "retrieve_candidates":
                saved.setdefault("candidates", output)
            elif action.tool == "score_candidates" and isinstance(output, dict):
                saved.setdefault("ranking", output)
            observations.append(AgentObservation(tool=action.tool, args=args, output=output, save_as=save_as))
        return observations

    @staticmethod
    def _observation_payload(observations: list[AgentObservation]) -> list[dict[str, Any]]:
        return [
            {
                "tool": obs.tool,
                "args": obs.args,
                "save_as": obs.save_as,
                "output": obs.output,
            }
            for obs in observations
        ]

    def _verify_agentic_turn(
        self,
        plan: AgentPlan,
        observations: list[AgentObservation],
        state: CompanionState,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        reasons: list[str] = []
        tools_used = {obs.tool for obs in observations}
        if plan.intent == "emergency" and "resolve_emergency_resources" not in tools_used:
            reasons.append("missing_emergency_resources")
            warnings.append("Emergency intent did not call emergency resource resolver.")
        if plan.intent == "replan" and "replan_itinerary" not in tools_used:
            reasons.append("missing_replan")
            warnings.append("Replan intent did not call replan_itinerary.")
        needs_second_search = False
        for obs in observations:
            if obs.tool != "replan_itinerary" or not isinstance(obs.output, dict):
                continue
            self_check = obs.output.get("self_check") or {}
            for reason in self_check.get("reasons") or []:
                if reason not in reasons:
                    reasons.append(reason)
            warnings.extend(item for item in obs.output.get("warnings") or [] if item not in warnings)
            needs_second_search = needs_second_search or obs.output.get("status") == "no_feasible_plan"
            needs_second_search = needs_second_search or "no_core_experience" in (self_check.get("reasons") or [])
        return {
            "ok": not reasons,
            "reasons": reasons,
            "warnings": warnings,
            "needs_second_search": needs_second_search,
        }

    def _fallback_reply_from_observations(
        self,
        plan: AgentPlan,
        observations: list[AgentObservation],
        verification: dict[str, Any],
    ) -> str:
        if plan.needs_clarification:
            return plan.clarification_question or "我还需要一个关键信息才能继续。"
        for obs in reversed(observations):
            if obs.tool == "replan_itinerary" and isinstance(obs.output, dict):
                summary = obs.output.get("summary") or "已完成当天剩余行程重排。"
                return f"**结论**\n{summary}\n\n**下一步**\n1. 按新顺序走，先保留优先级最高的站点。\n2. 如果现场又变动，继续告诉我当前位置和剩余时间。"
            if obs.tool == "resolve_emergency_resources" and isinstance(obs.output, dict):
                immediate = obs.output.get("immediate_action") or {}
                note = (obs.output.get("safety_notes") or [""])[0]
                action = immediate.get("summary") or "优先找最近游客中心、保安亭或出口。"
                note_line = f"\n- {note}" if note else "\n- 如果症状加重，直接联系现场工作人员或急救。"
                return f"**结论**\n先别继续赶路。{action}\n\n**安全提醒**{note_line}"
            if obs.tool == "score_candidates" and isinstance(obs.output, dict):
                primary = obs.output.get("primary") or []
                if primary:
                    names = "、".join(str(item.get("name", "")) for item in primary[:3])
                    return f"**结论**\n我优先建议：{names}。\n\n**下一步**\n1. 选一家后，我继续帮你算路线。\n2. 如果想换菜系或预算，直接补充条件。"
        if verification.get("warnings"):
            warning_lines = "\n".join(f"- {item}" for item in verification["warnings"])
            return f"**结论**\n我完成了检查，但还有风险。\n\n**风险**\n{warning_lines}"
        return "**结论**\n我已经根据当前状态完成处理。"

    def _generate_final_response(
        self,
        plan: AgentPlan,
        observations: list[AgentObservation],
        verification: dict[str, Any],
        state: CompanionState,
    ) -> str:
        try:
            response = self._chat_completion_create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": RESPONSE_GENERATOR_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "action_plan": plan.raw,
                                "observations": self._observation_payload(observations),
                                "verification": verification,
                                "state": self._router_state_payload(state),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
            reply = (response.choices[0].message.content or "").strip()
            trace.event(
                "Companion response LLM output",
                {"reply": reply},
                color="green",
            )
            return reply or self._fallback_reply_from_observations(plan, observations, verification)
        except Exception as exc:
            trace.event(
                "Companion response fallback",
                {"error": f"{type(exc).__name__}: {exc}"},
                color="red",
            )
            return self._fallback_reply_from_observations(plan, observations, verification)

    def _llm_repair_plan(
        self,
        plan: AgentPlan,
        observations: list[AgentObservation],
        verification: dict[str, Any],
        state: CompanionState,
    ) -> AgentPlan:
        response = self._chat_completion_create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": REPAIR_PLANNER_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "original_plan": plan.raw,
                            "observations": self._observation_payload(observations),
                            "verification": verification,
                            "state": self._router_state_payload(state),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        repair_plan = self._coerce_agent_plan(self._extract_json_object(content))
        trace.event(
            "Companion LLM repair output",
            {
                "raw_output": content,
                "coerced_plan": repair_plan.raw,
            },
            color="blue",
        )
        return repair_plan

    def _run_agentic_turn(self, user_input: str, state: CompanionState) -> AgentTurnResult:
        plan = self._llm_plan_actions(user_input, state)
        self._apply_plan_state_updates(plan, state)
        tool_logs: list[dict[str, Any]] = [
            {
                "tool": "agent_plan",
                "arguments": {"user_input": user_input},
                "preview": json.dumps(plan.raw, ensure_ascii=False)[:500],
            }
        ]
        if plan.needs_clarification:
            trace.event(
                "Companion clarification needed",
                {
                    "intent": plan.intent,
                    "goal": plan.goal,
                    "question": plan.clarification_question,
                    "plan": plan.raw,
                },
                color="yellow",
            )
            state.current_task = {
                "intent": plan.intent,
                "goal": plan.goal,
                "plan": plan.raw,
            }
            state.task_status = "needs_clarification"
            state.clarification_pending = "agent_plan"
            return AgentTurnResult(
                reply=plan.clarification_question or "我还需要一个关键信息才能继续。",
                intent=plan.intent,
                tool_logs=tool_logs,
            )
        observations = self._execute_action_plan(plan, state, tool_logs)
        verification = self._verify_agentic_turn(plan, observations, state)
        trace.event(
            "Companion verification",
            verification,
            color="blue",
        )
        if verification.get("needs_second_search"):
            try:
                repair_plan = self._llm_repair_plan(plan, observations, verification, state)
                if repair_plan.actions:
                    trace.event(
                        "Companion repair plan",
                        {
                            "reason": verification.get("reasons", []),
                            "plan": repair_plan.raw,
                        },
                        color="yellow",
                    )
                    tool_logs.append(
                        {
                            "tool": "agent_repair_plan",
                            "arguments": {"reason": verification.get("reasons", [])},
                            "preview": json.dumps(repair_plan.raw, ensure_ascii=False)[:500],
                        }
                    )
                    self._apply_plan_state_updates(repair_plan, state)
                    repair_observations = self._execute_action_plan(repair_plan, state, tool_logs)
                    observations.extend(repair_observations)
                    verification = self._verify_agentic_turn(repair_plan, observations, state)
            except Exception as exc:
                verification.setdefault("warnings", []).append(f"Repair planning failed: {exc}")
        reply = self._generate_final_response(plan, observations, verification, state)
        trace.event(
            "Companion generated reply",
            {
                "reply": reply,
                "observation_count": len(observations),
                "verification": verification,
            },
            color="green",
        )
        cards = [
            {"tool": obs.tool, "payload": obs.output}
            for obs in observations
            if obs.tool in {"replan_itinerary", "resolve_emergency_resources", "score_candidates"}
        ]
        return AgentTurnResult(
            reply=reply,
            intent=plan.intent,
            cards=cards,
            tool_logs=tool_logs,
            warnings=list(verification.get("warnings") or []),
        )

    def _apply_progress_updates(self, user_input: str, state: CompanionState) -> None:
        completed_markers = ["finished", "completed", "done with", "逛完", "玩完", "已经去了", "已经看完"]
        skipped_markers = ["skip", "skipped", "do not want to go", "don't want to go", "不想去", "不去了", "跳过", "放弃"]
        lowered = user_input.lower()
        mentioned = self._mentioned_plan_nodes(user_input, state)

        if any(marker in lowered or marker in user_input for marker in completed_markers):
            for name in mentioned:
                if name not in state.completed_nodes:
                    state.completed_nodes.append(name)
                if name in state.skipped_nodes:
                    state.skipped_nodes.remove(name)

        if any(marker in lowered or marker in user_input for marker in skipped_markers):
            for name in mentioned:
                if name not in state.skipped_nodes:
                    state.skipped_nodes.append(name)
                if name in state.completed_nodes:
                    state.completed_nodes.remove(name)

    def _mentioned_plan_nodes(self, user_input: str, state: CompanionState) -> list[str]:
        lowered = user_input.lower()
        matches: list[str] = []
        for node in state.remaining_plan:
            name = str(node.get("poi_name") or node.get("name") or "").strip()
            if name and name.lower() in lowered:
                matches.append(name)
        return matches

    def _maybe_handle_task_flow(
        self,
        user_input: str,
        state: CompanionState,
        routed_intent: str | None = None,
    ) -> AgentTurnResult | None:
        if state.clarification_pending:
            return self._resume_pending_task(user_input, state)

        intent = routed_intent or self._classify_intent(user_input)
        if intent != "replan" or not state.remaining_plan:
            return None

        task = self._create_replan_task(user_input, state)
        tool_logs: list[dict[str, Any]] = []
        if not state.current_location:
            self._extract_current_location(user_input, state, tool_logs)
        if not state.current_location:
            state.current_task = task
            state.task_status = "needs_clarification"
            state.clarification_pending = "current_location"
            state.clarification_resume_intent = "replan"
            return AgentTurnResult(
                reply="我可以帮你重排当天剩余行程。先告诉我你们现在在哪里，例如“我在酒店/颐和园门口”。",
                intent="replan",
                warnings=["缺少当前位置，已暂停重排任务。"],
            )

        state.current_task = task
        return self._execute_task(state, tool_logs=tool_logs)

    def _create_replan_task(self, user_input: str, state: CompanionState) -> dict[str, Any]:
        time_budget = self._extract_time_budget_hours(user_input) or state.time_budget_hours
        if time_budget is not None:
            state.time_budget_hours = time_budget
        task = {
            "intent": "replan",
            "original_input": user_input,
            "time_budget_hours": time_budget,
            "completed_nodes": list(state.completed_nodes),
            "skipped_nodes": list(state.skipped_nodes),
            "constraints": self._replan_constraints(state, time_budget),
        }
        state.task_stack.append(task)
        state.subtasks = [
            {"name": "read_remaining_plan", "status": "done"},
            {"name": "filter_completed_and_skipped", "status": "pending"},
            {"name": "fit_time_budget", "status": "pending"},
            {"name": "validate_plan", "status": "pending"},
        ]
        state.task_status = "running"
        return task

    def _resume_pending_task(self, user_input: str, state: CompanionState) -> AgentTurnResult:
        tool_logs: list[dict[str, Any]] = []
        if state.clarification_pending == "current_location":
            location = self._extract_current_location(user_input, state, tool_logs)
            if not location:
                return AgentTurnResult(
                    reply="我还需要你们现在的具体位置，才能继续重排。可以直接说“我在酒店”或“我在颐和园门口”。",
                    intent=state.clarification_resume_intent or state.intent or "replan",
                    warnings=["仍缺少当前位置。"],
                    tool_logs=tool_logs,
                )
            state.clarification_pending = None

        resume_intent = state.clarification_resume_intent or (state.current_task or {}).get("intent")
        state.clarification_resume_intent = None
        if resume_intent == "replan" and state.current_task:
            return self._execute_task(state, tool_logs=tool_logs)
        return AgentTurnResult(
            reply="当前位置已经更新。我还没有可恢复的重排任务，请再告诉我你想怎么调整今天的行程。",
            intent=resume_intent or "search",
            tool_logs=tool_logs,
        )

    def _execute_task(self, state: CompanionState, tool_logs: list[dict[str, Any]]) -> AgentTurnResult:
        task = state.current_task or {}
        if task.get("intent") != "replan":
            return AgentTurnResult(
                reply="当前任务类型暂时不能自动执行。",
                intent=str(task.get("intent") or "unknown"),
                warnings=["unsupported_task"],
                tool_logs=tool_logs,
            )

        time_budget = task.get("time_budget_hours") or state.time_budget_hours
        arguments = {
            "time_budget_hours": time_budget,
            "completed_nodes": state.completed_nodes,
            "skipped_nodes": state.skipped_nodes,
            "constraints": task.get("constraints") or self._replan_constraints(state, time_budget),
        }
        trace.event(
            "Companion pending task",
            {"task": task, "tool": "replan_itinerary", "arguments": arguments},
            color="yellow",
        )
        started_at = time.monotonic()
        trace.tool_start("replan_itinerary", arguments)
        try:
            result = replan_itinerary(
                remaining_plan=state.remaining_plan,
                current_location=state.current_location,
                time_budget_hours=time_budget,
                completed_nodes=state.completed_nodes,
                skipped_nodes=state.skipped_nodes,
                constraints=arguments["constraints"],
            )
        except Exception as exc:
            trace.tool_error("replan_itinerary", arguments, exc, int((time.monotonic() - started_at) * 1000))
            raise
        trace.tool_finish("replan_itinerary", arguments, result, int((time.monotonic() - started_at) * 1000))
        tool_logs.append(
            {
                "tool": "replan_itinerary",
                "arguments": arguments,
                "preview": result.get("summary", "")[:500],
            }
        )

        state.remaining_plan = list(result.get("new_plan") or [])
        state.deferred_nodes = [
            str(node.get("poi_name") or node.get("name") or "")
            for node in result.get("deferred_nodes", [])
            if node.get("poi_name") or node.get("name")
        ]
        state.self_check_results.append(
            {
                "final": result.get("self_check", {}),
                "history": result.get("self_check_history", []),
                "retry_count": result.get("retry_count", 0),
            }
        )
        state.task_status = "completed" if result.get("status") == "ok" else str(result.get("status") or "completed")
        state.subtasks = [
            {"name": "read_remaining_plan", "status": "done"},
            {"name": "filter_completed_and_skipped", "status": "done"},
            {"name": "fit_time_budget", "status": "done"},
            {"name": "validate_plan", "status": "done"},
        ]
        state.current_task = None

        plan_names = [str(node.get("poi_name") or node.get("name") or "") for node in result.get("new_plan", [])]
        reply = f"**结论**\n{result.get('summary') or '已完成当天剩余行程重排。'}"
        if plan_names:
            order_lines = "\n".join(f"{idx + 1}. {name}" for idx, name in enumerate(plan_names))
            reply += f"\n\n**新顺序**\n{order_lines}"
        if result.get("warnings"):
            warning_lines = "\n".join(f"- {item}" for item in result["warnings"])
            reply += f"\n\n**风险**\n{warning_lines}"
        reply += "\n\n**下一步**\n1. 先按新顺序去第一站。\n2. 如果现场时间继续变化，告诉我当前位置和剩余时间。"
        return AgentTurnResult(
            reply=reply,
            intent="replan",
            cards=[{"plan_type": "replanned_itinerary", **result}],
            tool_logs=tool_logs,
            warnings=list(result.get("warnings") or []),
        )

    def _replan_constraints(self, state: CompanionState, time_budget_hours: float | None) -> dict[str, Any]:
        return {
            "avoid_pois": list(state.avoid_pois),
            "prefer_indoor": state.prefer_indoor,
            "mobility_risk": state.mobility_risk,
            "current_time": state.current_time,
            "time_budget_hours": time_budget_hours,
        }

    def _extract_time_budget_hours(self, text: str) -> float | None:
        patterns = [
            r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b",
            r"(\d+(?:\.\d+)?)\s*(?:小时|小時|个小时)",
        ]
        lowered = text.lower()
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
        return None

    def _run_llm_turn(
        self,
        user_input: str,
        state: CompanionState,
        routed_intent: str | None = None,
    ) -> AgentTurnResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": TOOL_POLICY_PROMPT},
            {
                "role": "system",
                "content": json.dumps(
                    {
                        "semantic_intent": routed_intent or state.intent,
                        "companion_state": self._router_state_payload(state),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        messages.extend(state.turn_history[-10:])

        tool_logs: list[dict[str, Any]] = []
        llm_call_count = 0
        total_input_tokens = 0
        total_output_tokens = 0
        require_tool_first = self._should_require_tool_first(user_input, state)

        while True:
            response = self._chat_completion_create(
                model=self.settings.openai_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="required" if require_tool_first and not tool_logs else "auto",
            )
            llm_call_count += 1

            # Accumulate real token usage from the API response
            if response.usage is not None:
                total_input_tokens += response.usage.prompt_tokens
                total_output_tokens += response.usage.completion_tokens

            message = response.choices[0].message
            tool_calls = list(message.tool_calls or [])
            trace.event(
                "Companion tool-calling LLM output",
                {
                    "llm_call_count": llm_call_count,
                    "message_content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments or "{}",
                        }
                        for tool_call in tool_calls
                    ],
                },
                color="blue",
            )
            if not tool_calls:
                reply = (message.content or "").strip() or "暂时没有得到可执行结论。"
                intent = routed_intent or self._classify_intent(user_input)
                token_usage = {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                    "llm_call_count": llm_call_count,
                    "model": self.settings.openai_model,
                    "source": "api_usage_field",
                }
                return AgentTurnResult(
                    reply=reply,
                    intent=intent,
                    tool_logs=tool_logs,
                    token_usage=token_usage,
                )

            messages.append({"role": "assistant", "content": message.content or "", "tool_calls": tool_calls})
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments or "{}")
                output = self._run_tool_call(tool_name, arguments, state, tool_logs)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(output, ensure_ascii=False),
                    }
                )

    def _run_fallback_turn(
        self,
        user_input: str,
        state: CompanionState,
        routed_intent: str | None = None,
    ) -> AgentTurnResult:
        intent = routed_intent or self._classify_intent(user_input)
        tool_logs: list[dict[str, Any]] = []
        trace.event(
            "Companion fallback router",
            {
                "intent": intent,
                "routed_intent": routed_intent,
                "user_input": user_input,
            },
            color="blue",
        )

        if intent == "emergency":
            result = self._handle_emergency(user_input, state, tool_logs)
        elif intent == "coordinate":
            result = self._handle_coordinate(user_input, state, tool_logs)
        elif intent == "replan":
            result = self._handle_replan(user_input, state, tool_logs)
        else:
            result = self._handle_search(user_input, state, tool_logs)

        result.token_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_call_count": 0,
            "model": self.settings.openai_model,
            "source": "fallback_no_llm",
        }
        return result

    def _run_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        state: CompanionState,
        tool_logs: list[dict[str, Any]],
    ) -> Any:
        if tool_name not in self.tool_impls:
            raise KeyError(f"Unknown tool: {tool_name}")
        started_at = time.monotonic()
        trace.tool_start(tool_name, arguments)
        try:
            output = self.tool_impls[tool_name](arguments, state)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            trace.tool_error(tool_name, arguments, exc, elapsed_ms)
            raise
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        trace.tool_finish(tool_name, arguments, output, elapsed_ms)
        tool_logs.append({"tool": tool_name, "arguments": arguments, "preview": str(output)[:500]})
        return output

    def _tool_resolve_location(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        location = resolve_location(
            arguments["query"],
            settings=self.settings,
            city_bias=arguments.get("city_bias") or state.city or self.settings.default_city,
        )
        return location

    def _tool_retrieve_candidates(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        return retrieve_candidates(
            query=arguments["query"],
            city=arguments["city"],
            current_location=arguments.get("current_location"),
            settings=self.settings,
        )

    def _tool_score_candidates(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        return score_candidates(arguments["candidates"], arguments["context"])

    def _tool_replan_itinerary(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        time_budget = arguments.get("time_budget_hours") or state.time_budget_hours
        if time_budget is not None:
            state.time_budget_hours = float(time_budget)

        completed_nodes = arguments.get("completed_nodes") or state.completed_nodes
        skipped_nodes = arguments.get("skipped_nodes") or state.skipped_nodes
        constraints = self._replan_constraints(state, state.time_budget_hours)
        constraints.update(arguments.get("constraints") or {})

        result = replan_itinerary(
            remaining_plan=state.remaining_plan,
            current_location=state.current_location,
            time_budget_hours=state.time_budget_hours,
            completed_nodes=completed_nodes,
            skipped_nodes=skipped_nodes,
            constraints=constraints,
        )
        state.completed_nodes = list(completed_nodes)
        state.skipped_nodes = list(skipped_nodes)
        state.remaining_plan = list(result.get("new_plan") or [])
        state.deferred_nodes = [
            str(node.get("poi_name") or node.get("name") or "")
            for node in result.get("deferred_nodes", [])
            if node.get("poi_name") or node.get("name")
        ]
        state.self_check_results.append(
            {
                "final": result.get("self_check", {}),
                "history": result.get("self_check_history", []),
                "retry_count": result.get("retry_count", 0),
            }
        )
        return {"source_of_truth": "replan_itinerary", **result}

    def _tool_get_route(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        return get_route(
            origin=arguments["origin"],
            dest=arguments["dest"],
            mode=arguments.get("mode", "walking"),
            settings=self.settings,
        )

    def _tool_get_poi_detail(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        return get_poi_detail(
            arguments["name"],
            city=arguments.get("city") or state.city or "",
            settings=self.settings,
        )

    def _tool_get_weather_now(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        weather = get_weather_now(arguments["city"], settings=self.settings)
        state.weather_snapshot = weather
        return weather

    def _tool_resolve_emergency_resources(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        return resolve_emergency_resources(
            scene=arguments["scene"],
            location=arguments["location"],
            base_location=arguments.get("base_location"),
            settings=self.settings,
        )

    def _classify_intent(self, text: str) -> str:
        lowered = text.strip().lower()
        if any(
            token in lowered
            for token in [
                "replan",
                "reschedule",
                "reroute",
                "only have",
                "hours left",
                "重排",
                "重新安排",
                "调整行程",
                "改行程",
                "只剩",
                "剩下",
                "来不及",
            ]
        ):
            return "replan"
        return classify_intent(text)

    def _should_require_tool_first(self, text: str, state: CompanionState) -> bool:
        intent = self._classify_intent(text)
        if intent not in {"search", "coordinate", "replan", "emergency"}:
            return False

        if state.current_location:
            return True

        if re.search(r"(?:我在|我们在|在).{1,20}", text):
            return True

        if self._extract_mentioned_poi(text):
            return True

        return bool(self._extract_destinations(text))

    def _extract_current_location(self, text: str, state: CompanionState, tool_logs: list[dict[str, Any]]) -> dict[str, Any] | None:
        match = re.search(
            r"(?:我在|我们在|在|i am at|i'm at|we are at|we're at)(.+?)(?:，|,|。|\.|想|要|还|逛|吃|走不动|腿疼|下雨|$)",
            text,
            flags=re.IGNORECASE,
        )
        query = match.group(1).strip() if match else state.current_location
        if not query:
            return None
        location = self._run_tool_call(
            "resolve_location",
            {"query": query, "city_bias": state.city or self.settings.default_city},
            state,
            tool_logs,
        )
        state.city = location.get("city") or state.city
        state.set_current_location(location.get("name", query), (location.get("lat", 0.0), location.get("lon", 0.0)))
        return location

    def _extract_constraints(self, text: str, state: CompanionState) -> None:
        for token in ["不吃辣", "不喜欢北京菜", "预算高", "预算高一点", "需要无障碍"]:
            if token in text and token not in state.confirmed_constraints:
                state.confirmed_constraints.append(token)
        if any(token in text for token in ["老人", "长辈"]):
            state.party["elderly"] = max(1, int(state.party.get("elderly", 0) or 0))
        if any(token in text for token in ["小孩", "孩子", "亲子"]):
            state.party["children"] = max(1, int(state.party.get("children", 0) or 0))

    def _extract_destinations(self, text: str, city: str = "") -> list[str]:
        ordered_matches: list[tuple[int, str]] = []
        for poi_name in get_known_pois(city):
            index = text.find(poi_name)
            if index >= 0:
                ordered_matches.append((index, poi_name))
        if ordered_matches:
            ordered_matches.sort(key=lambda item: item[0])
            seen: set[str] = set()
            results: list[str] = []
            for _, poi_name in ordered_matches:
                if poi_name not in seen:
                    seen.add(poi_name)
                    results.append(poi_name)
            return results

        if "去" not in text:
            return []
        suffix = text.split("去", 1)[1]
        suffix = re.split(r"[？?。,.，]", suffix)[0]
        parts = re.split(r"[、/及]", suffix)
        results = []
        for part in parts:
            value = part.strip()
            if value and len(value) >= 2:
                results.append(value)
        return results

    def _extract_mentioned_poi(self, text: str, city: str = "") -> str | None:
        ordered_matches: list[tuple[int, str]] = []
        for poi_name in get_known_pois(city):
            index = text.find(poi_name)
            if index >= 0:
                ordered_matches.append((index, poi_name))
        if not ordered_matches:
            return None
        ordered_matches.sort(key=lambda item: item[0])
        return ordered_matches[0][1]

    def _filter_replan_candidates(
        self,
        candidates: list[dict[str, Any]],
        target_poi_name: str | None,
        state: CompanionState,
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        target_name = (target_poi_name or "").strip()
        for candidate in candidates:
            name = str(candidate.get("name", "")).strip()
            type_text = str(candidate.get("type_text", "")).strip()
            haystack = f"{name} {type_text}"

            if target_name and (name == target_name or target_name in name):
                continue
            if any(poi_name and (name == poi_name or poi_name in name) for poi_name in state.avoid_pois):
                continue
            if any(keyword in haystack for keyword in INDOOR_REPLAN_EXCLUDE_KEYWORDS):
                continue
            if not any(keyword in haystack for keyword in INDOOR_REPLAN_INCLUDE_KEYWORDS):
                continue
            filtered.append(candidate)
        return filtered

    def _context_payload(self, state: CompanionState, current_location: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "confirmed_constraints": state.confirmed_constraints,
            "inferred_constraints": state.inferred_constraints,
            "party": state.party,
            "current_time": state.current_time,
            "remaining_plan": state.remaining_plan,
            "current_location": current_location,
            "avoid_pois": state.avoid_pois,
            "prefer_indoor": state.prefer_indoor,
            "budget_level": state.budget_level,
            "food_constraints": state.food_constraints,
            "mobility_risk": state.mobility_risk,
        }

    def _adjust_stay_duration_for_party(self, base_duration_min: int, state: CompanionState, poi_name: str) -> int:
        adjusted = int(base_duration_min)
        elderly = int(state.party.get("elderly", 0) or 0)
        children = int(state.party.get("children", 0) or 0)

        if elderly > 0:
            adjusted += 30
        if children > 0:
            adjusted += 20
        if any(keyword in poi_name for keyword in ["颐和园", "故宫", "天安门", "天坛"]):
            adjusted += 20
        return adjusted

    def _party_feasibility_warnings(
        self,
        state: CompanionState,
        stops: list[dict[str, Any]],
        feasibility: dict[str, Any],
    ) -> list[str]:
        warnings: list[str] = []
        elderly = int(state.party.get("elderly", 0) or 0)
        children = int(state.party.get("children", 0) or 0)
        total_travel_min = int(feasibility.get("total_travel_min", 0) or 0)
        total_stay_min = int(feasibility.get("total_stay_min", 0) or 0)
        total_load_min = total_travel_min + total_stay_min

        if len(stops) >= 2 and any(stop["name"] in {"天安门", "天安门广场", "颐和园", "故宫", "天坛"} for stop in stops):
            if elderly > 0 or children > 0:
                warnings.append("同行有老人或小孩时，下午连续安排两个大景点通常偏赶，体力负担较高。")

        if elderly > 0 and total_load_min >= 240:
            warnings.append("按老人同行估算，这组行程总耗时偏长，中途最好安排明确休息点，否则体验会明显下降。")

        if children > 0 and total_load_min >= 210:
            warnings.append("按带小孩估算，这组安排后段更容易出现疲劳、催返或临时改计划。")

        if elderly > 0 and total_travel_min >= 60:
            warnings.append("跨城区移动时间已经不短，老人同行时不建议再叠加高步行量景点。")

        return warnings

    def _build_coordinate_alternatives(
        self,
        state: CompanionState,
        cards: list[dict[str, Any]],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if not cards:
            return []

        first = cards[0]
        alternatives: list[dict[str, Any]] = []
        alternatives.append(
            {
                "plan_type": "alternative",
                "title": "方案A：只保留第一站",
                "summary": f"优先只去 `{first['destination']['name']}`，减少跨城区移动和连续大景点负担。",
                "reason": "当前安排偏赶时，先保住第一站通常更稳。",
            }
        )

        if len(cards) > 1:
            last = cards[-1]
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": "方案B：直接去后面的大景点",
                    "summary": f"放弃前面的顺路点，直接去 `{last['destination']['name']}`，把主要游览时间留给核心景点。",
                    "reason": "对老人/小孩同行时，少切换、少折返通常体验更好。",
                }
            )

        if warnings:
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": "方案C：缩短当天目标",
                    "summary": "今天只完成一个大景点，另一个顺延到明天或改成附近室内点。",
                    "reason": "当前风险提示说明体力或时间都偏紧。",
                }
            )
        return alternatives[:3]

    def _build_replan_alternatives(
        self,
        state: CompanionState,
        target_poi_name: str | None,
        primary: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        alternatives: list[dict[str, Any]] = []
        if primary:
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": "方案A：切换到最近室内替代",
                    "summary": f"放弃 `{target_poi_name or '原目标'}`，改去 `{primary[0].get('name', '')}`。",
                    "reason": "保持当天节奏不散，同时规避下雨带来的体验下降。",
                }
            )
        if len(primary) > 1:
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": "方案B：去第二候选并压缩行程",
                    "summary": f"如果第一候选排队或不合适，可改去 `{primary[1].get('name', '')}`，并减少今天的其他室外活动。",
                    "reason": "保留机动性，避免把全部决策押在一个点位上。",
                }
            )
        alternatives.append(
            {
                "plan_type": "alternative",
                "title": "方案C：直接回到商场/综合体休整",
                "summary": "如果同行人已经明显疲劳，就不要强行补替代点，优先就近休整或吃饭。",
                "reason": "雨天临时改计划时，休整本身也是合理选择。",
            }
        )
        return alternatives[:3]

    def _build_emergency_alternatives(
        self,
        resources: dict[str, Any],
    ) -> list[dict[str, Any]]:
        alternatives: list[dict[str, Any]] = []
        primary = resources.get("primary_actions", []) or []
        backup = resources.get("backup_actions", []) or []

        if primary:
            first = primary[0]
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": "方案A：就近处置",
                    "summary": f"先去 `{first.get('name', '')}` 做当前最短路径处理。",
                    "reason": "适合症状不重但需要马上处理的情况。",
                }
            )

        return_to_base = next((item for item in primary if item.get("action_type") == "return_to_base"), None)
        if return_to_base:
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": "方案B：直接回撤",
                    "summary": f"停止后续游览，直接回 `{return_to_base.get('name', '集合点')}` 休息。",
                    "reason": "如果老人/伤者已经无法继续步行，这是更稳的处理方式。",
                }
            )
        elif backup:
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": "方案B：升级到更稳妥资源",
                    "summary": f"如果就近点不适合，改去 `{backup[0].get('name', '')}`。",
                    "reason": "适合需要更完整医疗/补给条件的情况。",
                }
            )

        alternatives.append(
            {
                "plan_type": "alternative",
                "title": "方案C：分流同行人",
                "summary": "由一名同行者陪同处理，其他人就近等待或提前结束行程。",
                "reason": "应急处理中，先把行动职责拆开通常更稳。",
            }
        )
        return alternatives[:3]

    def _handle_search(self, user_input: str, state: CompanionState, tool_logs: list[dict[str, Any]]) -> AgentTurnResult:
        current_location = self._extract_current_location(user_input, state, tool_logs)
        if not current_location:
            return AgentTurnResult(
                reply="我还不知道你当前在哪里。先告诉我“我在王府井/故宫/颐和园”这类当前位置。",
                intent="search",
                warnings=["缺少当前位置。"],
                tool_logs=tool_logs,
            )

        query = f"{current_location['name']} 餐厅"
        candidates = self._run_tool_call(
            "retrieve_candidates",
            {"query": query, "city": state.city, "current_location": current_location},
            state,
            tool_logs,
        )
        ranking = self._run_tool_call(
            "score_candidates",
            {"candidates": candidates, "context": self._context_payload(state, current_location)},
            state,
            tool_logs,
        )
        primary = ranking.get("primary", [])
        if not primary:
            return AgentTurnResult(
                reply="我没有找到足够可靠的附近候选。建议换成“商场/咖啡店/具体商圈 + 餐厅”再试一次。",
                intent="search",
                warnings=["候选为空。"],
                tool_logs=tool_logs,
            )

        cards = primary + ranking.get("backup", [])
        first = primary[0]
        option_lines = []
        for idx, item in enumerate(cards[:5], start=1):
            reason = item.get("ranking_reason") or "综合得分较高"
            distance = item.get("distance_m")
            distance_text = f"，约 {round(distance)} 米" if isinstance(distance, (int, float)) and distance else ""
            option_lines.append(f"{idx}. `{item.get('name', '')}`：{reason}{distance_text}")
        reply = (
            f"**结论**\n优先看 `{first.get('name', '')}`。\n\n"
            "**候选**\n"
            + "\n".join(option_lines)
            + "\n\n**下一步**\n"
            "1. 你选定一家后，我继续帮你算从当前位置过去的步行/打车时间。\n"
            "2. 如果想换菜系、预算或环境，直接补充条件。"
        )
        return AgentTurnResult(reply=reply, intent="search", cards=cards, tool_logs=tool_logs)

    def _handle_coordinate(self, user_input: str, state: CompanionState, tool_logs: list[dict[str, Any]]) -> AgentTurnResult:
        current_location = self._extract_current_location(user_input, state, tool_logs)
        destinations = self._extract_destinations(user_input, city=state.city or "")
        if not current_location or not destinations:
            return AgentTurnResult(
                reply="我需要知道你现在的位置和接下来要去的点位，才能判断时间是否来得及。",
                intent="coordinate",
                warnings=["缺少起点或目的地。"],
                tool_logs=tool_logs,
            )

        stops = []
        previous = current_location
        cards = []
        state.remaining_plan = []
        for dest_name in destinations:
            destination = self._run_tool_call(
                "resolve_location",
                {"query": dest_name, "city_bias": state.city or self.settings.default_city},
                state,
                tool_logs,
            )
            route = self._run_tool_call(
                "get_route",
                {"origin": previous, "dest": destination, "mode": "driving"},
                state,
                tool_logs,
            )
            poi_detail = self._run_tool_call("get_poi_detail", {"name": destination["name"]}, state, tool_logs)
            close_by = None
            if poi_detail.get("open_hours") and "-" in poi_detail["open_hours"] and poi_detail["open_hours"] != "全天开放":
                close_part = poi_detail["open_hours"].split("-", 1)[1]
                close_by = f"{state.current_time[:10]}T{close_part}:00"

            stops.append(
                {
                    "name": destination["name"],
                    "travel_duration_min": route["duration_min"],
                    "stay_duration_min": self._adjust_stay_duration_for_party(
                        int(poi_detail.get("recommended_duration_min", 60) or 60),
                        state,
                        destination["name"],
                    ),
                    "close_by": close_by,
                }
            )
            state.remaining_plan.append({"name": destination["name"]})
            cards.append({"destination": destination, "route": route, "poi_detail": poi_detail})
            previous = destination

        feasibility = check_time_feasibility(state.current_time, stops)
        party_warnings = self._party_feasibility_warnings(state, stops, feasibility)
        all_warnings = list(feasibility["warnings"]) + party_warnings
        leg_parts = []
        for card in cards:
            stay_min = self._adjust_stay_duration_for_party(
                int(card["poi_detail"].get("recommended_duration_min", 60) or 60),
                state,
                card["destination"]["name"],
            )
            leg_parts.append(
                f"{card['destination']['name']} 路上约 {card['route']['duration_min']} 分钟，建议至少预留 {stay_min} 分钟"
            )
        conclusion = "这条路线目前不建议直接执行。" if all_warnings else "这条路线目前看整体可行。"
        reply = f"**结论**\n{conclusion}"
        if leg_parts:
            reply += "\n\n**时间线**\n" + "\n".join(f"- {part}" for part in leg_parts)
        if feasibility["latest_departure_time"]:
            reply += f"\n\n**最晚出发**\n- 建议在 {feasibility['latest_departure_time']} 前离开当前点位。"
        if all_warnings:
            reply += "\n\n**风险**\n" + "\n".join(f"- {item}" for item in all_warnings)
        alternatives = self._build_coordinate_alternatives(state, cards, all_warnings)
        if alternatives:
            reply += "\n\n**可选方案**\n"
            reply += "\n".join(f"{idx + 1}. {item['title']}：{item['summary']}" for idx, item in enumerate(alternatives[:2]))
        return AgentTurnResult(
            reply=reply,
            intent="coordinate",
            cards=cards + alternatives,
            tool_logs=tool_logs,
            warnings=all_warnings,
        )

    def _handle_replan(self, user_input: str, state: CompanionState, tool_logs: list[dict[str, Any]]) -> AgentTurnResult:
        current_location = self._extract_current_location(user_input, state, tool_logs)
        current_location = current_location or {
            "name": state.current_location or state.city,
            "city": state.city,
            "lat": state.current_coords[0] if state.current_coords else 0.0,
            "lon": state.current_coords[1] if state.current_coords else 0.0,
        }

        target_poi_name = self._extract_mentioned_poi(user_input, city=state.city or "")
        target_location = current_location
        if target_poi_name:
            try:
                target_location = self._run_tool_call(
                    "resolve_location",
                    {"query": target_poi_name, "city_bias": state.city or self.settings.default_city},
                    state,
                    tool_logs,
                )
            except Exception:
                target_location = current_location

        weather = self._run_tool_call("get_weather_now", {"city": state.city}, state, tool_logs)
        query = f"{target_location['name']} 博物馆"
        candidates = self._run_tool_call(
            "retrieve_candidates",
            {"query": query, "city": state.city, "current_location": target_location},
            state,
            tool_logs,
        )
        candidates = self._filter_replan_candidates(candidates, target_poi_name, state)
        ranking = self._run_tool_call(
            "score_candidates",
            {"candidates": candidates, "context": self._context_payload(state, target_location)},
            state,
            tool_logs,
        )
        primary = ranking.get("primary", [])
        user_reports_rain = any(token in user_input for token in ["下雨", "淋雨", "雨天"])
        if user_reports_rain:
            conclusion = "你现场反馈已经在下雨，我优先按雨天策略重排。"
            weather_line = f"实时天气接口当前显示 `{weather.get('summary', 'Unknown')}`，这里只作辅助参考。"
        else:
            conclusion = "我先按当天实时天气重排。"
            weather_line = f"当前天气是 `{weather.get('summary', 'Unknown')}`。"
        reply = f"**结论**\n{conclusion}\n\n**依据**\n- {weather_line}"
        if primary:
            reply += f"\n- 室内替代优先看 `{primary[0].get('name', '')}`。"
        else:
            reply += "\n- 已排除原目标和明显室外点位，但当前没有找到足够好的室内替代。"
        if weather.get("suggestions"):
            reply += f"\n- {weather['suggestions'][0]}"
        alternatives = self._build_replan_alternatives(state, target_poi_name, primary)
        if alternatives:
            reply += "\n\n**可执行替代**\n"
            reply += "\n".join(f"{idx + 1}. {item['title']}：{item['summary']}" for idx, item in enumerate(alternatives[:2]))
        reply += "\n\n**下一步**\n1. 先选一个室内替代或休整点。\n2. 如果你给我剩余时间，我可以继续压缩后面的站点。"
        return AgentTurnResult(
            reply=reply,
            intent="replan",
            cards=primary + alternatives,
            tool_logs=tool_logs,
        )

    def _handle_emergency(self, user_input: str, state: CompanionState, tool_logs: list[dict[str, Any]]) -> AgentTurnResult:
        current_location = self._extract_current_location(user_input, state, tool_logs)
        if not current_location:
            current_location = {
                "name": state.current_location or state.city,
                "city": state.city,
                "lat": state.current_coords[0] if state.current_coords else 0.0,
                "lon": state.current_coords[1] if state.current_coords else 0.0,
            }

        scene = classify_emergency_scene(user_input)
        base_location = None
        if state.base_location:
            try:
                base_location = self._run_tool_call(
                    "resolve_location",
                    {"query": state.base_location, "city_bias": state.city or self.settings.default_city},
                    state,
                    tool_logs,
                )
            except Exception:
                base_location = None

        resources = self._run_tool_call(
            "resolve_emergency_resources",
            {"scene": scene, "location": current_location, "base_location": base_location},
            state,
            tool_logs,
        )
        primary = resources.get("primary_actions", [])
        immediate_action = resources.get("immediate_action") or {}
        evacuation_plan = resources.get("evacuation_plan") or {}
        group_split_plan = resources.get("group_split_plan") or {}

        if immediate_action:
            conclusion = f"先别继续赶路。{immediate_action.get('summary', '')}"
        elif primary:
            first = primary[0]
            conclusion = f"先别继续赶路。优先处理 `{first.get('action_type', '')}`：`{first.get('name', '')}`。"
        else:
            conclusion = "地图候选不够稳定，优先找最近出口、游客中心或保安亭。"
        reply = f"**结论**\n{conclusion}"
        if resources.get("safety_notes"):
            reply += "\n\n**安全提醒**\n" + "\n".join(f"- {item}" for item in resources["safety_notes"][:3])
        warnings = resources.get("warnings", [])
        cards = primary + resources.get("backup_actions", [])
        alternatives = []
        if immediate_action:
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": immediate_action.get("title", "立即动作"),
                    "summary": immediate_action.get("summary", ""),
                    "reason": immediate_action.get("reason", ""),
                }
            )
        if evacuation_plan:
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": evacuation_plan.get("title", "回撤方案"),
                    "summary": evacuation_plan.get("summary", ""),
                    "reason": evacuation_plan.get("reason", ""),
                }
            )
        if group_split_plan:
            alternatives.append(
                {
                    "plan_type": "alternative",
                    "title": group_split_plan.get("title", "同行人分工"),
                    "summary": group_split_plan.get("summary", ""),
                    "reason": group_split_plan.get("reason", ""),
                }
            )
        if alternatives:
            reply += "\n\n**接下来建议**\n"
            reply += "\n".join(f"{idx + 1}. {item['title']}：{item['summary']}" for idx, item in enumerate(alternatives[:3]))
        return AgentTurnResult(
            reply=reply,
            intent="emergency",
            cards=cards + alternatives,
            tool_logs=tool_logs,
            warnings=warnings,
        )
