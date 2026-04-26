## author:SUN Bin
from __future__ import annotations

from copy import deepcopy
import json
import re
import time
from dataclasses import dataclass, field

from .city_names import CITY_ALIASES, normalize_city_name, provider_city_name
from .config import Settings
from .llm import create_response_client
from .planner import plan_itinerary, render_markdown_report
from .tools.city_context import get_city_context
from .tools.cost_adapter import get_group_c_cost_summary
from .tools.hotel_adapter import get_hotel_candidates
from .tools.strategy_rag_adapter import get_strategy_context
from .tools.weather_adapter import get_group_c_weather_forecast
from .tools.poi import search_batch_pois
from .tools.tips import get_travel_tips
from .debug_tracer import (
    trace_session_start,
    trace_profile,
    trace_decomposition,
    trace_rag_input,
    trace_rag_output,
    trace_tool_call,
    trace_planner_input,
    trace_plan_output,
    trace_step_timer,
)

"""Main orchestration agent for our travel planner.

This module sits between user input and the deterministic planner. Its job is to:
- understand what the user wants
- keep multi-turn preference memory
- split complex requests into smaller sub-queries
- gather evidence from strategy / geo / conditions tools
- call the planner only after the context is rich enough
"""


SYSTEM_PROMPT = """
You are an expert travel-planning agent inspired by itinerary-builder apps.

Your job is not to free-write a generic travel plan. You must orchestrate tools to:
1. understand the city, trip duration, travel style, budget, and constraints
2. search and normalize relevant POIs
3. inspect weather
4. collect local travel tips
5. call the deterministic planner to build a structured itinerary
6. call the report generator to produce the final markdown report

Rules:
- Start with strategy retrieval for destination knowledge unless it is already available.
- Treat retrieved guide knowledge as planning evidence, not as decoration.
- When strategy retrieval suggests specific POIs or neighborhoods, prefer them unless they conflict with hard constraints, weather, or budget.
- Use POI search to normalize and verify guide recommendations instead of replacing them with arbitrary map results.
- If the user request is sparse, use city profile suggestions plus retrieved travel-guide signals to build a plausible first itinerary.
- Prefer geographically coherent day plans.
- Avoid jumping across distant districts on the same day unless the user explicitly requests it.
- Use indoor or mixed venues on poor-weather days.
- Respect must-visit and avoid lists.
- Keep the final answer concise but useful, and include the generated report.
- Do not stop for clarifying questions unless the request is impossible to fulfill.
- If dates are missing, assume the next available trip window and still produce a plan.
- If mobility constraints are missing, assume average adult walking tolerance.
- If a skyline preference is missing, choose the option that best fits the must-visit list and routing logic.
- If some tools return partial data, continue with the best available information instead of asking the user to fill the gap.
- Do not invent a route that ignores retrieved guide clusters when those clusters are available.
"""


@dataclass(slots=True)
class AgentRunResult:
    """Output for one-shot execution APIs.

    Fields:
    - answer: Final markdown text shown to user.
    - tool_logs: Compact audit trail of tool invocations and previews.
    - raw_response: Reserved for raw model output when needed.
    - plan: Structured itinerary JSON (if generation succeeded).
    """

    answer: str
    tool_logs: list[dict]
    raw_response: str = ""
    plan: dict | None = None


@dataclass(slots=True)
class AgentOrchestrationResult:
    """Expanded payload used when downstream groups need handoff-ready artifacts."""

    user_profile: dict
    decomposition: dict
    upstream_requests: dict
    collected_context: dict
    itinerary_json: dict
    hotel_recommendations: dict
    report: str
    tool_logs: list[dict]


@dataclass(slots=True)
class ConversationState:
    """Persistent state across turns in a chat-style planning session."""

    preference_memory: dict
    latest_user_profile: dict
    latest_plan: dict | None = None
    latest_hotel_recommendations: dict | None = None
    latest_report: str = ""
    confirmed_profile_slots: list[str] = field(default_factory=list)
    pending_profile_slots: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    turn_history: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class ConversationRunResult:
    """Return container for multi-turn APIs (`start_conversation` / `continue_conversation`)."""

    state: ConversationState
    answer: str
    tool_logs: list[dict]
    plan: dict | None = None
    needs_clarification: bool = False
    missing_profile_slots: list[str] = field(default_factory=list)


