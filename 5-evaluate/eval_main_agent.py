"""
主 Agent 三层评测整合脚本

用法:
    cd Travel_agent_7035
    # 全量跑三层（需要 LLM API Key）
    python 5-evaluate/eval_main_agent.py

    # 只跑层次一（意图理解，无 LLM 也可跑启发式路径）
    python 5-evaluate/eval_main_agent.py --layers 1

    # 只跑层次二（行程结构 assert，需要先提供 itinerary JSON）
    python 5-evaluate/eval_main_agent.py --layers 2 --itinerary-file path/to/itinerary.json

    # 只跑层次三（内容质量 Judge）
    python 5-evaluate/eval_main_agent.py --layers 3

    # 层次一限制条数
    python 5-evaluate/eval_main_agent.py --layers 1 --cases 10

    # 输出到指定文件
    python 5-evaluate/eval_main_agent.py --out results/eval_report.json

评测体系参考: 5-evaluate/框架-测评-主agent.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── 路径注入 ───────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
_PLANNER = _ROOT / "3-travel_planner"
for _p in [str(_ROOT), str(_PLANNER), str(_PLANNER / "travel_planner")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(override=False)

# ── LLM 客户端（层次三 Judge 用） ─────────────────────────────────────────────
try:
    from openai import AzureOpenAI, OpenAI
    _AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    _AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    _AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
    _AZURE_API_VER = os.getenv("AZURE_OPENAI_API_VERSION", "").strip()

    _FOUNDRY_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    _FOUNDRY_API_KEY = os.getenv("FOUNDRY_PROJECT_API_KEY", "").strip()
    _FOUNDRY_DEPLOYMENT = os.getenv("FOUNDRY_PROJECT_DEPLOYMENT", "").strip()
    _DEPLOYMENT = _AZURE_DEPLOYMENT or _FOUNDRY_DEPLOYMENT

    def _openai_compatible_base_url(endpoint: str) -> str:
        endpoint = endpoint.strip().rstrip("/")
        if endpoint.endswith("/openai/v1"):
            return f"{endpoint}/"
        if endpoint.endswith(".openai.azure.com"):
            return f"{endpoint}/openai/v1/"
        return f"{endpoint}/"

    def _make_llm_client():
        if _AZURE_ENDPOINT and _AZURE_API_KEY and _AZURE_DEPLOYMENT:
            return AzureOpenAI(
                azure_endpoint=_AZURE_ENDPOINT,
                api_key=_AZURE_API_KEY,
                api_version=_AZURE_API_VER or "2024-10-21",
            )
        if not (_FOUNDRY_ENDPOINT and _FOUNDRY_API_KEY and _FOUNDRY_DEPLOYMENT):
            raise RuntimeError(
                "缺少 LLM Judge 凭据，请在 .env 中设置 AZURE_OPENAI_* "
                "或 FOUNDRY_PROJECT_ENDPOINT / FOUNDRY_PROJECT_API_KEY / FOUNDRY_PROJECT_DEPLOYMENT"
            )
        return OpenAI(
            base_url=_openai_compatible_base_url(_FOUNDRY_ENDPOINT),
            api_key=_FOUNDRY_API_KEY,
        )
except ImportError:
    AzureOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore
    def _make_llm_client():
        raise RuntimeError("openai 包未安装")

# ── 测试集路径 ─────────────────────────────────────────────────────────────────
_EVAL_DIR    = _ROOT / "5-evaluate"
_L1_TEST     = _EVAL_DIR / "test_intent_understanding.json"
_L3_TEST     = _EVAL_DIR / "test_content_quality.json"
_MAX_DISTRICTS_PER_DAY = 3

# ═══════════════════════════════════════════════════════════════════════════════
# 层次一：意图理解测评
# ═══════════════════════════════════════════════════════════════════════════════

# 槽位权重（与框架文档一致）
_SLOT_WEIGHTS = {
    "city":         1.0,
    "trip_days":    1.0,
    "travel_type":  1.0,
    "budget_level": 0.5,
    "pace":         0.5,
    "must_visit":   0.5,
    "avoid":        0.5,
}


def _score_slot(slot: str, predicted: Any, expected: Any) -> float:
    """单槽位打分：1.0 正确，0.0 错误。列表槽位全对才给分。"""
    if expected is None:
        return 1.0  # 无 golden 值，跳过

    if slot in ("must_visit", "avoid"):
        # 列表全对才给分（顺序不敏感，忽略大小写）
        pred_set = {str(v).strip().lower() for v in (predicted or [])}
        exp_set  = {str(v).strip().lower() for v in (expected or [])}
        return 1.0 if pred_set == exp_set else 0.0

    if slot == "city":
        return 1.0 if str(predicted or "").strip().lower() == str(expected or "").strip().lower() else 0.0

    if slot == "trip_days":
        try:
            return 1.0 if int(predicted) == int(expected) else 0.0
        except (TypeError, ValueError):
            return 0.0

    # 枚举槽位（travel_type / budget_level / pace）
    return 1.0 if str(predicted or "").strip().lower() == str(expected or "").strip().lower() else 0.0


def _weighted_accuracy(slot_scores: dict[str, float]) -> float:
    """加权准确率 = Σ(weight × score) / Σ weight"""
    total_weight = 0.0
    total_score  = 0.0
    for slot, weight in _SLOT_WEIGHTS.items():
        if slot in slot_scores:
            total_weight += weight
            total_score  += weight * slot_scores[slot]
    return total_score / total_weight if total_weight > 0 else 0.0


def _call_agent_understand(
    user_request: str,
    use_llm: bool,
    stored_preferences: dict | None = None,
) -> dict:
    """调用主 agent 的意图理解路径，返回 resolved_profile dict。"""
    try:
        from travel_planner.agent import TravelPlanningAgent
        from travel_planner.config import Settings

        settings = Settings()
        agent = TravelPlanningAgent(settings=settings)

        default_city = (stored_preferences or {}).get("city") or settings.default_city or "Hong Kong"
        if use_llm:
            result = agent._llm_understand_turn(
                user_request=user_request,
                default_city=default_city,
                stored_preferences=stored_preferences,
            )
            if result is None:
                return {"_error": "LLM understanding returned None; check credentials/API availability"}
        else:
            result = agent._heuristic_understand_turn(
                user_request=user_request,
                default_city=default_city,
                stored_preferences=stored_preferences,
            )

        if result is None:
            return {}
        return result.resolved_profile or {}
    except Exception as exc:
        return {"_error": str(exc)}


def _flatten_l1_cases(test_data: dict) -> list[dict]:
    """将 categories[].cases[] 结构展平为带 category 字段的列表。"""
    flat = []
    categories = test_data.get("categories", [])
    if isinstance(categories, list):
        for cat in categories:
            cat_id = cat.get("id", "unknown")
            for case in cat.get("cases", []):
                c = dict(case)
                c.setdefault("category", cat_id)
                flat.append(c)
    # 兼容旧格式 test_cases
    flat.extend(test_data.get("test_cases", []))
    return flat


def _score_l1_prediction(predicted: dict, expected: dict) -> tuple[dict[str, float], float]:
    """对单条 expected/predicted 槽位结果打分。"""
    slot_scores = {}
    for slot in _SLOT_WEIGHTS:
        if slot in expected:
            slot_scores[slot] = _score_slot(slot, predicted.get(slot), expected[slot])
    return slot_scores, _weighted_accuracy(slot_scores)


def run_layer1(test_data: dict, use_llm: bool, max_cases: int | None) -> dict:
    """运行层次一：意图理解测评。"""
    cases = _flatten_l1_cases(test_data)
    if max_cases:
        cases = cases[:max_cases]

    results = []
    category_stats: dict[str, list[float]] = {}
    path_label = "LLM" if use_llm else "heuristic"

    print(f"\n{'='*60}")
    print(f"层次一：意图理解测评（路径={path_label}，共 {len(cases)} 条）")
    print(f"{'='*60}")

    for i, case in enumerate(cases):
        case_id      = case.get("id", f"case_{i+1}")
        category     = case.get("category", "unknown")

        if "turns" in case:
            stored_preferences = None
            turns = case.get("turns", [])
            print(f"  [{i+1}/{len(cases)}] {case_id} 多轮 case，共 {len(turns)} 轮")

            for turn in turns:
                turn_no = turn.get("turn")
                turn_id = f"{case_id}_turn_{turn_no}"
                user_request = turn.get("user_request", "")
                expected = turn.get("expected_after_turn", {})
                predicted = _call_agent_understand(
                    user_request,
                    use_llm,
                    stored_preferences=stored_preferences,
                )

                if "_error" in predicted:
                    print(f"    [turn {turn_no}] ERROR: {predicted['_error']}")
                    row = {
                        "id": turn_id,
                        "conversation_id": case_id,
                        "turn": turn_no,
                        "category": category,
                        "user_request": user_request,
                        "weighted_accuracy": 0.0,
                        "slot_scores": {},
                        "predicted": predicted,
                        "expected": expected,
                        "error": predicted["_error"],
                    }
                    results.append(row)
                    continue

                stored_preferences = predicted
                slot_scores, acc = _score_l1_prediction(predicted, expected)
                category_stats.setdefault(category, []).append(acc)

                pass_mark = "[PASS]" if acc >= 0.85 else "[FAIL]"
                print(f"    [turn {turn_no}] {pass_mark}  acc={acc:.2f}  {user_request[:40]}")
                row = {
                    "id": turn_id,
                    "conversation_id": case_id,
                    "turn": turn_no,
                    "category": category,
                    "user_request": user_request,
                    "weighted_accuracy": round(acc, 4),
                    "slot_scores": slot_scores,
                    "predicted": predicted,
                    "expected": expected,
                }
                results.append(row)
            continue

        user_request = case.get("user_request", "")
        expected     = case.get("expected", {})

        predicted = _call_agent_understand(user_request, use_llm)
        if "_error" in predicted:
            print(f"  [{i+1}/{len(cases)}] {case_id} ERROR: {predicted['_error']}")
            results.append({
                "id": case_id, "category": category,
                "user_request": user_request,
                "weighted_accuracy": 0.0,
                "slot_scores": {}, "predicted": predicted, "expected": expected,
                "error": predicted["_error"],
            })
            continue

        slot_scores, acc = _score_l1_prediction(predicted, expected)
        category_stats.setdefault(category, []).append(acc)

        pass_mark = "[PASS]" if acc >= 0.85 else "[FAIL]"
        print(f"  [{i+1}/{len(cases)}] {case_id} {pass_mark}  acc={acc:.2f}  {user_request[:40]}")

        results.append({
            "id": case_id, "category": category,
            "user_request": user_request,
            "weighted_accuracy": round(acc, 4),
            "slot_scores": slot_scores,
            "predicted": predicted,
            "expected": expected,
        })

    overall_acc = sum(r["weighted_accuracy"] for r in results) / len(results) if results else 0.0
    pass_count  = sum(1 for r in results if r["weighted_accuracy"] >= 0.85)

    print(f"\n  整体加权准确率: {overall_acc:.3f}  ({pass_count}/{len(results)} 条 ≥ 0.85)")
    for cat, scores in sorted(category_stats.items()):
        print(f"  {cat}: avg={sum(scores)/len(scores):.3f}  n={len(scores)}")

    return {
        "layer": 1,
        "path": path_label,
        "total_cases": len(results),
        "top_level_cases": len(cases),
        "overall_accuracy": round(overall_acc, 4),
        "pass_count": pass_count,
        "pass_threshold": 0.85,
        "passed": overall_acc >= 0.85,
        "category_stats": {k: round(sum(v)/len(v), 4) for k, v in category_stats.items()},
        "cases": results,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 层次二：行程结构验证（确定性 Python assert）
# ═══════════════════════════════════════════════════════════════════════════════

def _check_must_visit_completeness(profile: dict, itinerary: dict) -> tuple[bool, str]:
    """must_visit 里所有 POI 均出现在 selected_pois 中。"""
    must_visit  = [v.lower() for v in profile.get("must_visit", [])]
    selected    = [p.get("name", "").lower() for p in itinerary.get("selected_pois", [])]
    missing     = [v for v in must_visit if not any(v in s or s in v for s in selected)]
    ok = len(missing) == 0
    msg = "PASS" if ok else f"FAIL: 缺少 must_visit POI {missing}"
    return ok, msg


def _check_avoid_filter(profile: dict, itinerary: dict) -> tuple[bool, str]:
    """avoid 里任何 POI 均不出现在任意 DayPlan.items 中（优先级高于 must_visit）。"""
    avoid_list = [v.lower() for v in profile.get("avoid", [])]
    violations = []
    for day in itinerary.get("days", []):
        for item in day.get("items", []):
            poi_name = item.get("poi_name", "").lower()
            for av in avoid_list:
                if av in poi_name or poi_name in av:
                    violations.append(f"Day{day.get('day_index')} {item.get('poi_name')}")
    ok = len(violations) == 0
    msg = "PASS" if ok else f"FAIL: avoid POI 出现在行程 {violations}"
    return ok, msg


def _check_cross_district(itinerary: dict) -> tuple[bool, str]:
    """每天 DayPlanItem 所属 district 去重后 ≤ MAX_DISTRICTS_PER_DAY（=3）。"""
    violations = []
    for day in itinerary.get("days", []):
        districts = list({item.get("district", "Unknown") for item in day.get("items", [])})
        if len(districts) > _MAX_DISTRICTS_PER_DAY:
            violations.append(f"Day{day.get('day_index')}: {districts}")
    ok = len(violations) == 0
    msg = "PASS" if ok else f"FAIL: 跨区超限 {violations}"
    return ok, msg


def _check_daily_poi_count(itinerary: dict) -> tuple[bool, str]:
    """每个 DayPlan.items 长度 ≤ 5。"""
    violations = []
    for day in itinerary.get("days", []):
        n = len(day.get("items", []))
        if n > 5:
            violations.append(f"Day{day.get('day_index')}: {n} 个 POI")
    ok = len(violations) == 0
    msg = "PASS" if ok else f"FAIL: 单日 POI 超限 {violations}"
    return ok, msg


def _check_field_completeness(itinerary: dict) -> tuple[bool, str]:
    """每个 DayPlan 的 theme / area / estimated_cost 均非空。"""
    violations = []
    for day in itinerary.get("days", []):
        idx = day.get("day_index", "?")
        for field in ("theme", "area", "estimated_cost"):
            val = day.get(field)
            if val is None or str(val).strip() == "":
                violations.append(f"Day{idx}.{field} 缺失")
    ok = len(violations) == 0
    msg = "PASS" if ok else f"FAIL: 字段缺失 {violations}"
    return ok, msg


def _check_day_count(profile: dict, itinerary: dict) -> tuple[bool, str]:
    """len(itinerary.days) == profile.trip_days。"""
    expected_days = int(profile.get("trip_days", 0))
    actual_days   = len(itinerary.get("days", []))
    ok = (expected_days == actual_days)
    msg = "PASS" if ok else f"FAIL: 期望 {expected_days} 天，实际 {actual_days} 天"
    return ok, msg


def _run_structure_checks(profile: dict, itinerary: dict) -> dict:
    """运行全部 6 项结构验证，返回汇总结果。"""
    checks = {
        "must_visit_completeness": _check_must_visit_completeness(profile, itinerary),
        "avoid_filter":            _check_avoid_filter(profile, itinerary),
        "cross_district_limit":    _check_cross_district(itinerary),
        "daily_poi_count":         _check_daily_poi_count(itinerary),
        "field_completeness":      _check_field_completeness(itinerary),
        "day_count_match":         _check_day_count(profile, itinerary),
    }
    results = {k: {"passed": v[0], "message": v[1]} for k, v in checks.items()}
    all_passed = all(v[0] for v in checks.values())
    return {"all_passed": all_passed, "checks": results}


def _profile_for_layer2(payload: dict, itinerary: dict) -> dict:
    """从响应 payload 中取 profile；裸 itinerary JSON 则用 trip_days 兜底。"""
    profile = payload.get("user_profile") or payload.get("profile") or {}
    profile = dict(profile) if isinstance(profile, dict) else {}
    profile.setdefault("trip_days", itinerary.get("trip_days", len(itinerary.get("days", []))))
    profile.setdefault("must_visit", [])
    profile.setdefault("avoid", [])
    return profile


def run_layer2(itinerary_file: str | None) -> dict:
    """运行层次二：行程结构验证。"""
    print(f"\n{'='*60}")
    print("层次二：行程结构验证（确定性 Python assert）")
    print(f"{'='*60}")

    if not itinerary_file:
        # 尝试从 eval_trace.jsonl 提取最新一条行程（仅用于演示）
        trace_path = _EVAL_DIR / "eval_trace.jsonl"
        if not trace_path.exists():
            print("  [WARN]  未提供 --itinerary-file，且找不到 eval_trace.jsonl，跳过层次二")
            return {"layer": 2, "skipped": True, "reason": "无行程 JSON 可验证"}

        records = []
        with open(trace_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        # 找有 itinerary_json 字段的记录
        itinerary_records = [r for r in records if "itinerary_json" in r and r["itinerary_json"]]
        if not itinerary_records:
            print("  [WARN]  eval_trace.jsonl 中没有 itinerary_json，跳过层次二")
            print("  提示：用 --itinerary-file 直接传入行程 JSON 文件")
            return {"layer": 2, "skipped": True, "reason": "eval_trace 无 itinerary_json 字段"}

        record    = itinerary_records[-1]
        itinerary = record["itinerary_json"]
        profile   = _profile_for_layer2(record, itinerary)
        source    = "eval_trace.jsonl（最新条）"
    else:
        with open(itinerary_file, encoding="utf-8-sig") as f:
            data = json.load(f)
        # 支持直接传行程 JSON、包含 itinerary_json 的响应，或 profile + itinerary 的字典
        if "itinerary_json" in data:
            itinerary = data["itinerary_json"]
            profile   = _profile_for_layer2(data, itinerary)
        elif "itinerary" in data:
            itinerary = data["itinerary"]
            profile   = _profile_for_layer2(data, itinerary)
        else:
            itinerary = data
            profile   = _profile_for_layer2(data, itinerary)
        source = itinerary_file

    print(f"  数据来源: {source}")
    result = _run_structure_checks(profile, itinerary)

    for check_name, check_result in result["checks"].items():
        mark = "[OK]" if check_result["passed"] else "[FAIL]"
        print(f"  {mark} {check_name}: {check_result['message']}")

    overall_mark = "[全部通过]" if result["all_passed"] else "[存在失败]"
    print(f"\n  结构验证结果: {overall_mark}")

    return {
        "layer": 2,
        "source": source,
        "all_passed": result["all_passed"],
        "passed": result["all_passed"],
        "checks": result["checks"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 层次三：内容质量评测（Claude Sonnet Judge）
# ═══════════════════════════════════════════════════════════════════════════════

_DIMENSION_RUBRICS = {
    "主题匹配度": """1分：行程与用户旅行类型完全背离（如亲子游无一儿童友好场所，美食游无本地餐厅）
