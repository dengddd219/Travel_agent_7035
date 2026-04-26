from __future__ import annotations

import json
import re
from typing import Any

from config import Settings
from constraint_extractor import get_known_pois, classify_intent, extract_constraints
from models import AgentTurnResult, CompanionState
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

    def run_turn(self, user_input: str, state: CompanionState | None = None) -> AgentTurnResult:
        state = state or CompanionState(city=self.settings.default_city)
        state.update_time()
        self._apply_structured_constraints(user_input, state)
        state.add_turn("user", user_input)
        self._apply_progress_updates(user_input, state)

        try:
            task_result = self._maybe_handle_task_flow(user_input, state)
            if task_result is not None:
                result = task_result
            elif self.client is not None:
                try:
                    result = self._run_llm_turn(user_input=user_input, state=state)
                except Exception as llm_exc:
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
                result = self._run_fallback_turn(user_input=user_input, state=state)
        except Exception as exc:
            result = AgentTurnResult(
                reply=f"这轮请求没有成功执行：{exc}",
                intent="error",
                warnings=["已返回保守错误信息。"],
                error={"code": "turn_failed", "message": str(exc), "retryable": True},
                state=state,
            )

        state.add_turn("assistant", result.reply)
        result.state = state
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

    def _maybe_handle_task_flow(self, user_input: str, state: CompanionState) -> AgentTurnResult | None:
        if state.clarification_pending:
            return self._resume_pending_task(user_input, state)

        intent = self._classify_intent(user_input)
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
        result = replan_itinerary(
            remaining_plan=state.remaining_plan,
            current_location=state.current_location,
            time_budget_hours=time_budget,
            completed_nodes=state.completed_nodes,
            skipped_nodes=state.skipped_nodes,
            constraints=task.get("constraints") or self._replan_constraints(state, time_budget),
        )
        tool_logs.append(
            {
                "tool": "replan_itinerary",
                "arguments": {
                    "time_budget_hours": time_budget,
                    "completed_nodes": state.completed_nodes,
                    "skipped_nodes": state.skipped_nodes,
                },
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
        reply = result.get("summary") or "已完成当天剩余行程重排。"
        if plan_names:
            reply += " 新顺序：" + " -> ".join(plan_names) + "。"
        if result.get("warnings"):
            reply += " 风险提示：" + "；".join(result["warnings"])
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

    def _run_llm_turn(self, user_input: str, state: CompanionState) -> AgentTurnResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": TOOL_POLICY_PROMPT},
        ]
        messages.extend(state.turn_history[-10:])

        tool_logs: list[dict[str, Any]] = []
        llm_call_count = 0
        total_input_tokens = 0
        total_output_tokens = 0
        require_tool_first = self._should_require_tool_first(user_input, state)

        while True:
            response = self.client.chat.completions.create(
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
            if not tool_calls:
                reply = (message.content or "").strip() or "暂时没有得到可执行结论。"
                intent = self._classify_intent(user_input)
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

    def _run_fallback_turn(self, user_input: str, state: CompanionState) -> AgentTurnResult:
        intent = self._classify_intent(user_input)
        tool_logs: list[dict[str, Any]] = []

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
        output = self.tool_impls[tool_name](arguments, state)
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
        if any(token in lowered for token in ["replan", "reschedule", "reroute", "only have", "hours left"]):
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
        reply = (
            f"优先推荐你先看 `{first.get('name', '')}`。"
            f"它{first.get('ranking_reason', '综合得分较高')}。"
            f"我也保留了 {min(len(cards), 5)} 个候选供你比较。"
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
        reply = "路线已经帮你串起来了。"
        if leg_parts:
            reply += " 当前粗略时间线：" + "，".join(leg_parts) + "。"
        if feasibility["latest_departure_time"]:
            reply += f" 如果你要赶第一站，最晚建议在 {feasibility['latest_departure_time']} 前离开当前点位。"
        if all_warnings:
            reply += " 但这组安排我不建议直接执行。风险提示：" + "；".join(all_warnings)
        else:
            reply += " 目前看整体可行。"
        alternatives = self._build_coordinate_alternatives(state, cards, all_warnings)
        if alternatives:
            reply += " 你可以这样改："
            reply += "；".join(f"{item['title']}：{item['summary']}" for item in alternatives[:2])
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
            reply = "你现场反馈已经在下雨，我优先按雨天策略重排。"
            reply += f" 实时天气接口当前显示 `{weather.get('summary', 'Unknown')}`，这里只作辅助参考。"
        else:
            reply = f"我先按当天实时天气重排。当前天气是 `{weather.get('summary', 'Unknown')}`。"
        if primary:
            reply += f" 室内替代我优先建议 `{primary[0].get('name', '')}`。"
        else:
            reply += " 我先排除了原目标和明显室外点位，但当前没有找到足够好的室内替代，建议改查附近商场或大型博物馆。"
        if weather.get("suggestions"):
            reply += " " + weather["suggestions"][0]
        alternatives = self._build_replan_alternatives(state, target_poi_name, primary)
        if alternatives:
            reply += " 可执行替代："
            reply += "；".join(f"{item['title']}：{item['summary']}" for item in alternatives[:2])
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
            reply = f"先别继续赶路。{immediate_action.get('summary', '')}"
        elif primary:
            first = primary[0]
            reply = f"先别继续赶路。优先处理 `{first.get('action_type', '')}`：`{first.get('name', '')}`。"
        else:
            reply = "地图候选不够稳定，优先找最近出口、游客中心或保安亭。"
        if resources.get("safety_notes"):
            reply += " " + resources["safety_notes"][0]
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
            reply += " 接下来建议："
            reply += "；".join(f"{item['title']}：{item['summary']}" for item in alternatives[:3])
        return AgentTurnResult(
            reply=reply,
            intent="emergency",
            cards=cards + alternatives,
            tool_logs=tool_logs,
            warnings=warnings,
        )