class TravelPlanningAgent:
    """Main orchestration agent.

    This class has three responsibilities:
    1) Parse/normalize user intent into a stable profile and sub-queries.
    2) Coordinate tool calls (LLM-driven first, deterministic fallback second).
    3) Produce final itinerary/report and optional orchestration handoff payload.
    """

    TRAVEL_TYPE_ALIASES = {
        "family": ["family", "亲子", "带娃", "kids", "children"],
        "food": ["food", "dining", "美食", "吃", "火锅", "小吃"],
        "theme": ["theme", "niche", "小众", "主题", "设计"],
        "leisure": ["leisure", "relax", "休闲", "轻松"],
    }
    BUDGET_ALIASES = {
        "low": ["low budget", "budget low", "低预算", "省钱", "economy"],
        "medium": ["medium budget", "budget medium", "中等预算", "适中预算", "中等", "中档"],
        "high": ["high budget", "budget high", "高预算", "luxury", "豪华", "不限预算", "预算不是问题"],
    }
    PACE_ALIASES = {
        "slow": ["slow", "more relaxed", "take it easy", "轻松", "慢节奏", "不要太赶", "松一点", "慢一点", "悠闲"],
        "balanced": ["balanced", "适中", "均衡"],
        "packed": ["packed", "fit more", "more packed", "紧凑", "特种兵", "排满", "多塞一点", "尽量多玩"],
    }
    INTEREST_ALIASES = {
        "local food": ["food", "dining", "美食", "吃"],
        "viewpoints": ["view", "skyline", "观景", "夜景", "harbour"],
        "culture": ["culture", "museum", "文化", "博物馆", "历史"],
        "family friendly": ["family", "亲子", "kids", "children", "带娃"],
        "museums": ["museum", "gallery", "博物馆", "美术馆"],
        "shopping": ["shopping", "mall", "逛街", "购物", "商场"],
        "hidden gems": ["hidden gem", "小众", "冷门"],
        "night views": ["night", "night view", "夜景"],
    }
    POI_NAME_ALIASES = {
        "太古": "太古里",
        "成都太古": "成都太古里",
        "春熙": "春熙路",
    }
    INTEREST_QUERY_ALIASES = {
        "landmarks": "landmark",
        "viewpoints": "viewpoint",
        "local food": "food market",
        "museums": "museum",
        "shopping": "shopping district",
        "culture": "cultural district",
        "family friendly": "family attraction",
        "night views": "night view",
        "hidden gems": "hidden gem",
    }
    GEO_QUERY_ALIASES = {
        "local food": "美食街",
        "viewpoints": "观景台",
        "culture": "博物馆",
        "family friendly": "亲子景区",
        "museums": "博物馆",
        "shopping": "购物中心",
        "night views": "夜景",
        "hidden gems": "小众景点",
    }
    PROFILE_SLOT_ORDER = ("city", "trip_days", "travel_style", "budget_level", "pace", "constraints")
    PROFILE_FLEXIBLE_REPLIES = (
        "都可以",
        "都行",
        "随便",
        "你定",
        "你决定",
        "你来定",
        "无所谓",
        "没要求",
        "whatever",
        "either is fine",
        "up to you",
    )
    PROFILE_NEGATIVE_REPLIES = (
        "没有",
        "没了",
        "none",
        "no",
        "不用",
        "不需要",
        "没有特别的",
        "没有要求",
        "没有必须去的",
        "没有想避开的",
    )
    TRAVEL_TYPE_LABELS = {
        "leisure": "轻松逛逛",
        "family": "亲子友好",
        "food": "美食优先",
        "theme": "主题体验",
    }
    BUDGET_LEVEL_LABELS = {
        "low": "低预算",
        "medium": "中等预算",
        "high": "高预算",
    }
    PACE_LABELS = {
        "slow": "轻松节奏",
        "balanced": "适中节奏",
        "packed": "紧凑节奏",
    }
    INTEREST_LABELS = {
        "local food": "本地美食",
        "viewpoints": "观景夜景",
        "culture": "文化体验",
        "family friendly": "亲子友好",
        "museums": "博物馆",
        "shopping": "购物逛街",
        "hidden gems": "小众路线",
        "night views": "夜景",
    }
    CHINESE_DAY_NUMBERS = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "十一": 11,
        "十二": 12,
        "十三": 13,
        "十四": 14,
    }

    def __init__(self, settings: Settings | None = None) -> None:
        # Load settings once for reuse across runs.
        # The runtime is mostly deterministic today, so we only initialize the
        # LLM client when a code path actually needs it.
        self.settings = settings or Settings.from_env()
        self.client = None
        self.model = self.settings.foundry_deployment
        # Tool implementations exposed to the model. Names must match schemas in build_tools().
        # This indirection lets the LLM see a clean tool contract while we keep
        # the real Python callables configurable on our side.
        self.tool_impls = {
            "get_city_context": get_city_context,
            "get_strategy_context": self._get_strategy_context,
            "search_batch_pois": self._search_batch_pois,
            "get_weather_forecast": self._get_weather_forecast,
            "get_cost_summary": self._get_cost_summary,
            "get_travel_tips": self._get_travel_tips,
        }

    def _ensure_response_client(self):
        if self.client is None:
            bundle = create_response_client(self.settings)
            self.client = bundle.client
            self.model = bundle.model
        return self.client

    def _search_batch_pois(self, city: str, queries: list[str], limit_per_query: int = 3) -> dict:
        # Adapter wrapper so all tools share agent-level settings.
        return search_batch_pois(city=city, queries=queries, limit_per_query=limit_per_query, settings=self.settings)

    def _get_travel_tips(
        self, city: str, poi_names: list[str], travel_type: str = "leisure", interests: list[str] | None = None
    ) -> dict:
        # Normalize optional list input; downstream adapter expects a concrete list.
        return get_travel_tips(
            city=city,
            poi_names=poi_names,
            travel_type=travel_type,
            interests=interests or [],
            settings=self.settings,
        )

    @staticmethod
    def _get_strategy_context(city: str, queries: list[str], travel_type: str = "leisure", top_k: int = 5) -> dict:
        return get_strategy_context(
            city=city,
            queries=queries,
            travel_type=travel_type,
            top_k=top_k,
        )

    def _get_weather_forecast(self, city: str, trip_days: int = 3, start_date: str = "") -> dict:
        # Group C weather provider wrapper.
        return get_group_c_weather_forecast(
            city=city,
            trip_days=trip_days,
            start_date=start_date,
            settings=self.settings,
        )

    @staticmethod
    def _get_cost_summary(
        city: str,
        days: int,
        budget_level: str,
        user_budget: float | None = None,
    ) -> dict:
        # Static because this computation does not depend on instance state.
        return get_group_c_cost_summary(
            city=city,
            days=days,
            budget_level=budget_level,
            user_budget=user_budget,
        )

    @staticmethod
    def _extract_function_calls(response) -> list:
        # Responses API may contain multiple output item types; keep only tool calls.
        return [item for item in response.output if getattr(item, "type", None) == "function_call"]

    @staticmethod
    def _preview_tool_result(result: object, limit: int = 500) -> str:
        try:
            preview = json.dumps(result, ensure_ascii=False)
        except Exception:
            preview = str(result)
        return preview[:limit]

    @classmethod
    def _append_tool_log(
        cls,
        tool_results: dict[str, object],
        *,
        tool_name: str,
        arguments: dict,
        result: object,
    ) -> None:
        tool_results.setdefault("_logs", []).append(
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "result_preview": cls._preview_tool_result(result),
            }
        )

    @staticmethod
    def build_tools() -> list[dict]:
        # JSON schemas define the contract the model must follow when invoking tools.
        # Keeping these schemas explicit helps the orchestration stay stable even
        # when the user's request is vague or highly conversational.
        return [
            {
                "type": "function",
                "name": "get_strategy_context",
                "description": "Retrieve strategy-level travel knowledge from the local RAG corpus, including recommended POIs and pitfalls.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "queries": {"type": "array", "items": {"type": "string"}},
                        "travel_type": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 8},
                    },
                    "required": ["city", "queries", "travel_type"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_city_context",
                "description": "Load curated city context, transport hints, and suggested search themes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "travel_type": {"type": "string"},
                    },
                    "required": ["city", "travel_type"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "search_batch_pois",
                "description": "Search and normalize real POIs for a city based on named attractions, food spots, or neighborhoods.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "queries": {"type": "array", "items": {"type": "string"}},
                        "limit_per_query": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    },
                    "required": ["city", "queries"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_weather_forecast",
                "description": "Fetch date-aligned weather forecast for the trip window using the conditions provider.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "trip_days": {"type": "integer", "minimum": 1, "maximum": 14},
                        "start_date": {"type": "string"},
                    },
                    "required": ["city", "trip_days"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_cost_summary",
                "description": "Estimate city-level hotel, food, and local transport budget for the trip window.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "days": {"type": "integer", "minimum": 1, "maximum": 30},
                        "budget_level": {"type": "string"},
                        "user_budget": {"type": ["number", "null"]},
                    },
                    "required": ["city", "days", "budget_level"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "get_travel_tips",
                "description": "Collect local travel tips and pitfalls for the selected POIs and travel style.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "poi_names": {"type": "array", "items": {"type": "string"}},
                        "travel_type": {"type": "string"},
                        "interests": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["city", "poi_names", "travel_type"],
                    "additionalProperties": False,
                },
            },
        ]

    @staticmethod
    def _extract_clause(text: str, label: str) -> str:
        # Extract patterns like "Must visit: ..." or "Interests: ..." from free-form text.
        match = re.search(rf"{label}\s*:\s*(.+?)(?:\.|$)", text, flags=re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    @classmethod
    def _split_csv(cls, raw: str) -> list[str]:
        # Split by both English and Chinese separators, then trim empties.
        if not raw:
            return []
        return [part.strip() for part in re.split(r"[,;，；、\n]|(?:\s+(?:and|or)\s+)|(?:\s*[和及与]\s*)", raw) if part.strip()]

    # Tokens that look like instruction verbs or time expressions — not real POI names.
    _NOISE_POI_PATTERNS: list[str] = [
        r"^规划.*路线$",
        r"^(?:给我|帮我|请|帮|给)[\s\S]{0,6}(?:规划|安排|制定|设计|生成|出|写)[\s\S]{0,6}(?:路线|行程|计划|攻略)$",
        r"^[\s\S]{0,4}(?:出行|出发|旅行|假期|节假日|五一|十一|春节|元旦|清明|端午|中秋|暑假|寒假)[\s\S]{0,6}$",
        r"^\d+\s*天$",
        r"^[一二两三四五六七八九十]+\s*天$",
        r"^(?:路线|行程|计划|攻略|安排)$",
    ]
    _POI_REMOVE_PREFIX_CUES: tuple[str, ...] = (
        "不去",
        "不想去",
        "先不去",
        "不打算去",
        "不考虑去",
        "取消去",
        "别去",
        "不要去",
        "不用去",
        "不安排",
        "先不安排",
        "别安排",
        "不要安排",
        "去掉",
        "删掉",
        "移除",
        "拿掉",
        "撤掉",
        "取消",
        "remove",
        "drop",
        "delete",
        "skip",
        "cancel",
    )
    _POI_REMOVE_SUFFIX_CUES: tuple[str, ...] = (
        "不去了",
        "先不去了",
        "不想去了",
        "不要了",
        "先不要了",
        "不用去了",
        "别安排了",
        "不安排了",
        "先不安排了",
        "不考虑了",
        "先不考虑了",
        "取消了",
        "取消",
        "去掉",
        "去掉了",
        "删掉",
        "删掉了",
        "移除",
        "拿掉",
        "撤掉",
        "remove",
        "drop",
        "deleted",
        "skip",
        "cancel",
    )

    @classmethod
    def _is_noise_poi(cls, value: str) -> bool:
        for pattern in cls._NOISE_POI_PATTERNS:
            if re.search(pattern, value.strip(), flags=re.IGNORECASE):
                return True
        return False

    @classmethod
    def _normalize_poi_name(cls, value: str) -> str:
        # Users often mention POIs in a conversational way:
        # "我想去太古", "然后去春熙", "成都玩三天必须去..."
        # This helper strips those wrappers and keeps only the part we should
        # use for POI search and must-visit matching.
        normalized = value.strip()
        if not normalized:
            return ""
        normalized = normalized.strip("，,；;、。.!？?：: ")
        cleanup_patterns = [
            r"^(?:我想去|想去|一定要去|必须去|安排去|要去|去|打卡|逛)\s*",
            r"^(?:必须去|一定要去|安排去|要去)\s*",
            r"^(?:再去|然后去|顺路去|以及去)\s*",
            r"^(?:香港|东京|成都|上海|北京|广州|深圳|杭州|西安|重庆|厦门|南京)\s*(?:玩|逛|待)?\s*(?:\d+\s*天|[一二两三四五六七八九十]+\s*天)?\s*",
            r"^(?:玩|逛)\s*(?:\d+\s*天|[一二两三四五六七八九十]+\s*天)\s*",
        ]
        previous = None
        while normalized and normalized != previous:
            previous = normalized
            for pattern in cleanup_patterns:
                normalized = re.sub(pattern, "", normalized).strip("，,；;、。.!？?：: ")
        normalized = re.sub(r"(?:了|啦|呀|啊|呢|吧)$", "", normalized).strip("，,；;、。.!？?：: ")
        if cls._is_noise_poi(normalized):
            return ""
        return cls.POI_NAME_ALIASES.get(normalized, normalized)

    @classmethod
    def _match_alias_group(cls, text: str, mapping: dict[str, list[str]], default: str) -> str:
        # Return the first matching canonical category; fallback to default.
        for canonical, aliases in mapping.items():
            if any(alias in text for alias in aliases):
                return canonical
        return default

    @classmethod
    def _find_alias_group(cls, text: str, mapping: dict[str, list[str]]) -> str | None:
        # Same as _match_alias_group but without default coercion.
        for canonical, aliases in mapping.items():
            if any(alias in text for alias in aliases):
                return canonical
        return None

    # Patterns that signal "origin city" (departure), not destination.
    # We strip these segments before city scanning so "从深圳出发去厦门" picks Xiamen.
    _ORIGIN_PATTERNS: list[str] = [
        r"从\s*(.+?)\s*(?:出发|飞|乘|搭|坐|开车|驾车|自驾)",
        r"(?:starting|departing|flying)\s+from\s+([A-Za-z\s]+?)(?:\s+to|\s*,|\s*$)",
    ]

    @classmethod
    def _strip_origin_city(cls, user_request: str) -> str:
        # Remove "从X出发" style segments so origin city doesn't compete with destination.
        stripped = user_request
        for pattern in cls._ORIGIN_PATTERNS:
            for match in re.finditer(pattern, stripped, flags=re.IGNORECASE):
                stripped = stripped.replace(match.group(0), " ")
        return stripped

    @classmethod
    def _strip_negated_cities(cls, text: str) -> str:
        # Remove cities mentioned in negation phrases like "不想去成都", "不去上海", "改成去X" implies X stays.
        # Pattern: negation marker + city → erase just that city token so the positive city wins.
        negation_patterns = [
            r"(?:不想去|不去|不想到|别去|不要去|取消去|放弃去)\s*([^\s，,。!？]+)",
            r"(?:don't want to go to|not going to|cancel)\s+([A-Za-z\s]+?)(?:\s*[,，。]|$)",
        ]
        result = text
        for pattern in negation_patterns:
            for match in re.finditer(pattern, result, flags=re.IGNORECASE):
                negated_token = match.group(1).strip()
                # Only erase it if it's a known city alias, to avoid removing real words.
                if normalize_city_name(negated_token) != negated_token:
                    result = result.replace(match.group(0), " ")
        return result

    @classmethod
    def _extract_explicit_city(cls, user_request: str) -> str | None:
        # 1. Strip "从X出发" so origin city doesn't win over destination.
        dest_text = cls._strip_origin_city(user_request)
        # 2. Strip negated cities ("不想去成都") so they don't match before the intended city.
        dest_text = cls._strip_negated_cities(dest_text)

        # 3. Try regex-based extraction from phrases like "改成去北京", "trip in Tokyo".
        city_match = re.search(
            r"(?:改成去|换成去|trip in|in|to|去|到)\s+([A-Z][A-Za-z\s\-]+?)(?:\.|,| for | with | budget| pace| must visit)",
            dest_text,
        )
        if city_match:
            explicit = normalize_city_name(city_match.group(1).strip())
            if explicit:
                return explicit

        # Also try Chinese destination phrase: "改成去北京" / "换到上海"
        cn_match = re.search(
            r"(?:改成去|换成去|改去|换去|换到|改到)\s*([一-鿿]{2,4})",
            dest_text,
        )
        if cn_match:
            explicit = normalize_city_name(cn_match.group(1).strip())
            if explicit and explicit != cn_match.group(1).strip():
                return explicit

        # 4. Fall back to unified city normalization — scan all aliases, longest match first
        #    to avoid short alias shadowing a longer one that appears later in the text.
        lower = dest_text.lower()
        best_city: str | None = None
        best_pos = len(dest_text)
        for alias, canonical in CITY_ALIASES.items():
            idx = lower.find(alias)
            if idx == -1:
                idx = dest_text.find(alias)
            if idx == -1:
                continue
            # Prefer the city whose alias appears **last** in the string:
            # "不想去[成都]了，改成去[北京]" → 北京 appears later, wins.
            if idx > best_pos or best_city is None:
                best_city = canonical
                best_pos = idx
        return best_city

    @classmethod
    def _extract_city(cls, user_request: str, default_city: str) -> str:
        # Never return empty city; always enforce a deterministic fallback.
        return cls._extract_explicit_city(user_request) or normalize_city_name(default_city) or default_city

    # Chinese public holidays: name → (month, day, default_duration)
    _CN_HOLIDAYS: dict[str, tuple[int, int, int]] = {
        "五一": (5, 1, 5),
        "劳动节": (5, 1, 5),
        "十一": (10, 1, 7),
        "国庆": (10, 1, 7),
        "国庆节": (10, 1, 7),
        "春节": (2, 1, 7),
        "元旦": (1, 1, 3),
        "清明": (4, 4, 3),
        "清明节": (4, 4, 3),
        "端午": (5, 31, 3),  # approximate; varies by year
        "端午节": (5, 31, 3),
        "中秋": (9, 15, 3),
        "中秋节": (9, 15, 3),
    }

    @classmethod
    def _parse_holiday_date(cls, user_request: str) -> tuple[str, int] | None:
        """Return (iso_date_string, default_days) for a recognised holiday, or None."""
        import datetime as _dt
        current_year = _dt.date.today().year
        for name, (month, day, duration) in cls._CN_HOLIDAYS.items():
            if name in user_request:
                # Snap to the upcoming occurrence of this holiday.
                candidate = _dt.date(current_year, month, day)
                if candidate < _dt.date.today():
                    candidate = _dt.date(current_year + 1, month, day)
                return candidate.isoformat(), duration
        return None

    @classmethod
    def _parse_trip_days(cls, user_request: str) -> int | None:
        lower = user_request.lower()
        trip_days_match = re.search(r"(\d+)\s*-\s*day|(\d+)\s+day|(\d+)\s*天", lower)
        if trip_days_match:
            return int(next(group for group in trip_days_match.groups() if group))

        chinese_days_match = re.search(r"([一二两三四五六七八九十]{1,3})\s*天", user_request)
        if chinese_days_match:
            days = cls.CHINESE_DAY_NUMBERS.get(chinese_days_match.group(1))
            if days is not None:
                return days

        if "weekend" in lower or "周末" in user_request:
            return 2

        # Infer days from holiday duration when user doesn't state days explicitly.
        holiday = cls._parse_holiday_date(user_request)
        if holiday:
            return holiday[1]

        return None

    @classmethod
    def _extract_user_profile(cls, user_request: str, default_city: str = "Hong Kong") -> dict:
        # Build a normalized profile from noisy natural language input.
        # This function is intentionally permissive because user input is often:
        # - incomplete
        # - partly Chinese, partly English
        # - not written in explicit "field: value" form
        lower = user_request.lower()
        city = cls._extract_city(user_request, default_city)

        trip_days = cls._parse_trip_days(user_request) or 3

        # Resolve start_date from explicit holiday mention when no days stated directly.
        holiday_info = cls._parse_holiday_date(user_request)
        start_date = holiday_info[0] if holiday_info else ""

        travel_type = cls._match_alias_group(lower + user_request, cls.TRAVEL_TYPE_ALIASES, "leisure")

        budget_level = cls._match_alias_group(lower + user_request, cls.BUDGET_ALIASES, "medium")

        pace = cls._match_alias_group(lower + user_request, cls.PACE_ALIASES, "balanced")

        travelers = cls._extract_clause(user_request, "Travelers") or "friends"
        must_visit_clause = cls._extract_clause(user_request, "Must visit")
        avoid_clause = cls._extract_clause(user_request, "Avoid")
        interests_clause = cls._extract_clause(user_request, "Interests")
        notes_clause = cls._extract_clause(user_request, "Use these travel notes as source material")
        extra_clause = cls._extract_clause(user_request, "Extra request")

        profile = {
            "city": city,
            "start_date": start_date,
            "trip_days": trip_days,
            "travel_type": travel_type,
            "travelers": travelers,
            "budget_level": budget_level,
            "pace": pace,
            "interests": cls._split_csv(interests_clause),
            "must_visit": [
                item for item in
                (cls._normalize_poi_name(raw) for raw in cls._split_csv(must_visit_clause))
                if item
            ],
            "avoid": cls._split_csv(avoid_clause),
            "notes": notes_clause,
            "extra_request": extra_clause,
        }

        # Backfill obvious must-visit items if user mentions places inline instead
        # of using an explicit "Must visit:" clause.
        if not profile["must_visit"]:
            implicit_items: list[str] = []
            for pattern in [
                r"(?:想去|一定要去|必须去|安排去|想逛|要去)\s*[:：]?\s*(.+?)(?:[。.!?]|$)",
            ]:
                for match in re.finditer(pattern, user_request, flags=re.IGNORECASE):
                    implicit_items.extend(cls._split_csv(match.group(1)))
            profile["must_visit"] = cls._dedupe_items(
                [n for n in (cls._normalize_poi_name(item) for item in implicit_items) if n]
            )
        if not profile["must_visit"]:
            known_places = [
                "Peak Tram",
                "Central Market",
                "Tsim Sha Tsui Promenade",
                "Star Ferry",
                "Temple Street Night Market",
            ]
            profile["must_visit"] = [place for place in known_places if place.lower() in lower]
        # Infer interests from aliases when explicit "Interests:" clause is absent.
        if not profile["interests"]:
            inferred = []
            combined_text = lower + user_request
            for interest, aliases in cls.INTEREST_ALIASES.items():
                if any(alias in combined_text for alias in aliases):
                    inferred.append(interest)
            profile["interests"] = inferred
        return profile

    @staticmethod
    def _dedupe_queries(queries: list[str], limit: int = 12) -> list[str]:
        # Preserve order while deduplicating; cap list to control tool fan-out.
        deduped: list[str] = []
        seen: set[str] = set()
        for query in queries:
            key = query.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(query.strip())
        return deduped[:limit]

    @classmethod
    def _dedupe_items(cls, values: list[str]) -> list[str]:
        # Case-insensitive deduplication while preserving first seen variant.
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(value.strip())
        return deduped

    @classmethod
    def _extract_action_items(cls, user_request: str, patterns: list[str]) -> list[str]:
        # Collect entities matched by intent regex (add/remove/avoid phrases).
        items: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, user_request, flags=re.IGNORECASE):
                items.extend(cls._split_csv(match.group(1)))
        return cls._dedupe_items(items)

    @classmethod
    def _extract_negated_memory_items(cls, user_request: str, existing_items: list[str]) -> list[str]:
        removals: list[str] = []
        if not existing_items:
            return removals

        for item in existing_items:
            normalized_item = cls._normalize_poi_name(item)
            if not normalized_item:
                continue
            for match in re.finditer(re.escape(normalized_item), user_request, flags=re.IGNORECASE):
                before = user_request[max(0, match.start() - 12):match.start()]
                after = user_request[match.end():match.end() + 12]
                before_text = before.lower() + before
                after_text = after.lower() + after
                if any(cue in before_text for cue in cls._POI_REMOVE_PREFIX_CUES) or any(
                    cue in after_text for cue in cls._POI_REMOVE_SUFFIX_CUES
                ):
                    removals.append(normalized_item)
                    break
        return cls._dedupe_items(removals)

    @classmethod
    def _merge_text_field(cls, existing: str, addition: str) -> str:
        # Merge note fields as unique snippets joined by a stable delimiter.
        snippets = [snippet.strip() for snippet in [existing, addition] if snippet and snippet.strip()]
        merged: list[str] = []
        seen: set[str] = set()
        for snippet in snippets:
            key = snippet.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(snippet)
        return " | ".join(merged)

    @classmethod
    def _is_flexible_reply(cls, user_request: str) -> bool:
        lowered = user_request.lower()
        return any(alias in user_request or alias in lowered for alias in cls.PROFILE_FLEXIBLE_REPLIES)

    @classmethod
    def _is_negative_reply(cls, user_request: str) -> bool:
        lowered = user_request.lower().strip()
        if any(alias == lowered for alias in cls.PROFILE_NEGATIVE_REPLIES):
            return True
        return any(alias in user_request or alias in lowered for alias in cls.PROFILE_NEGATIVE_REPLIES)

    @classmethod
    def _extract_confirmed_profile_slots(
        cls,
        user_request: str,
        pending_profile_slots: list[str] | None = None,
    ) -> set[str]:
        combined_text = user_request.lower() + user_request
        confirmed: set[str] = set()
        pending_profile_slots = pending_profile_slots or []

        must_visit_items = cls._extract_action_items(
            user_request,
            [
                r"(?:add|include|also include|保留|加上|加入|想去|一定要去|必须去|安排去)\s*[:：]?\s*(.+?)(?:[。.!?]|$)",
            ],
        )
        avoid_items = cls._extract_action_items(
            user_request,
            [
                r"(?:avoid|skip|不要去|别去|避开|排除)\s*[:：]?\s*(.+?)(?:[。.!?]|$)",
                r"(?:remove|drop|delete|删掉|去掉)\s*[:：]?\s*(.+?)(?:[。.!?]|$)",
            ],
        )

        if cls._extract_explicit_city(user_request):
            confirmed.add("city")
        if cls._parse_trip_days(user_request) is not None:
            confirmed.add("trip_days")
        if (
            cls._find_alias_group(combined_text, cls.TRAVEL_TYPE_ALIASES)
            or cls._extract_clause(user_request, "Interests")
            or any(alias in combined_text for aliases in cls.INTEREST_ALIASES.values() for alias in aliases)
            or must_visit_items
            or cls._extract_clause(user_request, "Must visit")
        ):
            confirmed.add("travel_style")
        if cls._find_alias_group(combined_text, cls.BUDGET_ALIASES):
            confirmed.add("budget_level")
        if cls._find_alias_group(combined_text, cls.PACE_ALIASES):
            confirmed.add("pace")
        if must_visit_items or avoid_items or cls._extract_clause(user_request, "Must visit") or cls._extract_clause(user_request, "Avoid"):
            confirmed.add("constraints")

        if pending_profile_slots:
            active_slot = pending_profile_slots[0]
            if active_slot in {"travel_style", "budget_level", "pace"} and cls._is_flexible_reply(user_request):
                confirmed.add(active_slot)
            if active_slot == "constraints" and (cls._is_negative_reply(user_request) or cls._is_flexible_reply(user_request)):
                confirmed.add(active_slot)

        return confirmed

    @classmethod
    def _order_profile_slots(cls, slots: set[str] | list[str]) -> list[str]:
        slot_set = {slot for slot in slots if slot}
        return [slot for slot in cls.PROFILE_SLOT_ORDER if slot in slot_set]

    @classmethod
    def _resolve_confirmed_profile_slots(
        cls,
        previous_state: ConversationState | None,
        user_request: str,
        user_profile: dict,
    ) -> list[str]:
        if previous_state and previous_state.confirmed_profile_slots:
            confirmed = set(previous_state.confirmed_profile_slots)
        elif previous_state and previous_state.latest_plan:
            confirmed = set(cls.PROFILE_SLOT_ORDER)
        else:
            confirmed = set()

        previous_city = str(previous_state.preference_memory.get("city", "")).strip() if previous_state else ""
        current_city = str(user_profile.get("city", "")).strip()
        if previous_city and current_city and previous_city != current_city:
            confirmed.discard("constraints")

        confirmed.update(
            cls._extract_confirmed_profile_slots(
                user_request,
                pending_profile_slots=previous_state.pending_profile_slots if previous_state else [],
            )
        )
        return cls._order_profile_slots(confirmed)

    @classmethod
    def _next_missing_profile_slots(cls, confirmed_profile_slots: list[str]) -> list[str]:
        confirmed = set(confirmed_profile_slots)
        return [slot for slot in cls.PROFILE_SLOT_ORDER if slot not in confirmed]

    @classmethod
    def _build_profile_checkpoint(cls, user_profile: dict, confirmed_profile_slots: list[str]) -> str:
        confirmed = set(confirmed_profile_slots)
        snippets: list[str] = []
        if "city" in confirmed and user_profile.get("city"):
            snippets.append(f"去 {user_profile['city']}")
        if "trip_days" in confirmed and user_profile.get("trip_days"):
            snippets.append(f"玩 {user_profile['trip_days']} 天")
        if "travel_style" in confirmed:
            if user_profile.get("must_visit"):
                snippets.append("想去 " + "、".join(user_profile["must_visit"][:2]))
            elif user_profile.get("interests"):
                snippets.append(
                    "偏好 "
                    + "、".join(cls.INTEREST_LABELS.get(item, item) for item in user_profile["interests"][:2])
                )
            else:
                snippets.append(cls.TRAVEL_TYPE_LABELS.get(user_profile.get("travel_type", "leisure"), "轻松逛逛"))
        if "budget_level" in confirmed:
            snippets.append(cls.BUDGET_LEVEL_LABELS.get(user_profile.get("budget_level", "medium"), "中等预算"))
        if "pace" in confirmed:
            snippets.append(cls.PACE_LABELS.get(user_profile.get("pace", "balanced"), "适中节奏"))
        return "，".join(snippets[:4])

    @classmethod
    def _build_clarification_question(
        cls,
        user_profile: dict,
        confirmed_profile_slots: list[str],
        missing_profile_slots: list[str],
    ) -> str:
        active_slot = missing_profile_slots[0]
        checkpoint = cls._build_profile_checkpoint(user_profile, confirmed_profile_slots)
        if active_slot == "city":
            return "为了把攻略做准一点，我先确认一下目的地：你这次想去哪个城市？"
        if active_slot == "trip_days":
            prefix = f"目前我先记下了：{checkpoint}。" if checkpoint else ""
            return f"{prefix}这次大概玩几天？比如 2 天、3 天、5 天都可以。"
        if active_slot == "travel_style":
            prefix = f"目前我先记下了：{checkpoint}。" if checkpoint else ""
            return (
                f"{prefix}你更想走哪种路线？比如轻松逛、美食、亲子、主题体验；"
                "如果有特别想去的点，也可以直接告诉我。"
            )
        if active_slot == "budget_level":
            prefix = f"目前我先记下了：{checkpoint}。" if checkpoint else ""
            return f"{prefix}预算大概想走什么档位？低预算 / 中等 / 高预算 都可以。"
        if active_slot == "pace":
            prefix = f"目前我先记下了：{checkpoint}。" if checkpoint else ""
            return f"{prefix}行程节奏想轻松一点、适中，还是尽量排满？"

        prefix = "信息已经差不多齐了。" if len(missing_profile_slots) == 1 else (f"目前我先记下了：{checkpoint}。" if checkpoint else "")
        return f"{prefix}有没有一定要去或想避开的地方？没有的话直接回复“没有”，我就开始生成完整攻略。"

    @classmethod
    def _extract_profile_updates(cls, user_request: str) -> dict:
        # Parse incremental update instructions from follow-up conversation turns.
        # Structure:
        # - replace: overwrite scalar/list fields when explicit instruction exists
        # - add/remove: patch list fields incrementally
        # - append: append text memory fields (notes/extra_request)
        combined_text = user_request.lower() + user_request
        updates = {
            "replace": {},
            "add": {"interests": [], "must_visit": [], "avoid": []},
            "remove": {"interests": [], "must_visit": [], "avoid": []},
            "append": {"notes": "", "extra_request": ""},
        }

        explicit_city = cls._extract_explicit_city(user_request)
        if explicit_city:
            updates["replace"]["city"] = explicit_city

        trip_days = cls._parse_trip_days(user_request)
        if trip_days is not None:
            updates["replace"]["trip_days"] = trip_days

        travel_type = cls._find_alias_group(combined_text, cls.TRAVEL_TYPE_ALIASES)
        if travel_type:
            updates["replace"]["travel_type"] = travel_type
            default_interest = {
                "food": "local food",
                "family": "family friendly",
                "theme": "hidden gems",
            }.get(travel_type)
            if default_interest:
                updates["add"]["interests"].append(default_interest)

        budget_level = cls._find_alias_group(combined_text, cls.BUDGET_ALIASES)
        if budget_level:
            updates["replace"]["budget_level"] = budget_level

        pace = cls._find_alias_group(combined_text, cls.PACE_ALIASES)
        if pace:
            updates["replace"]["pace"] = pace

        travelers = cls._extract_clause(user_request, "Travelers")
        if travelers:
            updates["replace"]["travelers"] = travelers

        notes_clause = cls._extract_clause(user_request, "Use these travel notes as source material")
        if notes_clause:
            updates["append"]["notes"] = notes_clause

        extra_clause = cls._extract_clause(user_request, "Extra request")
        if extra_clause:
            updates["append"]["extra_request"] = extra_clause
        elif re.search(r"第\s*\d+\s*天", user_request) and re.search(
            r"(简单|太少|不够|空|单薄|丰富|增加|加点|多安排|充实|more|denser|too simple|add)",
            combined_text,
        ):
            updates["append"]["extra_request"] = user_request.strip()

        interests_clause = cls._extract_clause(user_request, "Interests")
        if interests_clause:
            updates["replace"]["interests"] = cls._split_csv(interests_clause)
        else:
            inferred_interests = [
                interest
                for interest, aliases in cls.INTEREST_ALIASES.items()
                if any(alias in combined_text for alias in aliases)
            ]
            updates["add"]["interests"].extend(inferred_interests)

        must_visit_clause = cls._extract_clause(user_request, "Must visit")
        if must_visit_clause:
            updates["replace"]["must_visit"] = cls._split_csv(must_visit_clause)

        avoid_clause = cls._extract_clause(user_request, "Avoid")
        if avoid_clause:
            updates["replace"]["avoid"] = cls._split_csv(avoid_clause)

        updates["add"]["must_visit"].extend(
            cls._extract_action_items(
                user_request,
                [
                    r"(?:add|include|also include|保留|加上|加入|想去|一定要去|必须去|安排去)\s*[:：]?\s*(.+?)(?:[。.!?]|$)",
                ],
            )
        )
        updates["remove"]["must_visit"].extend(
            cls._extract_action_items(
                user_request,
                [
                    r"(?:remove|drop|delete|删掉|去掉)\s*[:：]?\s*(.+?)(?:[。.!?]|$)",
                    r"(?:不去|不想去|先不去|不考虑|取消去)\s*[:：]?\s*(.+?)(?:了)?(?:[，,；;。.!?\n]|$)",
                ],
            )
        )
        updates["add"]["avoid"].extend(
            cls._extract_action_items(
                user_request,
                [
                    r"(?:avoid|skip|不要去|别去|避开|排除)\s*[:：]?\s*(.+?)(?:[。.!?]|$)",
                ],
            )
        )

        for field in ("interests", "must_visit", "avoid"):
            updates["add"][field] = cls._dedupe_items(updates["add"][field])
            updates["remove"][field] = cls._dedupe_items(updates["remove"][field])
        updates["add"]["must_visit"] = [cls._normalize_poi_name(item) for item in updates["add"]["must_visit"]]
        updates["remove"]["must_visit"] = [
            normalized
            for normalized in (cls._normalize_poi_name(item) for item in updates["remove"]["must_visit"])
            if normalized
        ]
        if "must_visit" in updates["replace"]:
            updates["replace"]["must_visit"] = [
                normalized
                for normalized in (cls._normalize_poi_name(item) for item in updates["replace"]["must_visit"])
                if normalized
            ]
        return updates

    @classmethod
    def _merge_preference_memory(cls, preference_memory: dict, user_request: str) -> dict:
        # Apply parsed updates on top of previous memory to get latest preference state.
        # This is what makes "Refine Existing Plan" feel conversational instead
        # of forcing the user to repeat the whole trip profile every time.
        merged = deepcopy(preference_memory)
        updates = cls._extract_profile_updates(user_request)
        updates["remove"]["must_visit"] = cls._dedupe_items(
            updates["remove"]["must_visit"]
            + cls._extract_negated_memory_items(user_request, list(merged.get("must_visit", [])))
        )
        city_changed = False
        previous_city = str(merged.get("city", "")).strip()

        for field, value in updates["replace"].items():
            merged[field] = value
            if field == "city" and str(value).strip() and str(value).strip() != previous_city:
                city_changed = True

        if city_changed:
            # City-specific memories should not bleed into a new destination.
            merged["must_visit"] = []
            merged["avoid"] = []
            merged["notes"] = ""
            merged["extra_request"] = ""

        for field in ("interests", "must_visit", "avoid"):
            current_values = cls._dedupe_items(list(merged.get(field, [])))
            removals = {value.lower() for value in updates["remove"].get(field, [])}
            if removals:
                current_values = [value for value in current_values if value.lower() not in removals]
            current_values.extend(updates["add"].get(field, []))
            merged[field] = cls._dedupe_items(current_values)

        # Conflict resolution rule: avoid-list wins over must-visit to prevent unsafe plans.
        must_visit_keys = {value.lower() for value in merged.get("must_visit", [])}
        avoid_keys = {value.lower() for value in merged.get("avoid", [])}
        if must_visit_keys & avoid_keys:
            merged["must_visit"] = [
                value for value in merged.get("must_visit", []) if value.lower() not in avoid_keys
            ]

        if updates["append"]["notes"]:
            merged["notes"] = cls._merge_text_field(merged.get("notes", ""), updates["append"]["notes"])
        if updates["append"]["extra_request"]:
            merged["extra_request"] = cls._merge_text_field(
                merged.get("extra_request", ""),
                updates["append"]["extra_request"],
            )

        return merged

    @classmethod
    def _resolve_user_profile(
        cls,
        user_request: str,
        *,
        default_city: str,
        stored_preferences: dict | None = None,
    ) -> dict:
        # Multi-turn: merge into memory. Single-turn: fresh extraction.
        if stored_preferences:
            return cls._merge_preference_memory(stored_preferences, user_request)
        return cls._extract_user_profile(user_request, default_city=default_city)

    @classmethod
    def _build_strategy_queries(cls, user_profile: dict, city_context: dict | None = None) -> list[str]:
        # Build high-level discovery queries for POI/theme exploration.
        # These queries are meant for the strategy/RAG side, so they can be
        # broader and more thematic than map-search queries.
        queries: list[str] = []
        city = user_profile.get("city", "")
        rag_city = provider_city_name(city, "zh") or city
        for poi_name in user_profile.get("must_visit", []):
            if not poi_name:
                continue
            queries.append(poi_name)
            if rag_city and rag_city not in poi_name:
                queries.append(f"{rag_city} {poi_name}")
        if user_profile.get("notes"):
            note_parts = [part.strip() for part in re.split(r"[\n,，;；/|]+", user_profile["notes"]) if part.strip()]
            queries.extend(note_parts[:6])
        if city_context:
            queries.extend(city_context.get("suggested_queries", [])[:4])

        for interest in user_profile.get("interests", []):
            alias = cls.INTEREST_QUERY_ALIASES.get(interest, interest)
            if rag_city:
                queries.append(f"{rag_city} {alias}")
            else:
                queries.append(alias)

        if city_context:
            recommended_areas = [item.get("name", "") for item in city_context.get("recommended_areas", []) if item.get("name")]
            queries.extend(recommended_areas[:3])

        return cls._dedupe_queries(queries, limit=12)

    @classmethod
    def _decompose_request(
        cls,
        user_request: str,
        user_profile: dict,
        city_context: dict | None = None,
    ) -> dict:
        # Convert one user request into parallelizable subtasks:
        # - strategy queries (thematic ideas)
        # - geo queries (routeable POIs)
        # - condition queries (weather + budget)
        # plus planning constraints for deterministic planner.
        #
        # This is the main "agentic workflow" step. Instead of throwing the
        # entire user question at every tool, we decompose it into smaller asks.
        city = user_profile["city"]
        rag_city = provider_city_name(city, "zh") or city
        combined_text = " ".join(
            part for part in [user_request, user_profile.get("notes", ""), user_profile.get("extra_request", "")] if part
        ).lower()

        strategy_queries = cls._build_strategy_queries(user_profile, city_context)
        geo_queries = list(user_profile.get("must_visit", []))
        provider_city = provider_city_name(city, "zh")
        geo_queries.extend(
            f"{provider_city} {poi_name}"
            for poi_name in user_profile.get("must_visit", [])
            if poi_name and provider_city and provider_city not in poi_name
        )
        geo_queries.extend(
            part.strip()
            for part in re.split(r"[\n,，;；/|]+", user_profile.get("notes", ""))
            if 2 <= len(part.strip()) <= 40
        )
        for interest in user_profile.get("interests", []):
            alias = cls.GEO_QUERY_ALIASES.get(interest, interest)
            geo_queries.append(f"{city} {alias}")

        if user_profile["travel_type"] == "family":
            strategy_queries.append(f"{rag_city} 亲子游")
        if user_profile["travel_type"] == "food":
            strategy_queries.append(f"{rag_city} 美食路线")
        if user_profile["trip_days"] > 1:
            strategy_queries.append(f"{rag_city} {user_profile['trip_days']}天 行程")

        if city_context:
            fallback_geo = city_context.get("suggested_queries", [])[:4]
            if geo_queries:
                # Keep user-requested POIs first, but always blend in a few city defaults so sparse requests
                # still have enough candidate places to fill multi-day itineraries.
                geo_queries.extend(fallback_geo[: max(0, min(3, user_profile["trip_days"]))])
            else:
                geo_queries.extend(fallback_geo)

        rain_sensitive = any(
            term in combined_text
            for term in ["rain", "rainy", "umbrella", "indoor", "下雨", "雨天", "室内"]
        )
        if rain_sensitive:
            strategy_queries.append(f"{rag_city} 雨天 室内")

        if user_profile["budget_level"] != "medium":
            budget_label = cls.BUDGET_LEVEL_LABELS.get(user_profile["budget_level"], user_profile["budget_level"])
            strategy_queries.append(f"{rag_city} {budget_label} 玩法")

        planning_constraints = [
            f"Pace target: {user_profile['pace']}",
            f"Budget target: {user_profile['budget_level']}",
            f"Travel type: {user_profile['travel_type']}",
        ]
        if user_profile.get("must_visit"):
            planning_constraints.append(f"Must keep these if possible: {', '.join(user_profile['must_visit'])}")
        if user_profile.get("avoid"):
            planning_constraints.append(f"Avoid these places or patterns: {', '.join(user_profile['avoid'])}")
        if rain_sensitive:
            planning_constraints.append("Need indoor backups or weather-safe swaps.")
        if user_profile.get("extra_request"):
            planning_constraints.append(f"Extra request: {user_profile['extra_request']}")

        condition_queries = {
            "weather": {
                "city": city,
                "trip_days": user_profile["trip_days"],
                "start_date": user_profile.get("start_date", ""),
                "focus": "rain-aware" if rain_sensitive else "general",
            },
            "cost": {
                "city": city,
                "days": user_profile["trip_days"],
                "budget_level": user_profile["budget_level"],
                "travelers": user_profile.get("travelers", "friends"),
                "user_budget": None,
            },
        }

        return {
            "original_request": user_request,
            "strategy_queries": cls._dedupe_queries(strategy_queries, limit=14),
            "geo_queries": cls._dedupe_queries(geo_queries, limit=14),
            "condition_queries": condition_queries,
            "planning_constraints": planning_constraints,
            "synthesis_goal": f"Produce one executable {user_profile['trip_days']}-day itinerary JSON for {city}.",
        }

    @staticmethod
    def _build_structured_agent_input(user_request: str, user_profile: dict, decomposition: dict) -> str:
        # Feed the model with explicit structured context to reduce hallucinated assumptions.
        # The more we tell the model about already-resolved structure, the less
        # likely it is to skip tools or make up missing details.
        return "\n".join(
            [
                f"Original request: {user_request}",
                f"Normalized profile: {json.dumps(user_profile, ensure_ascii=False)}",
                f"Strategy subtasks: {json.dumps(decomposition['strategy_queries'], ensure_ascii=False)}",
                f"Geo subtasks: {json.dumps(decomposition['geo_queries'], ensure_ascii=False)}",
                f"Condition subtasks: {json.dumps(decomposition['condition_queries'], ensure_ascii=False)}",
                f"Planning constraints: {json.dumps(decomposition['planning_constraints'], ensure_ascii=False)}",
                f"Synthesis goal: {decomposition['synthesis_goal']}",
            ]
        )

    @staticmethod
    def _merge_strategy_into_travel_tips(travel_tips: dict, strategy_context: dict | None) -> dict:
        # Merge RAG snippets into the travel-tip pool so later reasoning and UI
        # summaries can explicitly mention retrieved guide evidence.
        merged = deepcopy(travel_tips or {"tips": []})
        merged.setdefault("tips", [])
        if not strategy_context:
            return merged

        existing_pairs = {
            (str(item.get("poi_name", "")).strip().lower(), str(item.get("tip", "")).strip().lower())
            for item in merged["tips"]
            if isinstance(item, dict)
        }
        for result in strategy_context.get("results", []):
            text = str(result.get("chunk_text", "")).strip()
            if not text:
                continue
            snippet = re.split(r"[。！？!?;\n]", text, maxsplit=1)[0].strip()[:140]
            for poi_name in result.get("metadata", {}).get("poi_names", [])[:3]:
                key = (str(poi_name).strip().lower(), snippet.lower())
                if snippet and key not in existing_pairs:
                    merged["tips"].append({"poi_name": poi_name, "tip": snippet})
                    existing_pairs.add(key)

        for poi_name in strategy_context.get("recommended_pois", [])[:5]:
            key = (str(poi_name).strip().lower(), "recommended by travel-guide retrieval".lower())
            if key not in existing_pairs:
                merged["tips"].append({"poi_name": poi_name, "tip": "Recommended by travel-guide retrieval."})
                existing_pairs.add(key)
        return merged

    def _augment_poi_results_with_strategy(self, user_profile: dict, poi_result: dict, strategy_context: dict | None) -> dict:
        # RAG knows what people recommend; map search knows coordinates.
        # This function makes sure those two worlds are connected.
        if not hasattr(self, "settings"):
            return poi_result

        existing_names = {
            str(item.get("name", "")).strip().lower()
            for item in poi_result.get("results", [])
            if isinstance(item, dict)
        }
        missing_must_visit = [
            poi_name
            for poi_name in user_profile.get("must_visit", [])
            if poi_name.strip().lower() not in existing_names
        ]
        missing_strategy_queries = [
            poi_name
            for poi_name in (strategy_context or {}).get("recommended_pois", [])
            if poi_name.strip().lower() not in existing_names
        ][:6]
        missing_queries = self._dedupe_queries(missing_must_visit + missing_strategy_queries, limit=8)
        if not missing_queries:
            return poi_result

        extra_result = self._search_batch_pois(
            city=user_profile["city"],
            queries=missing_queries,
            limit_per_query=2,
        )
        merged_results = list(poi_result.get("results", []))
        seen = set(existing_names)
        for item in extra_result.get("results", []):
            name_key = str(item.get("name", "")).strip().lower()
            if not name_key or name_key in seen:
                continue
            # Verify the returned POI name meaningfully matches the query that produced it.
            # Amap fuzzy-matches "黄鹤楼" in Chengdu and returns "新场黄鹤楼" — we keep it
            # only if at least 2 characters from the original query appear in the result name.
            query_for_item = next(
                (q for q in missing_queries if q.strip().lower() == name_key or
                 sum(1 for ch in q if ch in item.get("name", "")) >= 2),
                None,
            )
            if query_for_item is None:
                continue
            merged_results.append(item)
            seen.add(name_key)

        merged = deepcopy(poi_result)
        merged["results"] = merged_results
        merged["strategy_augmented_queries"] = missing_queries
        return merged

    @staticmethod
    def _summarize_budget(user_profile: dict, plan: dict, poi_result: dict, cost_summary: dict | None = None) -> dict:
        # Merge our own attraction-level estimate with optional Group C cost envelope.
        poi_prices = [
            float(item.get("ticket_price", 0.0))
            for item in poi_result.get("results", [])
            if isinstance(item, dict)
        ]
        candidate_avg = round(sum(poi_prices) / len(poi_prices), 2) if poi_prices else 0.0
        summary = {
            "budget_level": user_profile.get("budget_level", "medium"),
            "estimated_core_attraction_cost": round(float(plan.get("total_estimated_cost", 0.0)), 2),
            "candidate_poi_average_ticket_price": candidate_avg,
            "assumption": "Accommodation and long-haul transport are excluded unless another team provides them.",
        }
        if cost_summary:
            summary["trip_budget_estimate"] = cost_summary.get("totals", {})
            summary["pricing_notes"] = cost_summary.get("pricing_notes", [])
            summary["budget_fit"] = cost_summary.get("budget_fit", {})
            summary["stay_and_food_breakdown"] = cost_summary.get("breakdown", {})
            summary["assumption"] = "Accommodation, food, and local transport come from Group C; attraction cost remains our own estimate."
        return summary

    @staticmethod
    def _render_budget_section(cost_summary: dict | None, budget_summary: dict) -> str:
        # Render an optional markdown budget block for final report.
        if not cost_summary:
            return ""

        totals = cost_summary.get("totals", {})
        budget_fit = cost_summary.get("budget_fit", {})
        breakdown = cost_summary.get("breakdown", {})
        lines = [
            "## Budget Envelope",
            f"- Trip estimate: CNY {totals.get('min', 0):.0f}-{totals.get('max', 0):.0f}",
            f"- Attraction estimate in current itinerary: CNY {budget_summary.get('estimated_core_attraction_cost', 0):.0f}",
        ]
        if breakdown:
            hotel = breakdown.get("hotel_per_night", {})
            food = breakdown.get("food_per_day", {})
            transport = breakdown.get("local_transport_total", {})
            lines.extend(
                [
                    f"- Hotel per night: CNY {hotel.get('min', 0):.0f}-{hotel.get('max', 0):.0f}",
                    f"- Food per day: CNY {food.get('min', 0):.0f}-{food.get('max', 0):.0f}",
                    f"- Local transport total: CNY {transport.get('min', 0):.0f}-{transport.get('max', 0):.0f}",
                ]
            )
        if budget_fit.get("user_budget") is not None:
            lines.append(
                f"- User budget fit: {'within budget' if budget_fit.get('within_budget') else 'above full budget range'}"
            )
            if budget_fit.get("minimum_feasible") and not budget_fit.get("within_budget"):
                lines.append("- Minimum feasible version is possible, but the upper end exceeds the stated budget.")
        for note in cost_summary.get("pricing_notes", [])[:2]:
            lines.append(f"- Note: {note}")
        return "\n".join(lines)

    @staticmethod
    def _derive_target_districts(plan: dict) -> list[str]:
        # Infer where to stay: prioritize districts repeatedly used in itinerary days/items.
        district_counts: dict[str, int] = {}
        for day in plan.get("days", []):
            area = day.get("area", "")
            if area:
                district_counts[area] = district_counts.get(area, 0) + 2
            for item in day.get("items", []):
                district = item.get("district", "")
                if district:
                    district_counts[district] = district_counts.get(district, 0) + 1
        return [district for district, _ in sorted(district_counts.items(), key=lambda pair: pair[1], reverse=True)[:3]]

    def _build_hotel_recommendations(
        self,
        *,
        user_profile: dict,
        plan: dict,
        cost_summary: dict | None,
    ) -> dict:
        # Recommend hotels consistent with route concentration and budget envelope.
        return get_hotel_candidates(
            city=user_profile["city"],
            trip_days=user_profile["trip_days"],
            start_date=user_profile.get("start_date", ""),
            target_districts=self._derive_target_districts(plan),
            budget_level=user_profile.get("budget_level", "medium"),
            cost_summary=cost_summary,
        )

    @staticmethod
    def _render_hotel_section(hotel_recommendations: dict | None) -> str:
        # Render concise markdown section with areas + top hotel candidates.
        if not hotel_recommendations:
            return ""
        lines = ["## Stay Suggestions"]
        for area in hotel_recommendations.get("recommended_areas", [])[:3]:
            lines.append(f"- Area: {area.get('district', 'Unknown')} — {area.get('reason', '')}")
        for hotel in hotel_recommendations.get("hotel_candidates", [])[:3]:
            price_text = (
                f"CNY {float(hotel['min_price']):.0f}+"
                if hotel.get("min_price") is not None
                else "price unavailable"
            )
            district = hotel.get("district") or "Unknown district"
            lines.append(
                f"- Hotel: {hotel.get('name', 'Unknown')} ({district}, {price_text}, source: {hotel.get('source', 'unknown')})"
            )
            if hotel.get("price_note"):
                lines.append(f"  Note: {hotel['price_note']}")
        for note in hotel_recommendations.get("selection_notes", [])[:2]:
            lines.append(f"- Note: {note}")
        return "\n".join(lines)

    @staticmethod
    def _build_guide_references(strategy_context: dict | None) -> list[str]:
        # Extract a few short guide references that can later be shown directly
        # to the user as "why this route looks like this".
        if not strategy_context:
            return []
        references: list[str] = []
        for result in strategy_context.get("results", [])[:3]:
            text = str(result.get("chunk_text", "")).strip()
            if not text:
                continue
            snippet = re.split(r"[。！？!?;\n]", text, maxsplit=1)[0].strip()
            if snippet:
                references.append(snippet[:120])
        for note in strategy_context.get("local_pitfalls", [])[:2]:
            if note and note not in references:
                references.append(str(note).strip()[:120])
        for neighborhood in strategy_context.get("neighborhood_notes", [])[:2]:
            district = str(neighborhood.get("district", "")).strip()
            if district:
                references.append(f"攻略里这个区域被反复提到：{district}")
        return references[:4]

    def _build_orchestration_payload(
        self,
        *,
        user_profile: dict,
        decomposition: dict,
        tool_results: dict,
        plan: dict,
        report: str,
    ) -> AgentOrchestrationResult:
        # Build a rich handoff bundle for multi-group collaboration and debugging.
        # This payload is more verbose than the user-facing answer because it is
        # designed for team handoff and integration inspection.
        city_context = tool_results["get_city_context"]
        strategy_context = tool_results.get("get_strategy_context", {})
        poi_result = self._augment_poi_results_with_strategy(
            user_profile,
            tool_results["search_batch_pois"],
            strategy_context,
        )
        tool_results["search_batch_pois"] = poi_result
        weather = tool_results["get_weather_forecast"]
        cost_summary = tool_results.get("get_cost_summary")
        travel_tips = self._merge_strategy_into_travel_tips(
            tool_results["get_travel_tips"],
            strategy_context,
        )
        tool_results["get_travel_tips"] = travel_tips
        budget_summary = self._summarize_budget(user_profile, plan, poi_result, cost_summary=cost_summary)
        hotel_recommendations = tool_results.get("get_hotel_candidates", {})

        upstream_requests = {
            "group_a_strategy": {
                "objective": "Retrieve destination knowledge, theme suggestions, and strategy-level POI ideas.",
                "city": user_profile["city"],
                "travel_type": user_profile["travel_type"],
                "interests": user_profile.get("interests", []),
                "must_visit": user_profile.get("must_visit", []),
                "notes": user_profile.get("notes", ""),
                "query_candidates": decomposition["strategy_queries"],
                "expected_response_fields": [
                    "recommended_pois",
                    "theme_suggestions",
                    "local_pitfalls",
                    "neighborhood_notes",
                ],
            },
            "group_b_geo": {
                "objective": "Normalize POIs, coordinates, district grouping, and route feasibility.",
                "city": user_profile["city"],
                "poi_queries": decomposition["geo_queries"],
                "must_visit": user_profile.get("must_visit", []),
                "expected_response_fields": [
                    "name",
                    "lat",
                    "lon",
                    "district",
                    "address",
                    "open_hours",
                    "ticket_price",
                ],
            },
            "group_c_conditions": {
                "objective": "Provide trip-window weather and budget envelope.",
                "city": user_profile["city"],
                "trip_days": user_profile["trip_days"],
                "start_date": user_profile.get("start_date", ""),
                "travelers": user_profile.get("travelers", "friends"),
                "budget_level": user_profile.get("budget_level", "medium"),
                "query_bundle": decomposition["condition_queries"],
                "expected_response_fields": [
                    "daily_weather",
                    "budget_summary",
                    "pricing_notes",
                ],
            },
        }
        collected_context = {
            "request_breakdown": decomposition,
            "strategy_context": {
                "city_context": city_context,
                "rag_context": tool_results.get("get_strategy_context", {}),
                "travel_tips": travel_tips,
            },
            "geo_context": {
                "poi_result": poi_result,
                "poi_count": len(poi_result.get("results", [])),
            },
            "conditions_context": {
                "weather": weather,
                "cost_summary": cost_summary,
                "budget_summary": budget_summary,
            },
            "lodging_context": hotel_recommendations,
            "handoff_for_delivery_group": {
                "itinerary_json": plan,
            },
        }
        return AgentOrchestrationResult(
            user_profile=user_profile,
            decomposition=decomposition,
            upstream_requests=upstream_requests,
            collected_context=collected_context,
            itinerary_json=plan,
            hotel_recommendations=hotel_recommendations,
            report=report,
            tool_logs=tool_results.get("_logs", []),
        )

    def _auto_finish(self, user_profile: dict, tool_results: dict) -> AgentRunResult:
        # Deterministic finalization path once minimum required tool data is present.
        # The planner is called only after we have enough:
        # - city context
        # - POIs
        # - weather
        # - travel tips / strategy context
        city_context = tool_results["get_city_context"]
        strategy_context = tool_results.get("get_strategy_context", {})
        poi_result = self._augment_poi_results_with_strategy(
            user_profile,
            tool_results["search_batch_pois"],
            strategy_context,
        )
        tool_results["search_batch_pois"] = poi_result
        trace_planner_input(strategy_context, len(poi_result.get("results", [])))
        weather = tool_results["get_weather_forecast"]
        cost_summary = tool_results.get("get_cost_summary")
        tips = self._merge_strategy_into_travel_tips(
            tool_results["get_travel_tips"],
            strategy_context,
        )
        tool_results["get_travel_tips"] = tips
        plan = plan_itinerary(
            user_profile=user_profile,
            candidate_pois=poi_result["results"],
            weather=weather,
            city_context=city_context,
            travel_tips=tips,
            strategy_context=strategy_context,
            settings=self.settings,
        )
        plan["guide_references"] = self._build_guide_references(strategy_context)
        plan["strategy_summary"] = {
            "recommended_pois": strategy_context.get("recommended_pois", []),
            "theme_suggestions": strategy_context.get("theme_suggestions", []),
            "neighborhood_notes": strategy_context.get("neighborhood_notes", []),
        }
        plan["weather_payload"] = weather
        trace_plan_output(plan)
        report = render_markdown_report(
            plan=plan,
            user_profile=user_profile,
            city_context=city_context,
            weather=weather,
        )
        budget_summary = self._summarize_budget(user_profile, plan, poi_result, cost_summary=cost_summary)
        hotel_recommendations = self._build_hotel_recommendations(
            user_profile=user_profile,
            plan=plan,
            cost_summary=cost_summary,
        )
        tool_results["get_hotel_candidates"] = hotel_recommendations
        budget_section = self._render_budget_section(cost_summary, budget_summary)
        hotel_section = self._render_hotel_section(hotel_recommendations)
        sections = [report]
        if budget_section:
            sections.append(budget_section)
        if hotel_section:
            sections.append(hotel_section)
        final_report = "\n\n".join(sections)
        return AgentRunResult(
            answer=final_report,
            tool_logs=tool_results.get("_logs", []),
            raw_response="",
            plan=plan,
        )

    def _execute(
        self,
        user_request: str,
        max_rounds: int = 8,
        stored_preferences: dict | None = None,
    ) -> tuple[dict, dict, dict, str]:
        # Core control loop:
        # 1) normalize request/profile
        # 2) let model decide tool sequence
        # 3) execute tool calls and return outputs
        # 4) auto-finish when required tool set is complete
        # 5) fallback-fill missing tools if model stops early
        default_city = stored_preferences.get("city", self.settings.default_city) if stored_preferences else self.settings.default_city
        trace_session_start(user_request)
        user_profile = self._resolve_user_profile(
            user_request,
            default_city=default_city,
            stored_preferences=stored_preferences,
        )
        trace_profile(user_profile)
        decomposition = self._decompose_request(user_request, user_profile)
        trace_decomposition(decomposition)
        tool_results: dict[str, object] = {
            "_logs": [
                {
                    "tool_name": "decompose_request",
                    "arguments": {"user_request": user_request},
                    "result_preview": json.dumps(decomposition, ensure_ascii=False)[:500],
                }
            ]
            + (
                [
                    {
                        "tool_name": "merge_preference_memory",
                        "arguments": {"stored_preferences": stored_preferences},
                        "result_preview": json.dumps(user_profile, ensure_ascii=False)[:500],
                    }
                ]
                if stored_preferences
                else []
            ),
            "_decomposition": decomposition,
        }

        # Pre-fill all required tools deterministically to skip LLM tool-calling loop.
        city = user_profile["city"]
        strategy_queries = decomposition.get("strategy_queries") or [f"{city} {user_profile['travel_type']} itinerary"]
        geo_queries = decomposition.get("geo_queries") or [f"{city} landmark"]

        tool_latencies: dict[str, int] = {}

        _t0 = time.monotonic()
        tool_results["get_city_context"] = get_city_context(city, user_profile["travel_type"])
        tool_latencies["get_city_context"] = int((time.monotonic() - _t0) * 1000)
        self._append_tool_log(
            tool_results,
            tool_name="get_city_context",
            arguments={"city": city, "travel_type": user_profile["travel_type"]},
            result=tool_results["get_city_context"],
        )
        trace_tool_call("get_city_context", {"city": city, "travel_type": user_profile["travel_type"]}, tool_results["get_city_context"])
        _rag_queries = self._dedupe_queries(strategy_queries, limit=6)
        trace_rag_input(queries=_rag_queries, city=city, travel_type=user_profile["travel_type"], top_k=5)
        _t0 = time.monotonic()
        with trace_step_timer("RAG retrieval"):
            tool_results["get_strategy_context"] = self._get_strategy_context(
                city=city,
                queries=_rag_queries,
                travel_type=user_profile["travel_type"],
                top_k=5,
            )
        tool_latencies["get_strategy_context"] = int((time.monotonic() - _t0) * 1000)
        trace_rag_output(tool_results["get_strategy_context"])
        self._append_tool_log(
            tool_results,
            tool_name="get_strategy_context",
            arguments={
                "city": city,
                "queries": self._dedupe_queries(strategy_queries, limit=6),
                "travel_type": user_profile["travel_type"],
                "top_k": 5,
            },
            result=tool_results["get_strategy_context"],
        )
        _t0 = time.monotonic()
        tool_results["get_weather_forecast"] = self._get_weather_forecast(
            city=city,
            trip_days=user_profile["trip_days"],
            start_date=user_profile.get("start_date", ""),
        )
        tool_latencies["get_weather_forecast"] = int((time.monotonic() - _t0) * 1000)
        self._append_tool_log(
            tool_results,
            tool_name="get_weather_forecast",
            arguments={
                "city": city,
                "trip_days": user_profile["trip_days"],
                "start_date": user_profile.get("start_date", ""),
            },
            result=tool_results["get_weather_forecast"],
        )
        trace_tool_call("get_weather_forecast", {"city": city, "trip_days": user_profile["trip_days"]}, tool_results["get_weather_forecast"])
        _t0 = time.monotonic()
        tool_results["search_batch_pois"] = self._search_batch_pois(
            city=city,
            queries=self._dedupe_queries(geo_queries + user_profile.get("must_visit", []), limit=10),
            limit_per_query=3,
        )
        tool_latencies["search_batch_pois"] = int((time.monotonic() - _t0) * 1000)
        self._append_tool_log(
            tool_results,
            tool_name="search_batch_pois",
            arguments={
                "city": city,
                "queries": self._dedupe_queries(geo_queries + user_profile.get("must_visit", []), limit=10),
                "limit_per_query": 3,
            },
            result=tool_results["search_batch_pois"],
        )
        trace_tool_call("search_batch_pois", {"city": city, "queries": self._dedupe_queries(geo_queries + user_profile.get("must_visit", []), limit=10)}, tool_results["search_batch_pois"])
        _t0 = time.monotonic()
        tool_results["get_cost_summary"] = self._get_cost_summary(
            city=city,
            days=user_profile["trip_days"],
            budget_level=user_profile["budget_level"],
            user_budget=decomposition.get("condition_queries", {}).get("cost", {}).get("user_budget"),
        )
        tool_latencies["get_cost_summary"] = int((time.monotonic() - _t0) * 1000)
        self._append_tool_log(
            tool_results,
            tool_name="get_cost_summary",
            arguments={
                "city": city,
                "days": user_profile["trip_days"],
                "budget_level": user_profile["budget_level"],
                "user_budget": decomposition.get("condition_queries", {}).get("cost", {}).get("user_budget"),
            },
            result=tool_results["get_cost_summary"],
        )
        trace_tool_call("get_cost_summary", {"city": city, "days": user_profile["trip_days"], "budget_level": user_profile["budget_level"]}, tool_results["get_cost_summary"])
        poi_names = [item["name"] for item in tool_results["search_batch_pois"].get("results", [])[:8]]
        _t0 = time.monotonic()
        tool_results["get_travel_tips"] = self._get_travel_tips(
            city=city,
            poi_names=poi_names,
            travel_type=user_profile["travel_type"],
            interests=user_profile.get("interests", []),
        )
        tool_latencies["get_travel_tips"] = int((time.monotonic() - _t0) * 1000)
        self._append_tool_log(
            tool_results,
            tool_name="get_travel_tips",
            arguments={
                "city": city,
                "poi_names": poi_names,
                "travel_type": user_profile["travel_type"],
                "interests": user_profile.get("interests", []),
            },
            result=tool_results["get_travel_tips"],
        )
        trace_tool_call("get_travel_tips", {"city": city, "poi_names": poi_names, "travel_type": user_profile["travel_type"]}, tool_results["get_travel_tips"])
        tool_results["_tool_latencies"] = tool_latencies
        tool_results["_logs"].append({
            "tool_name": "_tool_latencies",
            "arguments": {},
            "result_preview": json.dumps(tool_latencies),
        })
        result = self._auto_finish(user_profile=user_profile, tool_results=tool_results)
        return user_profile, tool_results, result.plan or {}, result.answer

        structured_request = self._build_structured_agent_input(user_request, user_profile, decomposition)
        client = self._ensure_response_client()
        response = client.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=structured_request,
            tools=self.build_tools(),
        )
        tool_logs: list[dict] = []

        for _ in range(max_rounds):
            # Pull tool calls from latest model response.
            function_calls = self._extract_function_calls(response)
            if not function_calls:
                # If model stops issuing calls but we already have full required context, finish.
                if {
                    "get_strategy_context",
                    "get_city_context",
                    "search_batch_pois",
                    "get_weather_forecast",
                    "get_cost_summary",
                    "get_travel_tips",
                }.issubset(tool_results.keys()):
                    result = self._auto_finish(user_profile=user_profile, tool_results=tool_results)
                    return user_profile, tool_results, result.plan or {}, result.answer
                break

            tool_outputs = []
            for item in function_calls:
                function_name = item.name
                # Keep loop resilient: malformed args or runtime tool errors become structured error outputs.
                try:
                    function_args = json.loads(item.arguments or "{}")
                except json.JSONDecodeError as exc:
                    function_args = {}
                    function_result = {"error": f"Invalid function arguments: {exc}"}
                else:
                    try:
                        function_result = self.tool_impls[function_name](**function_args)
                    except Exception as exc:
                        function_result = {"error": f"{type(exc).__name__}: {exc}"}

                tool_logs.append(
                    {
                        "tool_name": function_name,
                        "arguments": function_args,
                        "result_preview": self._preview_tool_result(function_result),
                    }
                )
                tool_results["_logs"].append(tool_logs[-1])
                tool_results[function_name] = function_result

                # Send tool result back to model so it can decide subsequent actions.
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": json.dumps(function_result, ensure_ascii=False),
                    }
                )

            # Fast-path: if minimum required tool set is complete, skip extra model roundtrips.
            if {
                "get_strategy_context",
                "get_city_context",
                "search_batch_pois",
                "get_weather_forecast",
                "get_cost_summary",
                "get_travel_tips",
            }.issubset(tool_results.keys()):
                result = self._auto_finish(user_profile=user_profile, tool_results=tool_results)
                return user_profile, tool_results, result.plan or {}, result.answer

            response = client.responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=tool_outputs,
                tools=self.build_tools(),
                previous_response_id=response.id,
            )

        # Fallback layer: if model under-calls tools, run missing tools directly and still finish.
        missing = {
            "get_strategy_context",
            "get_city_context",
            "search_batch_pois",
            "get_weather_forecast",
            "get_cost_summary",
            "get_travel_tips",
        } - set(tool_results.keys())
        if missing:
            if "get_strategy_context" in missing:
                tool_results["get_strategy_context"] = self._get_strategy_context(
                    city=user_profile["city"],
                    queries=decomposition["strategy_queries"] or [f"{user_profile['city']} {user_profile['travel_type']} itinerary"],
                    travel_type=user_profile["travel_type"],
                    top_k=8,
                )
            if "get_city_context" in missing:
                tool_results["get_city_context"] = get_city_context(user_profile["city"], user_profile["travel_type"])
            if "search_batch_pois" in missing:
                strategy_queries = tool_results.get("get_strategy_context", {}).get("recommended_pois", [])
                tool_results["search_batch_pois"] = self._search_batch_pois(
                    city=user_profile["city"],
                    queries=(
                        self._dedupe_queries(
                            decomposition["geo_queries"]
                            + strategy_queries
                            + user_profile["must_visit"]
                        )
                        or [f"{user_profile['city']} landmark"]
                    ),
                    limit_per_query=3,
                )
            if "get_weather_forecast" in missing:
                tool_results["get_weather_forecast"] = self._get_weather_forecast(
                    city=user_profile["city"],
                    trip_days=user_profile["trip_days"],
                    start_date=user_profile.get("start_date", ""),
                )
            if "get_cost_summary" in missing:
                tool_results["get_cost_summary"] = self._get_cost_summary(
                    city=user_profile["city"],
                    days=user_profile["trip_days"],
                    budget_level=user_profile["budget_level"],
                    user_budget=decomposition["condition_queries"].get("cost", {}).get("user_budget"),
                )
            if "get_travel_tips" in missing:
                poi_names = [
                    item["name"]
                    for item in tool_results["search_batch_pois"].get("results", [])[:8]
                ]
                tool_results["get_travel_tips"] = self._get_travel_tips(
                    city=user_profile["city"],
                    poi_names=poi_names,
                    travel_type=user_profile["travel_type"],
                    interests=user_profile.get("interests", []),
                )
        result = self._auto_finish(user_profile=user_profile, tool_results=tool_results)
        return user_profile, tool_results, result.plan or {}, result.answer

    def _build_conversation_state(
        self,
        *,
        previous_state: ConversationState | None,
        user_message: str,
        user_profile: dict,
        plan: dict | None,
        hotel_recommendations: dict | None,
        report: str,
        confirmed_profile_slots: list[str] | None = None,
        pending_profile_slots: list[str] | None = None,
        needs_clarification: bool = False,
    ) -> ConversationState:
        # Append a compact turn record and refresh "latest" snapshots.
        turn_history = list(previous_state.turn_history) if previous_state else []
        turn_history.append(
            {
                "user_message": user_message,
                "resolved_profile": deepcopy(user_profile),
                "trip_city": user_profile.get("city", ""),
                "trip_days": user_profile.get("trip_days", 0),
                "needs_clarification": needs_clarification,
                "pending_profile_slots": list(pending_profile_slots or []),
            }
        )
        return ConversationState(
            preference_memory=deepcopy(user_profile),
            latest_user_profile=deepcopy(user_profile),
            latest_plan=deepcopy(plan) if plan else None,
            latest_hotel_recommendations=deepcopy(hotel_recommendations),
            latest_report=report,
            confirmed_profile_slots=list(confirmed_profile_slots or []),
            pending_profile_slots=list(pending_profile_slots or []),
            needs_clarification=needs_clarification,
            turn_history=turn_history,
        )

    def _run_conversation_turn(
        self,
        *,
        previous_state: ConversationState | None,
        user_request: str,
        max_rounds: int = 8,
    ) -> ConversationRunResult:
        stored_preferences = previous_state.preference_memory if previous_state else None
        default_city = (
            stored_preferences.get("city", self.settings.default_city)
            if stored_preferences
            else self.settings.default_city
        )
        preview_profile = self._resolve_user_profile(
            user_request,
            default_city=default_city,
            stored_preferences=stored_preferences,
        )
        confirmed_profile_slots = self._resolve_confirmed_profile_slots(
            previous_state=previous_state,
            user_request=user_request,
            user_profile=preview_profile,
        )
        missing_profile_slots = self._next_missing_profile_slots(confirmed_profile_slots)

        if missing_profile_slots:
            question = self._build_clarification_question(
                user_profile=preview_profile,
                confirmed_profile_slots=confirmed_profile_slots,
                missing_profile_slots=missing_profile_slots,
            )
            tool_logs = [
                {
                    "tool_name": "profile_completeness_check",
                    "arguments": {"user_request": user_request},
                    "result_preview": json.dumps(
                        {
                            "resolved_profile": preview_profile,
                            "confirmed_profile_slots": confirmed_profile_slots,
                            "missing_profile_slots": missing_profile_slots,
                            "follow_up_question": question,
                        },
                        ensure_ascii=False,
                    )[:800],
                }
            ]
            state = self._build_conversation_state(
                previous_state=previous_state,
                user_message=user_request,
                user_profile=preview_profile,
                plan=None,
                hotel_recommendations=None,
                report=question,
                confirmed_profile_slots=confirmed_profile_slots,
                pending_profile_slots=missing_profile_slots,
                needs_clarification=True,
            )
            return ConversationRunResult(
                state=state,
                answer=question,
                tool_logs=tool_logs,
                plan=None,
                needs_clarification=True,
                missing_profile_slots=missing_profile_slots,
            )

        user_profile, tool_results, plan, report = self._execute(
            user_request,
            max_rounds=max_rounds,
            stored_preferences=stored_preferences,
        )
        state = self._build_conversation_state(
            previous_state=previous_state,
            user_message=user_request,
            user_profile=user_profile,
            plan=plan,
            hotel_recommendations=tool_results.get("get_hotel_candidates"),
            report=report,
            confirmed_profile_slots=confirmed_profile_slots,
            pending_profile_slots=[],
            needs_clarification=False,
        )
        return ConversationRunResult(
            state=state,
            answer=report,
            tool_logs=tool_results.get("_logs", []),
            plan=plan,
            needs_clarification=False,
            missing_profile_slots=[],
        )

    def start_conversation(self, user_request: str, max_rounds: int = 8) -> ConversationRunResult:
        # Initialize state for first turn.
        return self._run_conversation_turn(
            previous_state=None,
            user_request=user_request,
            max_rounds=max_rounds,
        )

    def continue_conversation(
        self,
        state: ConversationState,
        user_request: str,
        max_rounds: int = 8,
    ) -> ConversationRunResult:
        # Continue planning with preference memory from prior turns.
        return self._run_conversation_turn(
            previous_state=state,
            user_request=user_request,
            max_rounds=max_rounds,
        )

    def run(self, user_request: str, max_rounds: int = 8) -> AgentRunResult:
        # One-shot convenience API.
        _, tool_results, plan, report = self._execute(user_request, max_rounds=max_rounds)
        return AgentRunResult(
            answer=report,
            tool_logs=tool_results.get("_logs", []),
            raw_response="",
            plan=plan,
        )

    def run_orchestrated(self, user_request: str, max_rounds: int = 8) -> AgentOrchestrationResult:
        # One-shot API that returns full orchestration artifacts.
        user_profile, tool_results, plan, report = self._execute(user_request, max_rounds=max_rounds)
        return self._build_orchestration_payload(
            user_profile=user_profile,
            decomposition=tool_results.get("_decomposition", {}),
            tool_results=tool_results,
            plan=plan,
            report=report,
        )