2分：仅有少量（<30%）POI 与旅行类型相关，大多数是通用景区堆砌
3分：约一半 POI 符合主题，但缺乏连贯性，主题感不强
4分：大多数（>70%）POI 与旅行类型高度相关，有主题贯穿
5分：全程 POI 均高度契合旅行类型，且主题在每日行程的 theme 字段中有清晰表达""",

    "路线合理性": """1分：同天行程跨越城市多个方向，需要大量重复来回，时间严重浪费
2分：同天存在明显绕路（如上午北部、下午南部、晚上再回北部）
3分：基本在同一区域，但存在 1-2 处不合理跳转，影响体验
4分：每天 POI 地理上聚集，跨区移动合理且有明确原因
5分：每天形成清晰的空间动线（如由西向东推进），移动高效，无冗余跳转""",

    "内容本地化程度": """1分：全是泛化景区介绍，无任何本地特色信息或实用 tips
2分：仅有极少量本地信息（1-2条），大量内容可套用于任何城市
3分：有一定本地特色，但 tips 较浅（如"这里很热闹"），缺乏具体实用信息
4分：包含本地化的具体建议（如最佳入园时间、避坑点、本地人常去的地方）
5分：行程充满在地知识：具体路线建议、本地餐厅而非景区餐厅、时段建议、游客常踩的坑及规避方法""",

    "用户偏好满足率": """1分：must_visit 有遗漏 或 avoid 里的 POI 出现在行程中（硬规则违反）
