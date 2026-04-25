from __future__ import annotations

import json
import re
from typing import Any

from config import Settings
from models import AgentTurnResult, CompanionState
from tools import (
    check_time_feasibility,
    classify_emergency_scene,
    get_route,
    get_weather_now,
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

KNOWN_BEIJING_POIS = [
    "天安门广场",
    "天安门",
    "颐和园",
    "故宫博物院",
    "故宫",
    "国家博物馆",
    "中国美术馆",
    "王府井",
    "天坛",
]

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
            "description": "Get static detail for a scenic spot from local mock data.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
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
        }
        self.client = None
        if self.settings.has_llm_credentials and OpenAI is not None:
            if self.settings.is_azure_openai and AzureOpenAI is not None:
                client_kwargs = {
                    "api_key": self.settings.openai_api_key,
                    "api_version": self.settings.openai_api_version,
                }
                if self.settings.azure_endpoint:
                    client_kwargs["azure_endpoint"] = self.settings.azure_endpoint
                self.client = AzureOpenAI(**client_kwargs)
            else:
                client_kwargs = {"api_key": self.settings.openai_api_key}
                if self.settings.openai_base_url:
                    client_kwargs["base_url"] = self.settings.openai_base_url
                self.client = OpenAI(**client_kwargs)

    def run_turn(self, user_input: str, state: CompanionState | None = None) -> AgentTurnResult:
        state = state or CompanionState(city=self.settings.default_city)
        state.update_time()
        state.add_turn("user", user_input)

        try:
            if self.client is not None:
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

    def _run_llm_turn(self, user_input: str, state: CompanionState) -> AgentTurnResult:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(state.turn_history[-10:])

        tool_logs: list[dict[str, Any]] = []
        llm_call_count = 0
        total_input_tokens = 0
        total_output_tokens = 0

        while True:
            response = self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
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

    def _tool_get_route(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        return get_route(
            origin=arguments["origin"],
            dest=arguments["dest"],
            mode=arguments.get("mode", "walking"),
            settings=self.settings,
        )

    def _tool_get_poi_detail(self, arguments: dict[str, Any], state: CompanionState) -> Any:
        return get_poi_detail(arguments["name"])

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
        if any(token in lowered for token in ["下雨", "关闭", "换吗", "能换", "排队", "不想去了"]):
            return "replan"
        if any(token in lowered for token in ["来得及", "时间够吗", "赶得上", "最晚几点"]):
            return "coordinate"
        if any(token in lowered for token in ["腿疼", "走不动", "受伤", "尿急", "网吧", "迷路", "求助", "回酒店"]):
            return "emergency"
        return "search"

    def _extract_current_location(self, text: str, state: CompanionState, tool_logs: list[dict[str, Any]]) -> dict[str, Any] | None:
        match = re.search(r"(?:我在|我们在|在)(.+?)(?:，|,|。|想|要|还|逛|吃|走不动|腿疼|下雨|$)", text)
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

    def _extract_destinations(self, text: str) -> list[str]:
        ordered_matches: list[tuple[int, str]] = []
        for poi_name in KNOWN_BEIJING_POIS:
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

    def _extract_mentioned_poi(self, text: str) -> str | None:
        ordered_matches: list[tuple[int, str]] = []
        for poi_name in KNOWN_BEIJING_POIS:
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
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        target_name = (target_poi_name or "").strip()
        for candidate in candidates:
            name = str(candidate.get("name", "")).strip()
            type_text = str(candidate.get("type_text", "")).strip()
            haystack = f"{name} {type_text}"

            if target_name and (name == target_name or target_name in name):
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

    def _handle_search(self, user_input: str, state: CompanionState, tool_logs: list[dict[str, Any]]) -> AgentTurnResult:
        self._extract_constraints(user_input, state)
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
        destinations = self._extract_destinations(user_input)
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
        return AgentTurnResult(reply=reply, intent="coordinate", cards=cards, tool_logs=tool_logs, warnings=all_warnings)

    def _handle_replan(self, user_input: str, state: CompanionState, tool_logs: list[dict[str, Any]]) -> AgentTurnResult:
        current_location = self._extract_current_location(user_input, state, tool_logs)
        current_location = current_location or {
            "name": state.current_location or state.city,
            "city": state.city,
            "lat": state.current_coords[0] if state.current_coords else 0.0,
            "lon": state.current_coords[1] if state.current_coords else 0.0,
        }

        target_poi_name = self._extract_mentioned_poi(user_input)
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
        candidates = self._filter_replan_candidates(candidates, target_poi_name)
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
        return AgentTurnResult(reply=reply, intent="replan", cards=primary, tool_logs=tool_logs)

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
        if primary:
            first = primary[0]
            reply = f"先别继续赶路。优先处理 `{first.get('action_type', '')}`：`{first.get('name', '')}`。"
        else:
            reply = "地图候选不够稳定，优先找最近出口、游客中心或保安亭。"
        if resources.get("safety_notes"):
            reply += " " + resources["safety_notes"][0]
        warnings = resources.get("warnings", [])
        cards = primary + resources.get("backup_actions", [])
        return AgentTurnResult(reply=reply, intent="emergency", cards=cards, tool_logs=tool_logs, warnings=warnings)
