## author:SUN Bin
from __future__ import annotations

from dataclasses import dataclass
import json
from functools import lru_cache

from .config import Settings
from .models import TurnUnderstandingPayload, UserPreferences

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at import time
    OpenAI = None

"""Shared LLM utilities.

This module is the single place where we:
- create the OpenAI-compatible client
- derive compact schema text from Pydantic models
- build prompt messages for structured understanding tasks

The rest of the codebase should consume these helpers instead of assembling
large prompt strings inline.
"""


@dataclass(slots=True)
class ResponseClientBundle:
    """Minimal bundle containing the client object and chosen deployment name."""
    client: object
    model: str


def create_response_client(settings: Settings) -> ResponseClientBundle:
    """Build the response client used by agent orchestration and UI polishing."""
    if OpenAI is None:
        raise RuntimeError(
            "The `openai` package is not installed. Run `python3 -m pip install -r requirements.txt` first."
        )
    if not settings.has_llm_credentials:
        raise RuntimeError(
            "LLM credentials are incomplete. Please set FOUNDRY_PROJECT_RESOURCE, "
            "FOUNDRY_PROJECT_API_KEY, and FOUNDRY_PROJECT_DEPLOYMENT."
        )

    client = OpenAI(
        base_url=settings.azure_base_url,
        api_key=settings.foundry_api_key,
    )
    return ResponseClientBundle(client=client, model=settings.foundry_deployment)


@lru_cache(maxsize=1)
def _user_preferences_schema_text() -> str:
    # Convert the Pydantic model into a compact JSON schema snippet that can be
    # embedded directly into prompts.
    schema = UserPreferences.model_json_schema()
    return json.dumps(
        {
            "title": schema.get("title"),
            "type": schema.get("type"),
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
            "$defs": schema.get("$defs", {}),
        },
        ensure_ascii=False,
        indent=2,
    )


@lru_cache(maxsize=1)
def _turn_understanding_schema_text() -> str:
    # Same idea as above, but for the full turn-understanding payload.
    schema = TurnUnderstandingPayload.model_json_schema()
    return json.dumps(
        {
            "title": schema.get("title"),
            "type": schema.get("type"),
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
            "$defs": schema.get("$defs", {}),
        },
        ensure_ascii=False,
        indent=2,
    )


def build_turn_understanding_messages(
    *,
    default_city: str,
    user_request: str,
    supported_cities: list[str],
    stored_preferences: dict | None = None,
    latest_plan_summary: str = "",
    today_iso: str,
) -> list[dict[str, str]]:
    # Build the single structured-understanding prompt used by the agent.
    # We keep prompt construction here so agent.py stays focused on orchestration.
    is_first_turn = stored_preferences is None
    mode_instructions = (
        "这是首轮理解。请优先判断用户是否已经提供了足够完整的偏好信息。"
        "如果城市、天数、路线风格、预算、节奏、约束里有明显缺失，就先标记 missing_profile_slots，"
        "不要急着假设用户接受默认偏好。"
        if is_first_turn
        else "这是多轮理解。默认继承 stored_preferences，只修改用户这轮明确提到的字段。"
    )
    clarification_rules = (
        "首轮时，只要以下关键字段缺失就应该追问：city、trip_days、travel_style、budget_level、pace、constraints。"
        "resolved_profile 里可以保留 schema 默认值作为占位，但 missing_profile_slots 必须真实反映用户尚未提供的信息。"
        "当 missing_profile_slots 非空时，needs_clarification 设为 true。"
        if is_first_turn
        else "多轮通常不追问；只有用户明确说要改城市但没说目标城市时才追问。"
    )
    system_prompt = f"""你是旅行规划系统的对话理解器。今天日期：{today_iso}。

目标：理解用户自然语言，并输出一个严格符合 schema 的 JSON 对象。

行为原则：
- 优先做语义理解，不要机械依赖关键词。
- 用户表达负向偏好时，把核心对象放进 avoid，不要把整句抱怨或原因塞进地名。
- 如果用户说明了原因（例如太累、太远、太挤），可以写进 extra_request 或 planning_constraints。
- avoid 的优先级高于 must_visit；如果冲突，必须从 must_visit 移除。
- strategy_queries / geo_queries 只保留简短中文检索词，不要重复，也不要包含 avoid 项。
- 除非 clarification_rules 允许，否则不要主动追问。
- 首轮不要把“没说”当成“默认接受”。尤其是预算、节奏、路线风格和避坑要求，应优先追问。

当前模式：
- {mode_instructions}
- {clarification_rules}

可选城市：
{", ".join(supported_cities)}

resolved_profile schema：
{_user_preferences_schema_text()}

输出 schema：
{_turn_understanding_schema_text()}

只输出一个 JSON 对象，不要输出解释。"""

    user_payload = {
        "default_city": default_city,
        "supported_cities": supported_cities,
        "stored_preferences": stored_preferences or {},
        "latest_plan_summary": latest_plan_summary,
        "latest_user_message": user_request,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def build_user_report_polish_messages(*, raw_report: str, itinerary_json: dict) -> list[dict[str, str]]:
    # Shared prompt for turning a structured draft report into user-facing copy.
    return [
        {
            "role": "system",
            "content": (
                "你是一名旅行产品文案编辑。请把用户版行程说明润色成自然、统一、容易理解的简体中文。"
                "要求：1. 不要中英文混用，专有景点名尽量转成常见中文；"
                "2. 保留每天安排、天气、餐饮建议、攻略依据；"
                "3. 语气像真人推荐，不要太硬，不要过度营销；"
                "4. 不要使用 Markdown 标题或项目符号，输出 4 到 6 段自然短文即可。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"城市：{itinerary_json.get('city', '')}\n"
                f"天数：{itinerary_json.get('trip_days', '')}\n"
                f"请润色下面这段用户版说明：\n{raw_report}"
            ),
        },
    ]


def build_user_report_generation_messages(*, report_brief: dict) -> list[dict[str, str]]:
    # Preferred path for user-facing copy: the UI layer sends a structured brief
    # and the model turns it into natural Chinese prose.
    return [
        {
            "role": "system",
            "content": (
                "你是一名旅行产品文案编辑。"
                "请根据给定的结构化行程摘要，写出自然、统一、容易理解的简体中文用户版说明。"
                "要求："
                "1. 语气像真人推荐，不要机械复述字段名；"
                "2. 保留每天区域、核心点位、天气、攻略依据、预算/住宿提示；"
                "3. 不要瞎编不存在的信息；"
                "4. 不要输出 Markdown 标题或项目符号；"
                "5. 输出 4 到 6 段短文。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(report_brief, ensure_ascii=False),
        },
    ]