2分：must_visit 全部保留，但 pace / budget 与用户要求明显不符
3分：核心偏好满足，但节奏或预算匹配有明显偏差（如慢节奏用户每天塞 5 个景点）
4分：所有槽位偏好均有体现，仅有细节上的小偏差
5分：用户所有显式和隐式偏好均被精准满足，且报告中有主动说明如何照顾这些偏好""",
}

_JUDGE_PROMPT_TEMPLATE = """你是一位拥有10年经验的资深旅行体验规划师，以严谨、挑剔、注重细节著称。你现在需要作为"行程质量评审员"，对一份 AI 生成的旅行行程进行客观、严苛的打分。

### 评审任务
你需要独立评估该行程在【{dimension_name}】这一单一维度的表现。

### 用户原始需求与画像
- 原始请求: "{user_request}"
- 提取槽位: 城市={city}, 旅行类型={travel_type}, 偏好节奏={pace}, 必去={must_visit}, 避开={avoid}, 预算等级={budget_level}

### 行程报告
<itinerary_report>
{markdown_report}
</itinerary_report>

### 【{dimension_name}】评分标准 (1-5分)
{dimension_specific_rubric}

### 评审要求 (非常重要)
1. 你必须严格遵循上述 1-5 分的评分标准，不要做"老好人"，如果表现平庸请果断给 2 分或 3 分。
2. 分析时，必须引用行程报告中的具体地点 (POI)、时间安排或具体描述作为证据。
3. 请先进行详尽的步骤分析（包含优点、缺点、证据引用），最后再给出最终得分。

