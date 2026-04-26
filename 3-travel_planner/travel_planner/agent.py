## author:SUN Bin
from __future__ import annotations

from copy import deepcopy
import json
import re
import time
from dataclasses import dataclass, field

from .city_names import CITY_ALIASES, normalize_city_name, normalize_location_display_name, normalize_poi_display_name, normalize_rag_query_text, provider_city_name
from .config import Settings
from .debug_tracer import (
    trace_decomposition,
    trace_plan_output,
    trace_planner_input,
    trace_profile,
    trace_rag_input,
    trace_rag_output,
    trace_session_start,
    trace_tool_call,
    trace_turn_understanding,
)
from .llm import build_turn_understanding_messages, create_response_client
from .planner import plan_itinerary, render_markdown_report
from .tools.city_context import get_city_context
from .tools.cost_adapter import get_group_c_cost_summary
from .tools.hotel_adapter import get_hotel_candidates
from .tools.strategy_rag_adapter import get_strategy_context
from .tools.weather_adapter import get_group_c_weather_forecast
from .tools.poi import search_batch_pois
from .tools.tips import get_travel_tips

"""LLM-first orchestration layer for the travel planner.

The guiding design is:
1. Let the model understand the user and produce structured state.
2. Keep deterministic code focused on tool I/O, normalization, and safety.
3. Avoid encoding too much product behavior in regex-heavy control flow.
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


@dataclass(slots=True)
class TurnUnderstandingResult:
    """Structured understanding of one user turn before tool execution."""

    resolved_profile: dict
    missing_profile_slots: list[str]
    needs_clarification: bool
    clarification_question: str = ""
    decomposition_overrides: dict = field(default_factory=dict)
    source: str = "heuristic"
    raw_output: str = ""


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
        "medium": ["medium budget", "budget medium", "中等预算", "适中预算", "预算适中", "中等", "中档"],
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
    PROFILE_SLOT_ORDER = ("city", "trip_days", "travel_style", "budget_level", "pace", "constraints")
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
        self.settings = settings or Settings.from_env()
        self.client = None
        self.model = self.settings.foundry_deployment

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
    def _preview_tool_result(result: object, limit: int = 500) -> str:
        try:
            preview = json.dumps(result, ensure_ascii=False)
        except Exception:
            preview = str(result)
        return preview[:limit]

    # --- Profile normalization helpers -------------------------------------

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
    def _record_tool_latency(tool_results: dict[str, object], tool_name: str, started_at: float) -> None:
        latencies = tool_results.setdefault("_latencies", {})
        if isinstance(latencies, dict):
            latencies[tool_name] = int((time.monotonic() - started_at) * 1000)

    @classmethod
    def _append_latency_log(cls, tool_results: dict[str, object]) -> None:
        latencies = tool_results.get("_latencies")
        if not isinstance(latencies, dict):
            return
        tool_results.setdefault("_logs", []).append(
            {
                "tool_name": "_tool_latencies",
                "arguments": {},
                "result_preview": cls._preview_tool_result(latencies, limit=2000),
            }
        )

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict | None:
        if not raw_text.strip():
            return None
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", raw_text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    @classmethod
    def _default_user_profile(cls, default_city: str) -> dict:
        city = normalize_city_name(default_city) or default_city or "Hong Kong"
        return {
            "city": city,
            "start_date": "",
            "trip_days": 3,
            "travel_type": "leisure",
            "travelers": "friends",
            "budget_level": "medium",
            "pace": "balanced",
            "interests": [],
            "must_visit": [],
            "avoid": [],
            "notes": "",
            "extra_request": "",
        }

    @classmethod
    def _coerce_profile_scalar(cls, value: object, allowed: set[str], aliases: dict[str, list[str]], default: str) -> str:
        text = str(value or "").strip()
        if not text:
            return default
        lowered = text.lower()
        if lowered in allowed:
            return lowered
        return cls._find_alias_group(lowered + text, aliases) or default

    @classmethod
    def _coerce_text_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return cls._split_csv(str(value))

    @classmethod
    def _normalize_interest_item(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        lowered = normalized.lower()
        if lowered in cls.INTEREST_ALIASES:
            return lowered
        return cls._find_alias_group(lowered + normalized, cls.INTEREST_ALIASES) or normalized

    @classmethod
    def _sanitize_resolved_profile(
        cls,
        candidate: dict | None,
        *,
        default_city: str,
        stored_preferences: dict | None = None,
    ) -> dict:
        base = deepcopy(stored_preferences) if stored_preferences else cls._default_user_profile(default_city)
        candidate = candidate or {}

        city = normalize_city_name(str(candidate.get("city", "")).strip()) or base.get("city") or default_city
        base["city"] = city
        start_date = str(candidate.get("start_date", base.get("start_date", "")) or "").strip()
        base["start_date"] = start_date

        trip_days_value = candidate.get("trip_days", base.get("trip_days", 3))
        if isinstance(trip_days_value, int):
            trip_days = trip_days_value
        else:
            trip_days = cls._parse_trip_days(str(trip_days_value)) or int(base.get("trip_days", 3) or 3)
        base["trip_days"] = max(1, min(14, int(trip_days)))

        base["travel_type"] = cls._coerce_profile_scalar(
            candidate.get("travel_type", base.get("travel_type", "leisure")),
            {"leisure", "family", "food", "theme"},
            cls.TRAVEL_TYPE_ALIASES,
            str(base.get("travel_type", "leisure")),
        )
        base["budget_level"] = cls._coerce_profile_scalar(
            candidate.get("budget_level", base.get("budget_level", "medium")),
            {"low", "medium", "high"},
            cls.BUDGET_ALIASES,
            str(base.get("budget_level", "medium")),
        )
        base["pace"] = cls._coerce_profile_scalar(
            candidate.get("pace", base.get("pace", "balanced")),
            {"slow", "balanced", "packed"},
            cls.PACE_ALIASES,
            str(base.get("pace", "balanced")),
        )

        travelers = str(candidate.get("travelers", base.get("travelers", "friends")) or "").strip()
        base["travelers"] = travelers or "friends"

        interests = candidate.get("interests", base.get("interests", []))
        base["interests"] = cls._dedupe_items(
            [
                normalized
                for normalized in (cls._normalize_interest_item(item) for item in cls._coerce_text_list(interests))
                if normalized
            ]
        )

        must_visit = candidate.get("must_visit", base.get("must_visit", []))
        base["must_visit"] = [
            normalized
            for normalized in (cls._normalize_poi_name(item) for item in cls._coerce_text_list(must_visit))
            if normalized
        ]
        avoid = candidate.get("avoid", base.get("avoid", []))
        base["avoid"] = [
            normalized
            for normalized in (cls._normalize_avoid_item(item) for item in cls._coerce_text_list(avoid))
            if normalized
        ]
        if base["avoid"]:
            base["must_visit"] = [
                value
                for value in base["must_visit"]
                if not any(cls._preference_terms_conflict(value, avoid_item) for avoid_item in base["avoid"])
            ]

        for field in ("notes", "extra_request"):
            value = candidate.get(field, base.get(field, ""))
            base[field] = str(value or "").strip()

        return base

    @classmethod
    def _normalize_llm_understanding_payload(
        cls,
        payload: dict | None,
        *,
        default_city: str,
        stored_preferences: dict | None = None,
    ) -> TurnUnderstandingResult | None:
        if not payload:
            return None

        resolved_profile = cls._sanitize_resolved_profile(
            payload.get("resolved_profile"),
            default_city=default_city,
            stored_preferences=stored_preferences,
        )
        missing_slots = cls._order_profile_slots(payload.get("missing_profile_slots", []))
        needs_clarification = bool(payload.get("needs_clarification"))
        clarification_question = str(payload.get("clarification_question", "") or "").strip()
        overrides = payload.get("decomposition_overrides") or {}
        strategy_queries = cls._normalize_rag_queries(
            cls._coerce_text_list(overrides.get("strategy_queries", [])),
            resolved_profile["city"],
        )
        geo_queries = cls._dedupe_queries(
            [normalize_poi_display_name(item) for item in cls._coerce_text_list(overrides.get("geo_queries", [])) if normalize_poi_display_name(item)],
            limit=14,
        )
        strategy_queries = cls._filter_queries_against_avoid(strategy_queries, resolved_profile.get("avoid", []), limit=12)
        geo_queries = cls._filter_queries_against_avoid(geo_queries, resolved_profile.get("avoid", []), limit=14)
        planning_constraints = [str(item).strip() for item in cls._coerce_text_list(overrides.get("planning_constraints", [])) if str(item).strip()]

        return TurnUnderstandingResult(
            resolved_profile=resolved_profile,
            missing_profile_slots=missing_slots,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            decomposition_overrides={
                "strategy_queries": strategy_queries,
                "geo_queries": geo_queries,
                "planning_constraints": planning_constraints,
                "intent_summary": str(overrides.get("intent_summary", "") or "").strip(),
            },
            source="llm",
            raw_output=json.dumps(payload, ensure_ascii=False),
        )

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
    _AVOID_REASON_SUFFIX_PATTERNS: tuple[str, ...] = (
        r"(?:太累|太远|太贵|太挤|太热|太晒|太冷|太折腾|太麻烦|太费体力|人太多|排队太久|要排队|会很累|比较累|有点累).*$",
        r"(?:不方便|不适合带娃|不适合老人|不适合我).*$",
    )

    @classmethod
    def _is_noise_poi(cls, value: str) -> bool:
        for pattern in cls._NOISE_POI_PATTERNS:
            if re.search(pattern, value.strip(), flags=re.IGNORECASE):
                return True
        return False

    @classmethod
    def _normalize_poi_name(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        normalized = re.split(r"[，,；;。.!?\n]", normalized, maxsplit=1)[0].strip("，,；;、。.!？?：: ")
        normalized = re.sub(
            r"^(?:我)?(?:想去|要去|去|打卡|逛|安排去|必须去|一定要去|顺路去|然后去)\s*",
            "",
            normalized,
        ).strip("，,；;、。.!？?：: ")
        normalized = re.sub(r"(?:了|啦|呀|啊|呢|吧)$", "", normalized).strip("，,；;、。.!？?：: ")
        if cls._is_noise_poi(normalized):
            return ""
        return normalize_poi_display_name(normalized)

    @classmethod
    def _normalize_avoid_item(cls, value: str) -> str:
        normalized = str(value or "").strip().strip("，,；;、。.!？?：: ")
        if not normalized:
            return ""
        normalized = re.split(r"[，,；;。.!?\n]", normalized, maxsplit=1)[0].strip("，,；;、。.!？?：: ")
        normalized = re.sub(
            r"^(?:我)?(?:还是)?(?:先)?(?:不想|不太想|不喜欢|不爱|不要|别|避免|避开|排除|取消)\s*",
            "",
            normalized,
        ).strip("，,；;、。.!？?：: ")
        normalized = re.sub(r"^(?:去|安排|打卡|逛|看|玩|吃|爬|走|跑|坐|住)\s*", "", normalized).strip("，,；;、。.!？?：: ")
        for pattern in cls._AVOID_REASON_SUFFIX_PATTERNS:
            normalized = re.sub(pattern, "", normalized).strip("，,；;、。.!？?：: ")
        normalized = re.sub(r"(?:了|啦|呀|啊|呢|吧)$", "", normalized).strip("，,；;、。.!？?：: ")
        if cls._is_noise_poi(normalized):
            return ""
        if not normalized:
            return ""
        return normalize_poi_display_name(normalized)

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
        day_reference_prefixes = {"第", "这", "那", "哪", "某", "昨", "今", "明", "前", "后"}

        def _looks_like_day_reference(text: str, start: int) -> bool:
            if start <= 0:
                return False
            return text[start - 1] in day_reference_prefixes

        def _valid_days(value: int | None) -> int | None:
            if value is None:
                return None
            return value if 1 <= value <= 14 else None

        for trip_days_match in re.finditer(
            r"(\d+)\s*(?:-\s*)?(?:day|days|天|日)(?:\s*(?:trip|tour|itinerary|游|游玩|行程|路线))?",
            lower,
        ):
            if _looks_like_day_reference(lower, trip_days_match.start(1)):
                continue
            return _valid_days(int(trip_days_match.group(1)))

        for chinese_days_match in re.finditer(
            r"([一二两三四五六七八九十]{1,3})\s*(?:天|日)(?:\s*(?:游|游玩|行程|路线))?",
            user_request,
        ):
            if _looks_like_day_reference(user_request, chinese_days_match.start(1)):
                continue
            return _valid_days(cls.CHINESE_DAY_NUMBERS.get(chinese_days_match.group(1)))

        overnight_match = re.search(r"(\d+)\s*天\s*\d+\s*(?:晚|夜)", user_request)
        if overnight_match:
            return _valid_days(int(overnight_match.group(1)))

        chinese_overnight_match = re.search(
            r"([一二两三四五六七八九十]{1,3})\s*天\s*[一二两三四五六七八九十\d]+\s*(?:晚|夜)",
            user_request,
        )
        if chinese_overnight_match:
            return _valid_days(cls.CHINESE_DAY_NUMBERS.get(chinese_overnight_match.group(1)))

        if "weekend" in lower or "周末" in user_request:
            return 2

        # Infer days from holiday duration when user doesn't state days explicitly.
        holiday = cls._parse_holiday_date(user_request)
        if holiday:
            return holiday[1]

        return None

    @classmethod
    def _extract_user_profile(cls, user_request: str, default_city: str = "Hong Kong") -> dict:
        # Lightweight fallback only.
        # The LLM path should handle real semantic understanding; this path just
        # extracts a few explicit fields so the app still works without LLM creds.
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
    def _preference_terms_conflict(cls, left: str, right: str) -> bool:
        left_key = cls._normalize_avoid_item(left).lower()
        right_key = cls._normalize_avoid_item(right).lower()
        if not left_key or not right_key:
            return False
        return left_key in right_key or right_key in left_key

    @classmethod
    def _query_matches_avoid_item(cls, query: str, avoid_item: str) -> bool:
        query_key = normalize_poi_display_name(str(query or "").strip()).lower()
        avoid_key = cls._normalize_avoid_item(avoid_item).lower()
        if not query_key or not avoid_key:
            return False
        return cls._preference_terms_conflict(query_key, avoid_key)

    @classmethod
    def _filter_queries_against_avoid(cls, queries: list[str], avoid_items: list[str], limit: int = 12) -> list[str]:
        filtered = [
            query
            for query in queries
            if not any(cls._query_matches_avoid_item(query, avoid_item) for avoid_item in avoid_items)
        ]
        return cls._dedupe_queries(filtered, limit=limit)

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
    def _order_profile_slots(cls, slots: set[str] | list[str]) -> list[str]:
        slot_set = {slot for slot in slots if slot}
        return [slot for slot in cls.PROFILE_SLOT_ORDER if slot in slot_set]

    @classmethod
    def _build_clarification_question(
        cls,
        user_profile: dict,
        missing_profile_slots: list[str],
    ) -> str:
        active_slot = missing_profile_slots[0]
        if active_slot == "city":
            return "为了把攻略做准一点，我先确认一下目的地：你这次想去哪个城市？"
        if active_slot == "trip_days":
            return "这次大概玩几天？比如 2 天、3 天、5 天都可以。"
        if active_slot == "travel_style":
            return (
                "你更想走哪种路线？比如轻松逛、美食、亲子、主题体验；"
                "如果有特别想去的点，也可以直接告诉我。"
            )
        if active_slot == "budget_level":
            return "预算大概想走什么档位？低预算 / 中等 / 高预算 都可以。"
        if active_slot == "pace":
            return "行程节奏想轻松一点、适中，还是尽量排满？"

        return "有没有一定要去或想避开的地方？没有的话直接回复“没有”，我就开始生成完整攻略。"

    @classmethod
    def _infer_missing_profile_slots(
        cls,
        user_request: str,
        stored_preferences: dict | None = None,
    ) -> list[str]:
        # Fallback clarification policy.
        # If the LLM path is unavailable, we still prefer asking for key
        # preferences on the first turn instead of silently filling them all.
        if stored_preferences:
            return []

        missing: list[str] = []
        combined_text = user_request.lower() + user_request
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

        if not cls._extract_explicit_city(user_request):
            missing.append("city")
        if cls._parse_trip_days(user_request) is None:
            missing.append("trip_days")
        if not (
            cls._find_alias_group(combined_text, cls.TRAVEL_TYPE_ALIASES)
            or cls._extract_clause(user_request, "Interests")
            or any(alias in combined_text for aliases in cls.INTEREST_ALIASES.values() for alias in aliases)
            or must_visit_items
            or cls._extract_clause(user_request, "Must visit")
        ):
            missing.append("travel_style")
        if not cls._find_alias_group(combined_text, cls.BUDGET_ALIASES):
            missing.append("budget_level")
        if not cls._find_alias_group(combined_text, cls.PACE_ALIASES):
            missing.append("pace")
        if not (must_visit_items or avoid_items or cls._extract_clause(user_request, "Must visit") or cls._extract_clause(user_request, "Avoid")):
            missing.append("constraints")
        return cls._order_profile_slots(missing)

    @staticmethod
    def _empty_profile_updates() -> dict:
        return {
            "replace": {},
            "add": {"interests": [], "must_visit": [], "avoid": []},
            "remove": {"interests": [], "must_visit": [], "avoid": []},
            "append": {"notes": "", "extra_request": ""},
        }

    @classmethod
    def _normalize_updates_payload(cls, updates: dict | None) -> dict:
        normalized = cls._empty_profile_updates()
        if not updates:
            return normalized

        for field, value in (updates.get("replace") or {}).items():
            if value not in (None, "", []):
                normalized["replace"][field] = value
        for bucket in ("add", "remove"):
            bucket_values = updates.get(bucket) or {}
            for field in ("interests", "must_visit", "avoid"):
                values = bucket_values.get(field) or []
                if isinstance(values, str):
                    values = cls._split_csv(values)
                normalized[bucket][field].extend(str(item).strip() for item in values if str(item).strip())
        for field in ("notes", "extra_request"):
            value = str((updates.get("append") or {}).get(field, "") or "").strip()
            if value:
                normalized["append"][field] = value

        for field in ("interests", "must_visit", "avoid"):
            normalized["add"][field] = cls._dedupe_items(normalized["add"][field])
            normalized["remove"][field] = cls._dedupe_items(normalized["remove"][field])
        normalized["add"]["interests"] = [
            cls._normalize_interest_item(item) for item in normalized["add"]["interests"] if cls._normalize_interest_item(item)
        ]
        normalized["remove"]["interests"] = [
            cls._normalize_interest_item(item) for item in normalized["remove"]["interests"] if cls._normalize_interest_item(item)
        ]
        normalized["add"]["must_visit"] = [cls._normalize_poi_name(item) for item in normalized["add"]["must_visit"] if cls._normalize_poi_name(item)]
        normalized["add"]["avoid"] = [cls._normalize_avoid_item(item) for item in normalized["add"]["avoid"] if cls._normalize_avoid_item(item)]
        normalized["remove"]["must_visit"] = [
            cls._normalize_poi_name(item) for item in normalized["remove"]["must_visit"] if cls._normalize_poi_name(item)
        ]
        normalized["remove"]["avoid"] = [
            cls._normalize_avoid_item(item) for item in normalized["remove"]["avoid"] if cls._normalize_avoid_item(item)
        ]
        if "must_visit" in normalized["replace"]:
            value = normalized["replace"]["must_visit"]
            if isinstance(value, str):
                value = cls._split_csv(value)
            normalized["replace"]["must_visit"] = [
                cls._normalize_poi_name(item) for item in value if cls._normalize_poi_name(item)
            ]
        if "avoid" in normalized["replace"]:
            value = normalized["replace"]["avoid"]
            if isinstance(value, str):
                value = cls._split_csv(value)
            normalized["replace"]["avoid"] = [
                cls._normalize_avoid_item(item) for item in value if cls._normalize_avoid_item(item)
            ]
        if "interests" in normalized["replace"] and isinstance(normalized["replace"]["interests"], str):
            normalized["replace"]["interests"] = cls._split_csv(normalized["replace"]["interests"])
        if "interests" in normalized["replace"]:
            normalized["replace"]["interests"] = [
                cls._normalize_interest_item(item)
                for item in normalized["replace"]["interests"]
                if cls._normalize_interest_item(item)
            ]
        return normalized

    @classmethod
    def _extract_profile_updates(cls, user_request: str) -> dict:
        # Tiny offline fallback for multi-turn edits.
        # Keep only explicit updates here; deeper semantic interpretation should
        # come from the LLM understanding path.
        combined_text = user_request.lower() + user_request
        updates = cls._empty_profile_updates()

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

        interests_clause = cls._extract_clause(user_request, "Interests")
        if interests_clause:
            updates["replace"]["interests"] = cls._split_csv(interests_clause)

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
                    r"(?:不喜欢去|不想去|不爱去|不喜欢|不太喜欢|不爱)\s*[:：]?\s*(.+?)(?:[，,。.!?\n]|$)",
                    r"(?:不要安排|别安排|不想安排|不喜欢安排)\s*[:：]?\s*(.+?)(?:[，,。.!?\n]|$)",
                    r"(?:不想|不太想|别|不要)\s*(?:爬|逛|看|玩|吃|打卡|走|跑|坐|住)\s*[:：]?\s*(.+?)(?:[，,。.!?\n]|$)",
                ],
            )
        )

        return cls._normalize_updates_payload(updates)

    @staticmethod
    def _summarize_plan_for_intent_understanding(plan: dict | None) -> str:
        if not plan:
            return "暂无上一版行程。"
        lines: list[str] = []
        for day in plan.get("days", [])[:10]:
            stops = [item.get("poi_name", "") for item in day.get("items", []) if item.get("poi_name")]
            lines.append(
                f"第{day.get('day_index', '?')}天｜区域：{day.get('area', '')}｜主题：{day.get('theme', '')}｜点位：{'、'.join(stops[:6])}"
            )
        return "\n".join(lines) or "暂无上一版行程。"

    def _merge_preference_memory(
        self,
        preference_memory: dict,
        user_request: str,
    ) -> dict:
        # Fallback-only incremental merge.
        # In the normal path, the LLM already returns the fully resolved profile.
        merged = deepcopy(preference_memory)
        rule_updates = self._extract_profile_updates(user_request)
        updates = self._normalize_updates_payload(rule_updates)
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
            current_values = self._dedupe_items(list(merged.get(field, [])))
            removals = {value.lower() for value in updates["remove"].get(field, [])}
            if removals:
                current_values = [value for value in current_values if value.lower() not in removals]
            current_values.extend(updates["add"].get(field, []))
            merged[field] = self._dedupe_items(current_values)

        # Conflict resolution rule: avoid-list wins over must-visit to prevent unsafe plans.
        must_visit_keys = {value.lower() for value in merged.get("must_visit", [])}
        avoid_keys = {value.lower() for value in merged.get("avoid", [])}
        if must_visit_keys & avoid_keys:
            merged["must_visit"] = [
                value for value in merged.get("must_visit", []) if value.lower() not in avoid_keys
            ]

        if updates["append"]["notes"]:
            merged["notes"] = self._merge_text_field(merged.get("notes", ""), updates["append"]["notes"])
        if updates["append"]["extra_request"]:
            merged["extra_request"] = self._merge_text_field(
                merged.get("extra_request", ""),
                updates["append"]["extra_request"],
            )

        return self._sanitize_resolved_profile(
            merged,
            default_city=str(merged.get("city", "") or self.settings.default_city),
        )

    def _resolve_user_profile(
        self,
        user_request: str,
        *,
        default_city: str,
        stored_preferences: dict | None = None,
    ) -> dict:
        if stored_preferences:
            return self._merge_preference_memory(stored_preferences, user_request)
        base_profile = self._sanitize_resolved_profile(
            self._extract_user_profile(user_request, default_city=default_city),
            default_city=default_city,
        )
        return self._merge_preference_memory(base_profile, user_request)

    # --- LLM-first turn understanding --------------------------------------

    def _llm_understand_turn(
        self,
        *,
        user_request: str,
        default_city: str,
        stored_preferences: dict | None = None,
        latest_plan: dict | None = None,
    ) -> TurnUnderstandingResult | None:
        # Main understanding path.
        # The model receives the schema plus conversation context and returns a
        # single JSON object that already contains both the resolved profile and
        # the search/planning hints needed by downstream tools.
        if not self.settings.has_llm_credentials:
            return None

        try:
            client = self._ensure_response_client()
        except Exception:
            return None

        supported_cities = sorted(set(CITY_ALIASES.values()))
        import datetime as _dt
        today_iso = _dt.date.today().isoformat()
        messages = build_turn_understanding_messages(
            default_city=default_city,
            user_request=user_request,
            supported_cities=supported_cities,
            stored_preferences=stored_preferences,
            latest_plan_summary=self._summarize_plan_for_intent_understanding(latest_plan),
            today_iso=today_iso,
        )

        try:
            response = client.responses.create(
                model=self.model,
                input=messages,
            )
        except Exception:
            return None

        parsed = self._extract_json_object(getattr(response, "output_text", "") or "")
        understanding = self._normalize_llm_understanding_payload(
            parsed,
            default_city=default_city,
            stored_preferences=stored_preferences,
        )
        if understanding:
            understanding.raw_output = getattr(response, "output_text", "") or understanding.raw_output
        return understanding

    # --- Retrieval decomposition and orchestration -------------------------

    def _heuristic_understand_turn(
        self,
        *,
        user_request: str,
        default_city: str,
        stored_preferences: dict | None = None,
        latest_plan: dict | None = None,
    ) -> TurnUnderstandingResult:
        # Small offline fallback for environments without LLM credentials.
        # We keep it intentionally conservative instead of trying to replicate
        # the full semantic understanding logic with rules.
        resolved_profile = self._resolve_user_profile(
            user_request,
            default_city=default_city,
            stored_preferences=stored_preferences,
        )
        missing_profile_slots = self._infer_missing_profile_slots(
            user_request,
            stored_preferences=stored_preferences,
        )
        clarification_question = ""
        if missing_profile_slots:
            clarification_question = self._build_clarification_question(
                user_profile=resolved_profile,
                missing_profile_slots=missing_profile_slots,
            )

        city_context = get_city_context(resolved_profile["city"], resolved_profile["travel_type"])
        decomposition = self._decompose_request(user_request, resolved_profile, city_context=city_context)
        return TurnUnderstandingResult(
            resolved_profile=resolved_profile,
            missing_profile_slots=missing_profile_slots,
            needs_clarification=bool(missing_profile_slots),
            clarification_question=clarification_question,
            decomposition_overrides={
                "strategy_queries": decomposition.get("strategy_queries", []),
                "geo_queries": decomposition.get("geo_queries", []),
                "planning_constraints": decomposition.get("planning_constraints", []),
                "intent_summary": user_request.strip(),
            },
            source="heuristic",
            raw_output="",
        )

    def _understand_turn(
        self,
        *,
        user_request: str,
        default_city: str,
        stored_preferences: dict | None = None,
        latest_plan: dict | None = None,
    ) -> TurnUnderstandingResult:
        llm_result = self._llm_understand_turn(
            user_request=user_request,
            default_city=default_city,
            stored_preferences=stored_preferences,
            latest_plan=latest_plan,
        )
        if llm_result:
            return llm_result
        return self._heuristic_understand_turn(
            user_request=user_request,
            default_city=default_city,
            stored_preferences=stored_preferences,
            latest_plan=latest_plan,
        )

    @classmethod
    def _contains_chinese(cls, text: str) -> bool:
        return any("一" <= ch <= "鿿" for ch in text)

    @classmethod
    def _normalize_rag_queries(cls, queries: list[str], city: str) -> list[str]:
        normalized: list[str] = []
        for query in queries:
            normalized_query = normalize_rag_query_text(query)
            if not normalized_query:
                continue
            if cls._contains_chinese(normalized_query):
                normalized.append(normalized_query)
            # English-only queries are poor fits for the Chinese guide corpus.
            # Keep only those that become Chinese after normalization.
        return cls._dedupe_queries(normalized, limit=12)

    @classmethod
    def _build_strategy_queries(cls, user_profile: dict, city_context: dict | None = None) -> list[str]:
        # Fallback query builder only.
        # In the normal path the LLM already emits strategy_queries; here we only
        # provide a small amount of deterministic padding for sparse requests.
        queries: list[str] = []
        city = user_profile.get("city", "")
        rag_city = provider_city_name(city, "zh") or city
        for poi_name in user_profile.get("must_visit", []):
            if not poi_name:
                continue
            queries.append(poi_name)
            if rag_city and rag_city not in poi_name:
                queries.append(f"{rag_city} {poi_name}")
        if city_context:
            queries.extend(city_context.get("suggested_queries", [])[:4])
            if not user_profile.get("must_visit"):
                queries.extend(city_context.get("seed_poi_names", [])[:4])

        if city_context:
            recommended_areas = [item.get("name", "") for item in city_context.get("recommended_areas", []) if item.get("name")]
            queries.extend(recommended_areas[:3])

        return cls._filter_queries_against_avoid(
            cls._normalize_rag_queries(queries, city),
            user_profile.get("avoid", []),
            limit=12,
        )

    @classmethod
    def _build_decomposition(
        cls,
        *,
        user_request: str,
        user_profile: dict,
        city_context: dict | None = None,
        understanding: TurnUnderstandingResult | None = None,
    ) -> dict:
        # Prefer the model's structured decomposition output. Deterministic code
        # only fills essential gaps so downstream tool calls always have enough
        # input to run.
        city = user_profile["city"]
        rag_city = provider_city_name(city, "zh") or city
        combined_text = " ".join(
            part for part in [user_request, user_profile.get("notes", ""), user_profile.get("extra_request", "")] if part
        ).lower()
        overrides = understanding.decomposition_overrides if understanding else {}

        strategy_queries = cls._coerce_text_list(overrides.get("strategy_queries", []))
        geo_queries = [
            normalize_poi_display_name(item)
            for item in cls._coerce_text_list(overrides.get("geo_queries", []))
            if normalize_poi_display_name(item)
        ]
        planning_constraints = [
            str(item).strip()
            for item in cls._coerce_text_list(overrides.get("planning_constraints", []))
            if str(item).strip()
        ]

        if not strategy_queries:
            strategy_queries = cls._build_strategy_queries(user_profile, city_context)
            if user_profile["trip_days"] > 1:
                strategy_queries.append(f"{rag_city} {user_profile['trip_days']}天 行程")
            if user_profile["budget_level"] != "medium":
                strategy_queries.append(f"{rag_city} {user_profile['budget_level']} 预算 玩法")
        typed_strategy_queries = [
            f"{rag_city} {user_profile['trip_days']}天 路线 攻略",
            f"{rag_city} 本地人 推荐 小众",
            f"{rag_city} 旅游 避坑 排队 预约",
        ]
        if user_profile.get("travel_type") == "food" or any(
            "food" in str(item).lower() or "美食" in str(item) or "吃" in str(item)
            for item in user_profile.get("interests", [])
        ):
            typed_strategy_queries.append(f"{rag_city} 美食 小吃 本地推荐")
        if user_profile.get("travel_type") == "family":
            typed_strategy_queries.append(f"{rag_city} 亲子 轻松 路线")
        for query in typed_strategy_queries:
            if query not in strategy_queries:
                strategy_queries.append(query)

        if not geo_queries:
            geo_queries = list(user_profile.get("must_visit", []))
            provider_city = provider_city_name(city, "zh")
            geo_queries.extend(
                f"{provider_city} {poi_name}"
                for poi_name in user_profile.get("must_visit", [])
                if poi_name and provider_city and provider_city not in poi_name
            )
            if city_context:
                fallback_geo = city_context.get("seed_poi_names", [])[:4] or city_context.get("suggested_queries", [])[:4]
                if geo_queries:
                    geo_queries.extend(fallback_geo[: max(0, min(3, user_profile["trip_days"]))])
                else:
                    geo_queries.extend(fallback_geo)

        if not planning_constraints:
            planning_constraints = [
                f"Pace target: {user_profile['pace']}",
                f"Budget target: {user_profile['budget_level']}",
                f"Travel type: {user_profile['travel_type']}",
            ]
            if user_profile.get("must_visit"):
                planning_constraints.append(f"Must keep these if possible: {', '.join(user_profile['must_visit'])}")
            if user_profile.get("avoid"):
                planning_constraints.append(f"Avoid these places or patterns: {', '.join(user_profile['avoid'])}")
            if user_profile.get("extra_request"):
                planning_constraints.append(f"Extra request: {user_profile['extra_request']}")

        rain_sensitive = any(
            term in combined_text
            for term in ["rain", "rainy", "umbrella", "indoor", "下雨", "雨天", "室内"]
        )
        if rain_sensitive and not any("weather-safe" in item.lower() or "indoor" in item.lower() or "雨天" in item for item in strategy_queries):
            strategy_queries.append(f"{rag_city} 雨天 室内")
        if rain_sensitive and "Need indoor backups or weather-safe swaps." not in planning_constraints:
            planning_constraints.append("Need indoor backups or weather-safe swaps.")

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
            "strategy_queries": cls._filter_queries_against_avoid(
                cls._normalize_rag_queries(strategy_queries, city),
                user_profile.get("avoid", []),
                limit=14,
            ),
            "geo_queries": cls._filter_queries_against_avoid(geo_queries, user_profile.get("avoid", []), limit=14),
            "condition_queries": condition_queries,
            "planning_constraints": cls._dedupe_items(planning_constraints),
            "synthesis_goal": f"Produce one executable {user_profile['trip_days']}-day itinerary JSON for {city}.",
        }

    @classmethod
    def _decompose_request(
        cls,
        user_request: str,
        user_profile: dict,
        city_context: dict | None = None,
        understanding: TurnUnderstandingResult | None = None,
    ) -> dict:
        return cls._build_decomposition(
            user_request=user_request,
            user_profile=user_profile,
            city_context=city_context,
            understanding=understanding,
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
        evidence_by_poi = strategy_context.get("strategy_evidence_by_poi", {}) or {}
        for entries in evidence_by_poi.values():
            for evidence in entries[:1]:
                poi_name = str(evidence.get("poi_name", "")).strip()
                snippet = str(evidence.get("snippet", "")).strip()[:180]
                role = str(evidence.get("role", "")).strip()
                if not poi_name or not snippet or role in {"transit", "pitfall"}:
                    continue
                key = (poi_name.lower(), snippet.lower())
                if key not in existing_pairs:
                    merged["tips"].append(
                        {
                            "poi_name": poi_name,
                            "tip": snippet,
                            "source": evidence.get("source_title", ""),
                            "role": role,
                        }
                    )
                    existing_pairs.add(key)
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
        poi_roles = (strategy_context or {}).get("poi_roles", {}) or {}
        high_value_roles = {"anchor", "nearby_walk"}
        allow_food_strategy_pois = user_profile.get("travel_type") == "food" or "local food" in set(user_profile.get("interests", []))
        if allow_food_strategy_pois:
            high_value_roles.add("food")
        missing_strategy_queries = [
            poi_name
            for poi_name in (strategy_context or {}).get("recommended_pois", [])
            if poi_name.strip().lower() not in existing_names
            and poi_roles.get(poi_name.strip().lower(), "anchor") in high_value_roles
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
    def _render_budget_section(cost_summary: dict | None, budget_summary: dict, *, zh: bool = False) -> str:
        # Render an optional markdown budget block for final report.
        if not cost_summary:
            return ""

        totals = cost_summary.get("totals", {})
        budget_fit = cost_summary.get("budget_fit", {})
        breakdown = cost_summary.get("breakdown", {})
        if zh:
            lines = [
                "## 预算概览",
                f"- 行程总预算估算：¥ {totals.get('min', 0):.0f}-{totals.get('max', 0):.0f}",
                f"- 当前行程景点门票估算：¥ {budget_summary.get('estimated_core_attraction_cost', 0):.0f}",
            ]
        else:
            lines = [
                "## Budget Envelope",
                f"- Trip estimate: CNY {totals.get('min', 0):.0f}-{totals.get('max', 0):.0f}",
                f"- Attraction estimate in current itinerary: CNY {budget_summary.get('estimated_core_attraction_cost', 0):.0f}",
            ]
        if breakdown:
            hotel = breakdown.get("hotel_per_night", {})
            food = breakdown.get("food_per_day", {})
            transport = breakdown.get("local_transport_total", {})
            if zh:
                lines.extend(
                    [
                        f"- 酒店每晚参考：¥ {hotel.get('min', 0):.0f}-{hotel.get('max', 0):.0f}",
                        f"- 每日餐饮参考：¥ {food.get('min', 0):.0f}-{food.get('max', 0):.0f}",
                        f"- 当地交通参考：¥ {transport.get('min', 0):.0f}-{transport.get('max', 0):.0f}",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"- Hotel per night: CNY {hotel.get('min', 0):.0f}-{hotel.get('max', 0):.0f}",
                        f"- Food per day: CNY {food.get('min', 0):.0f}-{food.get('max', 0):.0f}",
                        f"- Local transport total: CNY {transport.get('min', 0):.0f}-{transport.get('max', 0):.0f}",
                    ]
                )
        if budget_fit.get("user_budget") is not None:
            lines.append(
                (
                    f"- 用户预算匹配：{'在预算内' if budget_fit.get('within_budget') else '高于当前完整方案预算'}"
                    if zh
                    else f"- User budget fit: {'within budget' if budget_fit.get('within_budget') else 'above full budget range'}"
                )
            )
            if budget_fit.get("minimum_feasible") and not budget_fit.get("within_budget"):
                lines.append(
                    "- 低配版本仍可行，但完整方案的上限会超过当前预算。"
                    if zh
                    else "- Minimum feasible version is possible, but the upper end exceeds the stated budget."
                )
        for note in cost_summary.get("pricing_notes", [])[:2]:
            localized_note = note
            if zh:
                localized_note = (
                    "当前预算只覆盖酒店、餐饮和本地交通。"
                    if note == "Budget currently covers hotel, food, and local transport only."
                    else (
                        "长途交通和景点门票暂未计入，除非后续有其他数据源补充。"
                        if note == "Long-haul flights and attraction tickets remain outside this estimate unless another provider adds them."
                        else note
                    )
                )
            lines.append(f"- {'说明' if zh else 'Note'}: {localized_note}")
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
    def _render_hotel_section(hotel_recommendations: dict | None, *, zh: bool = False) -> str:
        # Render concise markdown section with areas + top hotel candidates.
        if not hotel_recommendations:
            return ""
        lines = ["## 住宿建议" if zh else "## Stay Suggestions"]
        for area in hotel_recommendations.get("recommended_areas", [])[:3]:
            district_label = normalize_location_display_name(area.get("district", "Unknown")) if zh else area.get("district", "Unknown")
            reason = area.get("reason", "")
            if zh and reason == "Matches the itinerary's highest-frequency districts.":
                reason = "与当前行程最集中的活动片区最匹配。"
            lines.append(
                f"- {'区域' if zh else 'Area'}: {district_label} — {reason}"
            )
        for hotel in hotel_recommendations.get("hotel_candidates", [])[:3]:
            price_text = (
                f"CNY {float(hotel['min_price']):.0f}+"
                if hotel.get("min_price") is not None
                else "price unavailable"
            )
            district = hotel.get("district") or "Unknown district"
            lines.append(
                f"- {'酒店' if zh else 'Hotel'}: {hotel.get('name', 'Unknown')} ({normalize_location_display_name(district) if zh else district}, {price_text}, {'来源' if zh else 'source'}: {hotel.get('source', 'unknown')})"
            )
            if hotel.get("price_note"):
                lines.append(f"  {'说明' if zh else 'Note'}: {hotel['price_note']}")
        for note in hotel_recommendations.get("selection_notes", [])[:2]:
            localized_note = note
            if zh:
                if note == "Hotels are ranked by itinerary district match first, then by price visibility and source quality.":
                    localized_note = "酒店优先按和行程片区的匹配度排序，其次参考价格可见性和数据来源质量。"
                elif note.startswith("Current hotel budget reference is up to CNY "):
                    localized_note = note.replace("Current hotel budget reference is up to CNY ", "当前酒店预算参考上限约为每晚 ¥ ").replace(" per night.", "。")
                elif note == "No live hotel candidates were returned, so use the recommended areas as the fallback stay guide.":
                    localized_note = "当前没有拿到实时酒店候选，可先按推荐住宿区域作为备选。"
            lines.append(f"- {'说明' if zh else 'Note'}: {localized_note}")
        return "\n".join(lines)

    @staticmethod
    def _build_guide_references(strategy_context: dict | None) -> list[str]:
        # Extract a few short guide references that can later be shown directly
        # to the user as "why this route looks like this".
        if not strategy_context:
            return []
        references: list[str] = []
        for hint in strategy_context.get("route_pair_hints", [])[:3]:
            left = str(hint.get("from", "")).strip()
            right = str(hint.get("to", "")).strip()
            evidence = str(hint.get("evidence", "")).strip()
            if left and right and evidence:
                references.append(f"{left} - {right}: {evidence[:100]}")
        for chunk in strategy_context.get("evidence_chunks", [])[:3]:
            snippet = str(chunk.get("snippet", "")).strip()
            title = str(chunk.get("source_title", "")).strip()
            if snippet:
                references.append((f"{title}: " if title else "") + snippet[:110])
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
        deduped: list[str] = []
        seen: set[str] = set()
        for item in references:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped[:5]

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
        # Final deterministic assembly step after all upstream context is ready.
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
        tips = self._merge_strategy_into_travel_tips(
            tool_results["get_travel_tips"],
            strategy_context,
        )
        tool_results["get_travel_tips"] = tips
        trace_planner_input(strategy_context, len(poi_result.get("results", [])))
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
        plan["conditions_context"] = {
            "weather": weather,
            "cost_summary": cost_summary,
            "budget_summary": budget_summary,
        }
        plan["lodging_context"] = hotel_recommendations
        budget_section = self._render_budget_section(cost_summary, budget_summary, zh=True)
        hotel_section = self._render_hotel_section(hotel_recommendations, zh=True)
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
        stored_plan: dict | None = None,
        understanding: TurnUnderstandingResult | None = None,
    ) -> tuple[dict, dict, dict, str]:
        # End-to-end orchestration:
        # 1. understand the turn
        # 2. derive retrieval subtasks
        # 3. call deterministic tools
        # 4. hand everything to the planner/report renderer
        default_city = stored_preferences.get("city", self.settings.default_city) if stored_preferences else self.settings.default_city
        should_trace_understanding = understanding is None
        if should_trace_understanding:
            trace_session_start(user_request)
        if understanding is None:
            understanding = self._understand_turn(
                user_request=user_request,
                default_city=default_city,
                stored_preferences=stored_preferences,
                latest_plan=stored_plan,
            )
        user_profile = understanding.resolved_profile
        if should_trace_understanding:
            trace_turn_understanding(understanding)
            trace_profile(user_profile)
        city = user_profile["city"]
        _t0 = time.monotonic()
        city_context = get_city_context(city, user_profile["travel_type"])
        city_context_latency_ms = int((time.monotonic() - _t0) * 1000)
        decomposition = self._decompose_request(
            user_request,
            user_profile,
            city_context=city_context,
            understanding=understanding,
        )
        trace_decomposition(decomposition)
        tool_results: dict[str, object] = {
            "_logs": [
                {
                    "tool_name": "understand_turn",
                    "arguments": {"user_request": user_request, "source": understanding.source},
                    "result_preview": self._preview_tool_result(
                        {
                            "resolved_profile": user_profile,
                            "missing_profile_slots": understanding.missing_profile_slots,
                            "needs_clarification": understanding.needs_clarification,
                            "decomposition_overrides": understanding.decomposition_overrides,
                        }
                    ),
                },
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
            "_latencies": {"get_city_context": city_context_latency_ms},
            "get_city_context": city_context,
        }

        # Pre-fill all required tools deterministically to skip LLM tool-calling loop.
        strategy_queries = decomposition.get("strategy_queries") or [f"{city} {user_profile['travel_type']} itinerary"]
        geo_queries = decomposition.get("geo_queries") or [f"{city} landmark"]

        self._append_tool_log(
            tool_results,
            tool_name="get_city_context",
            arguments={"city": city, "travel_type": user_profile["travel_type"]},
            result=tool_results["get_city_context"],
        )
        trace_tool_call(
            "get_city_context",
            {"city": city, "travel_type": user_profile["travel_type"]},
            tool_results["get_city_context"],
        )
        strategy_query_batch = self._dedupe_queries(strategy_queries, limit=6)
        trace_rag_input(
            queries=strategy_query_batch,
            city=city,
            travel_type=user_profile["travel_type"],
            top_k=8,
        )
        _t0 = time.monotonic()
        tool_results["get_strategy_context"] = self._get_strategy_context(
            city=city,
            queries=strategy_query_batch,
            travel_type=user_profile["travel_type"],
            top_k=8,
        )
        self._record_tool_latency(tool_results, "get_strategy_context", _t0)
        self._append_tool_log(
            tool_results,
            tool_name="get_strategy_context",
            arguments={
                "city": city,
                "queries": strategy_query_batch,
                "travel_type": user_profile["travel_type"],
                "top_k": 8,
            },
            result=tool_results["get_strategy_context"],
        )
        trace_rag_output(tool_results["get_strategy_context"])
        _t0 = time.monotonic()
        tool_results["get_weather_forecast"] = self._get_weather_forecast(
            city=city,
            trip_days=user_profile["trip_days"],
            start_date=user_profile.get("start_date", ""),
        )
        self._record_tool_latency(tool_results, "get_weather_forecast", _t0)
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
        trace_tool_call(
            "get_weather_forecast",
            {
                "city": city,
                "trip_days": user_profile["trip_days"],
                "start_date": user_profile.get("start_date", ""),
            },
            tool_results["get_weather_forecast"],
        )
        geo_query_batch = self._dedupe_queries(geo_queries + user_profile.get("must_visit", []), limit=10)
        _t0 = time.monotonic()
        tool_results["search_batch_pois"] = self._search_batch_pois(
            city=city,
            queries=geo_query_batch,
            limit_per_query=3,
        )
        self._record_tool_latency(tool_results, "search_batch_pois", _t0)
        self._append_tool_log(
            tool_results,
            tool_name="search_batch_pois",
            arguments={
                "city": city,
                "queries": geo_query_batch,
                "limit_per_query": 3,
            },
            result=tool_results["search_batch_pois"],
        )
        trace_tool_call(
            "search_batch_pois",
            {"city": city, "queries": geo_query_batch, "limit_per_query": 3},
            tool_results["search_batch_pois"],
        )
        cost_user_budget = decomposition.get("condition_queries", {}).get("cost", {}).get("user_budget")
        _t0 = time.monotonic()
        tool_results["get_cost_summary"] = self._get_cost_summary(
            city=city,
            days=user_profile["trip_days"],
            budget_level=user_profile["budget_level"],
            user_budget=cost_user_budget,
        )
        self._record_tool_latency(tool_results, "get_cost_summary", _t0)
        self._append_tool_log(
            tool_results,
            tool_name="get_cost_summary",
            arguments={
                "city": city,
                "days": user_profile["trip_days"],
                "budget_level": user_profile["budget_level"],
                "user_budget": cost_user_budget,
            },
            result=tool_results["get_cost_summary"],
        )
        trace_tool_call(
            "get_cost_summary",
            {
                "city": city,
                "days": user_profile["trip_days"],
                "budget_level": user_profile["budget_level"],
                "user_budget": cost_user_budget,
            },
            tool_results["get_cost_summary"],
        )
        poi_names = [item["name"] for item in tool_results["search_batch_pois"].get("results", [])[:8]]
        _t0 = time.monotonic()
        tool_results["get_travel_tips"] = self._get_travel_tips(
            city=city,
            poi_names=poi_names,
            travel_type=user_profile["travel_type"],
            interests=user_profile.get("interests", []),
        )
        self._record_tool_latency(tool_results, "get_travel_tips", _t0)
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
        trace_tool_call(
            "get_travel_tips",
            {
                "city": city,
                "poi_names": poi_names,
                "travel_type": user_profile["travel_type"],
                "interests": user_profile.get("interests", []),
            },
            tool_results["get_travel_tips"],
        )
        self._append_latency_log(tool_results)
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
        trace_session_start(user_request, turn=(len(previous_state.turn_history) + 1 if previous_state else 1))
        stored_preferences = previous_state.preference_memory if previous_state else None
        default_city = (
            stored_preferences.get("city", self.settings.default_city)
            if stored_preferences
            else self.settings.default_city
        )
        understanding = self._understand_turn(
            user_request=user_request,
            default_city=default_city,
            stored_preferences=stored_preferences,
            latest_plan=previous_state.latest_plan if previous_state else None,
        )
        trace_turn_understanding(understanding)
        preview_profile = understanding.resolved_profile
        trace_profile(preview_profile)
        missing_profile_slots = understanding.missing_profile_slots
        confirmed_profile_slots = self._order_profile_slots(set(self.PROFILE_SLOT_ORDER) - set(missing_profile_slots))

        needs_clarification = bool(missing_profile_slots)

        if needs_clarification:
            question = self._build_clarification_question(
                user_profile=preview_profile,
                missing_profile_slots=missing_profile_slots,
            )
            tool_logs = [
                {
                    "tool_name": "understand_turn",
                    "arguments": {"user_request": user_request},
                    "result_preview": json.dumps(
                        {
                            "resolved_profile": preview_profile,
                            "confirmed_profile_slots": confirmed_profile_slots,
                            "missing_profile_slots": missing_profile_slots,
                            "follow_up_question": question,
                            "source": understanding.source,
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
            stored_plan=previous_state.latest_plan if previous_state else None,
            understanding=understanding,
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