### 输出格式
必须输出合法的 JSON 格式，包含以下字段：
{{
  "analysis_steps": [
    "步骤1：验证用户需求的提取与匹配程度...",
    "步骤2：寻找行程中的具体证据支持...",
    "步骤3：对照评分标准确定最终扣分点..."
  ],
  "evidence_cited": ["引用报告中的原话1", "引用报告中的原话2"],
  "reason": "综合以上分析的最终评分理由总结（100字以内）",
  "score": int (1到5的整数)
}}"""


def _call_judge(
    client,
    dimension_name: str,
    user_request: str,
    profile: dict,
    markdown_report: str,
) -> dict:
    """调用 LLM Judge 对单一维度打分，返回解析后的结果 dict。"""
    rubric = _DIMENSION_RUBRICS[dimension_name]
    prompt = _JUDGE_PROMPT_TEMPLATE.format(
        dimension_name=dimension_name,
        user_request=user_request,
        city=profile.get("city", ""),
        travel_type=profile.get("travel_type", ""),
        pace=profile.get("pace", ""),
        must_visit="、".join(profile.get("must_visit", [])) or "无",
        avoid="、".join(profile.get("avoid", [])) or "无",
        budget_level=profile.get("budget_level", ""),
        markdown_report=markdown_report,
        dimension_specific_rubric=rubric,
    )

    try:
        response = client.chat.completions.create(
            model=_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=3000,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""

        # 提取 JSON
        json_match = re.search(r"\{[\s\S]+\}", raw)
        if not json_match:
            return {"error": "无法提取 JSON", "raw": raw, "score": None}

        parsed = json.loads(json_match.group(0))
        score = parsed.get("score")
        if not isinstance(score, int) or score not in range(1, 6):
            try:
                score = int(str(score).strip())
            except Exception:
                score = None
        parsed["score"] = score
        return parsed

    except Exception as exc:
        return {"error": str(exc), "score": None}


def run_layer3(test_data: dict, max_cases: int | None) -> dict:
    """运行层次三：内容质量 Judge 评测。"""
    print(f"\n{'='*60}")
    print("层次三：内容质量评测（LLM Judge）")
    print(f"{'='*60}")

    try:
        client = _make_llm_client()
    except RuntimeError as e:
        print(f"  [FAIL] 无法初始化 LLM 客户端: {e}")
        return {"layer": 3, "skipped": True, "reason": str(e)}

    pairs = test_data.get("contrast_pairs", [])
    if max_cases:
        pairs = pairs[:max_cases]

    all_pair_results = []
    dimensions = list(_DIMENSION_RUBRICS.keys())
    total_calls = 0
    start_ts = time.time()

    for pair_i, pair in enumerate(pairs):
        pair_id      = pair.get("pair_id") or pair.get("id") or f"pair_{pair_i+1}"
        user_request = pair.get("user_request", "")
        profile      = pair.get("profile", {})
        focus_dim    = pair.get("dimension_focus") or pair.get("focus_dimension", "")
        reports_root = pair.get("reports") if isinstance(pair.get("reports"), dict) else pair

        print(f"\n  对照组 [{pair_i+1}/{len(pairs)}]: {pair_id}  ({focus_dim})")
        print(f"  请求: {user_request[:50]}")

        pair_result = {
            "pair_id": pair_id,
            "user_request": user_request,
            "dimension_focus": focus_dim,
            "reports": {},
        }

        for report_key in ("high_quality", "low_quality"):
            report_obj     = reports_root.get(report_key, {})
            markdown_report = report_obj.get("markdown_report", "")
            expected_range  = report_obj.get("expected_score_range", [1, 5])
            dim_results     = {}

            if not markdown_report.strip():
                print(f"    [FAIL] {report_key}: markdown_report 为空，跳过 Judge")
                pair_result["reports"][report_key] = {
                    "dimension_scores": {},
                    "avg_score": None,
                    "expected_range": expected_range,
                    "in_expected_range": False,
                    "hard_fail": True,
                    "error": "empty markdown_report",
                }
                continue

            print(f"    [{report_key}] 开始 Judge ({len(dimensions)} 维度)...")

            for dim in dimensions:
                result = _call_judge(client, dim, user_request, profile, markdown_report)
                total_calls += 1
                score = result.get("score")
                dim_results[dim] = {
                    "score": score,
                    "reason": result.get("reason", ""),
                    "error": result.get("error"),
                    "analysis_steps": result.get("analysis_steps", []),
                    "evidence_cited": result.get("evidence_cited", []),
                }

                mark = "[OK]" if score is not None else "[FAIL]"
                print(f"      {mark} {dim}: {score}分  {result.get('reason', '')[:40]}")

            # 计算均分 & 是否在期望区间
            scores = [v["score"] for v in dim_results.values() if isinstance(v["score"], int)]
            avg_score = round(sum(scores) / len(scores), 2) if scores else None
            in_range = (
                expected_range[0] <= avg_score <= expected_range[1]
                if avg_score is not None else False
            )
            hard_fail = any(isinstance(v["score"], int) and v["score"] <= 1 for v in dim_results.values()) if report_key == "high_quality" else False

            pair_result["reports"][report_key] = {
                "dimension_scores": dim_results,
                "avg_score": avg_score,
                "expected_range": expected_range,
                "in_expected_range": in_range,
                "hard_fail": hard_fail,
            }

            range_mark = "[OK]" if in_range else "[WARN]"
            print(f"    {range_mark} {report_key}: avg={avg_score}  期望={expected_range}")

        # 对照验证：高质量均分 > 低质量均分
        hq_avg = pair_result["reports"]["high_quality"].get("avg_score")
        lq_avg = pair_result["reports"]["low_quality"].get("avg_score")
        contrast_ok = (hq_avg is not None and lq_avg is not None and hq_avg > lq_avg)
        hq_hard_fail = bool(pair_result["reports"]["high_quality"].get("hard_fail"))
        lq_detected = (lq_avg is not None and lq_avg <= 2.5)
        pair_result["contrast_valid"] = contrast_ok
        pair_result["high_quality_pass"] = (hq_avg is not None and hq_avg >= 3.5 and not hq_hard_fail)
        pair_result["low_quality_detected"] = lq_detected
        pair_result["passed"] = bool(pair_result["high_quality_pass"] and contrast_ok and lq_detected)
        print(f"    {'[OK]' if contrast_ok else '[FAIL]'} 对照有效: HQ({hq_avg}) > LQ({lq_avg})")

        all_pair_results.append(pair_result)

    # 汇总
    elapsed = time.time() - start_ts
    valid_contrasts = sum(1 for p in all_pair_results if p.get("contrast_valid"))
    hq_avgs = [p["reports"]["high_quality"]["avg_score"] for p in all_pair_results
                if p["reports"]["high_quality"].get("avg_score") is not None]
    lq_avgs = [p["reports"]["low_quality"]["avg_score"] for p in all_pair_results
                if p["reports"]["low_quality"].get("avg_score") is not None]

    overall_hq = round(sum(hq_avgs) / len(hq_avgs), 3) if hq_avgs else None
    overall_lq = round(sum(lq_avgs) / len(lq_avgs), 3) if lq_avgs else None
    pass_l3 = (overall_hq is not None and overall_hq >= 3.5
               and valid_contrasts == len(all_pair_results)
               and all(p.get("passed") for p in all_pair_results))

    print(f"\n  层次三汇总: HQ均分={overall_hq}  LQ均分={overall_lq}")
    print(f"  对照有效率: {valid_contrasts}/{len(all_pair_results)}")
    print(f"  总 Judge 调用: {total_calls}  耗时: {elapsed:.1f}s")
    print(f"  Pass 判定 (HQ≥3.5 & 对照全部有效): {'[OK]' if pass_l3 else '[FAIL]'}")

    return {
        "layer": 3,
        "total_pairs": len(pairs),
        "total_judge_calls": total_calls,
        "elapsed_seconds": round(elapsed, 1),
        "overall_hq_avg": overall_hq,
        "overall_lq_avg": overall_lq,
        "valid_contrasts": valid_contrasts,
        "passed": pass_l3,
        "pairs": all_pair_results,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 整合入口
# ═══════════════════════════════════════════════════════════════════════════════

def _print_summary(layer_results: list[dict]) -> None:
    """打印三层汇总表格。"""
    print(f"\n{'='*60}")
    print("三层评测汇总")
    print(f"{'='*60}")
    print(f"  {'层次':<12} {'结果':<8} {'关键指标'}")
    print(f"  {'-'*50}")
    for r in layer_results:
        if r.get("skipped"):
            print(f"  {'层次' + str(r['layer']):<12} {'SKIP':<8} {r.get('reason', '')}")
            continue
        passed   = r.get("passed", False)
        mark     = "[PASS]" if passed else "[FAIL]"
        layer_no = r["layer"]
        if layer_no == 1:
            metric = f"加权准确率={r.get('overall_accuracy', 0):.3f}  pass_rate={r.get('pass_count')}/{r.get('total_cases')}"
        elif layer_no == 2:
            checks = r.get("checks", {})
            failed = [k for k, v in checks.items() if not v["passed"]]
            metric = f"全部通过={r.get('all_passed')}  失败项={failed or '无'}"
        else:
            metric = f"HQ均分={r.get('overall_hq_avg')}  LQ均分={r.get('overall_lq_avg')}  对照有效={r.get('valid_contrasts')}/{r.get('total_pairs')}"
        print(f"  {'层次' + str(layer_no):<12} {mark:<12} {metric}")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="主 Agent 三层评测脚本")
    parser.add_argument("--layers", type=str, default="1,2,3",
                        help="要运行的层次，逗号分隔，如 1,2 或 3（默认 1,2,3）")
    parser.add_argument("--cases", type=int, default=None,
                        help="层次一/三的最大测试条数（默认全量）")
    parser.add_argument("--use-llm", action="store_true",
                        help="层次一使用 LLM 路径（默认启发式，无需 API）")
    parser.add_argument("--itinerary-file", type=str, default=None,
                        help="层次二：指定行程 JSON 文件路径")
    parser.add_argument("--out", type=str, default=None,
                        help="结果输出 JSON 文件路径（默认打印到 stdout）")
    args = parser.parse_args()

    layers_to_run = {int(x.strip()) for x in args.layers.split(",") if x.strip().isdigit()}
    layer_results = []

    # 加载测试集
    with open(_L1_TEST, encoding="utf-8") as f:
        l1_data = json.load(f)
    with open(_L3_TEST, encoding="utf-8") as f:
        l3_data = json.load(f)

    if 1 in layers_to_run:
        r1 = run_layer1(l1_data, use_llm=args.use_llm, max_cases=args.cases)
        layer_results.append(r1)

    if 2 in layers_to_run:
        r2 = run_layer2(itinerary_file=args.itinerary_file)
        layer_results.append(r2)

    if 3 in layers_to_run:
        r3 = run_layer3(l3_data, max_cases=args.cases)
        layer_results.append(r3)

    _print_summary(layer_results)

    report = {
        "eval_timestamp": datetime.now().isoformat(),
        "layers_run": sorted(layers_to_run),
        "layer_results": layer_results,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"结果已写入: {out_path}")
    else:
        # 打印精简 JSON 摘要（不包含 cases 明细，避免刷屏）
        summary = {k: v for k, v in report.items() if k != "layer_results"}
        summary["layer_summaries"] = [
            {k: v for k, v in r.items() if k not in ("cases", "pairs")}
            for r in layer_results
        ]
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
