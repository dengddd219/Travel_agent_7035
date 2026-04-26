# -*- coding: utf-8 -*-
"""
RAG Pipeline 交互式逐步演示脚本

  Step 0  用户输入
  Step 1  意图提取 (_extract_user_profile)
  Step 2  Query 分解 (_decompose_request)
  Step 3  RAG 检索 (get_strategy_context -> search_notes)
  Step 3b RAG 摘要输出 (_summarize_strategy)
  Step 4  城市上下文 (get_city_context)
  Step 5  天气预报 (get_weather_forecast)
  Step 6  POI 搜索 (search_batch_pois)
  Step 7  费用估算 (get_cost_summary)
  Step 8  旅行 Tips (get_travel_tips)
  Step 9  规划器输入汇总
  Step 10 规划器输出 (plan_itinerary)

用法:
    cd Travel_agent_7035
    python 5-evaluate/RAG全流程DEBUG.py
    python 5-evaluate/RAG全流程DEBUG.py --query "我想去成都玩3天，喜欢美食"
    python 5-evaluate/RAG全流程DEBUG.py --query "北京5天亲子游" --auto
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# ── 路径注入 ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
_PLANNER = _ROOT / "3-travel_planner"
_RAG_RETRIVAL = _ROOT / "2-rag-retrival"
_RAG_PIPELINE = _ROOT / "1-rag_pipeline_delivery"
_BACKEND = _ROOT / "backend"          # WeatherCost shim 在这里

for _p in [str(_PLANNER), str(_RAG_RETRIVAL), str(_RAG_PIPELINE), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── ANSI 颜色 ─────────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
CYAN    = "\033[36m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
RED     = "\033[31m"
WHITE   = "\033[97m"


def c(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


def hr(char: str = "-", width: int = 72, color: str = DIM) -> None:
    print(color + char * width + RESET)


def header(title: str, step: str, color: str = CYAN) -> None:
    print()
    hr("=", color=color)
    print(c(f"  {step}  {title}", BOLD, color))
    hr("-", color=DIM)


def kv(key: str, value: Any, indent: int = 2) -> None:
    pad = " " * indent
    if isinstance(value, (dict, list)):
        vstr = json.dumps(value, ensure_ascii=False, indent=2)
        lines = vstr.splitlines()
        print(f"{pad}{c(key + ':', BOLD, WHITE)}")
        for line in lines:
            print(f"{pad}  {c(line, DIM)}")
    else:
        print(f"{pad}{c(key + ':', BOLD, WHITE)} {c(str(value), DIM)}")


def pause(auto: bool, label: str = "") -> None:
    if auto:
        return
    msg = f"\n  {c('[ Enter 继续', YELLOW)}{c(f' -- {label}', DIM)}{c(' ]', YELLOW)}"
    input(msg)


def section_result(data: Any, max_chars: int = 800) -> None:
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    if len(raw) > max_chars:
        print(c(raw[:max_chars], DIM))
        print(c(f"  ... (截断，共 {len(raw)} 字符)", DIM))
    else:
        print(c(raw, DIM))


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run(query: str, auto: bool) -> None:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=False)
    load_dotenv(override=False)

    from travel_planner.config import Settings
    from travel_planner.agent import TravelPlanningAgent
    from travel_planner.tools.strategy_rag_adapter import get_strategy_context
    from travel_planner.tools.city_context import get_city_context
    from travel_planner.tools.poi import search_batch_pois
    from travel_planner.tools.weather_adapter import get_group_c_weather_forecast
    from travel_planner.tools.cost_adapter import get_group_c_cost_summary
    from travel_planner.tools.tips import get_travel_tips
    from travel_planner.planner import plan_itinerary

    settings = Settings.from_env()
    agent = TravelPlanningAgent(settings=settings)

    # ── STEP 0: 用户输入 ───────────────────────────────────────────────────────
    header("用户输入", "STEP 0", CYAN)
    kv("原始 query", query)
    pause(auto, "查看意图提取")

    # ── STEP 1: 意图提取 ───────────────────────────────────────────────────────
    header("意图提取  _extract_user_profile(user_request)", "STEP 1", YELLOW)
    print(c("  >> 正则 + 别名表从用户输入中提取结构化槽位，无 LLM", DIM))
    print()

    t0 = time.perf_counter()
    profile = agent._extract_user_profile(query)
    elapsed = time.perf_counter() - t0

    kv("输出 user_profile", profile)
    print(c(f"\n  耗时: {elapsed*1000:.1f}ms（纯 Python）", DIM))

    print()
    print(c("  槽位说明:", BOLD, WHITE))
    slot_notes = {
        "city":         "城市（别名表映射，24 条）",
        "trip_days":    "天数（1-14，默认 3）",
        "travel_type":  "旅行风格: leisure/family/food/theme",
        "budget_level": "预算: low/medium/high",
        "pace":         "节奏: slow/balanced/packed",
        "interests":    "兴趣标签",
        "must_visit":   "必去景点",
        "avoid":        "排斥景点（优先级高于 must_visit）",
    }
    for slot, note in slot_notes.items():
        val = profile.get(slot, "(未提取)")
        print(c(f"    {slot:<14}", BOLD, WHITE) + c(note, DIM) + c(f"  -> {val}", GREEN))

    pause(auto, "查看 Query 分解")

    # ── STEP 2: Query 分解 ─────────────────────────────────────────────────────
    header("Query 分解  _decompose_request(user_request, user_profile)", "STEP 2", YELLOW)
    print(c("  >> 把意图拆成 RAG检索query / 地图搜索query / 条件查询，无 LLM", DIM))
    print()

    t0 = time.perf_counter()
    decomp = agent._decompose_request(query, profile)
    elapsed = time.perf_counter() - t0

    kv("strategy_queries  (-> RAG 检索)", decomp.get("strategy_queries", []))
    kv("geo_queries       (-> POI 地图搜索)", decomp.get("geo_queries", []))
    kv("condition_queries (-> 天气/费用)", decomp.get("condition_queries", {}))
    print(c(f"\n  耗时: {elapsed*1000:.1f}ms（纯 Python）", DIM))

    pause(auto, "查看 RAG 检索")

    # ── 提取关键变量 ───────────────────────────────────────────────────────────
    city = profile.get("city", "Hong Kong")
    travel_type = profile.get("travel_type", "leisure")
    trip_days = profile.get("trip_days", 3)
    budget_level = profile.get("budget_level", "medium")
    strategy_queries = decomp.get("strategy_queries", [f"{city} 旅游攻略"])
    geo_queries = decomp.get("geo_queries", [f"{city} 景点"])
    must_visit = profile.get("must_visit", [])

    # ── STEP 3: RAG 检索 ───────────────────────────────────────────────────────
    header("RAG 检索  get_strategy_context()", "STEP 3", BLUE)
    print(c("  >> 内部调用 search_notes -> ChromaDB dense + BM25 -> RRF 融合", DIM))
    print(c("  >> 降级: ChromaDB 不可用 -> 本地 BM25 (strategy_rag_adapter)", DIM))
    print()

    rag_queries = list(dict.fromkeys(strategy_queries))[:6]   # 与 agent._dedupe_queries 一致
    kv("city", city)
    kv("travel_type", travel_type)
    kv("queries (去重后前6条)", rag_queries)
    kv("top_k", 5)

    print()
    print(c("  >> 开始检索...", BOLD, BLUE))

    t0 = time.perf_counter()
    rag_result = get_strategy_context(city=city, queries=rag_queries, travel_type=travel_type, top_k=5)
    elapsed = time.perf_counter() - t0

    print(c(f"  OK 耗时: {elapsed*1000:.0f}ms", GREEN))

    pause(auto, "查看 RAG 原始 chunks")

    # ── STEP 3a: 原始 chunks ───────────────────────────────────────────────────
    header("RAG 原始检索结果  results[]", "STEP 3a", BLUE)
    print(c("  >> search_notes 返回的原始 chunk 列表，按 RRF 融合分数排序", DIM))
    print()

    raw_chunks = rag_result.get("results", [])
    kv("retrieval_mode", rag_result.get("retrieval_mode", "?"))
    kv("source", rag_result.get("source", "?"))
    kv("总 chunk 数", len(raw_chunks))
    print()

    print(c("  前 5 条 chunks:", BOLD, WHITE))
    for i, ch in enumerate(raw_chunks[:5], 1):
        print()
        print(c(f"  -- Chunk #{i} --", DIM))
        kv("    chunk_id", ch.get("chunk_id", "?"))
        kv("    score", round(ch.get("score", 0), 6))
        meta = ch.get("metadata", {})
        kv("    metadata.city", meta.get("city", "?"))
        kv("    metadata.title", meta.get("title", "?"))
        kv("    metadata.poi_names", meta.get("poi_names", []))
        kv("    metadata.travel_type_tags", meta.get("travel_type_tags", []))
        snippet = ch.get("chunk_text", "")[:300].replace("\n", " ")
        print(c(f"    chunk_text (前300字): {snippet}", DIM))

    pause(auto, "查看 RAG 摘要输出")

    # ── STEP 3b: _summarize_strategy 输出 ─────────────────────────────────────
    header("RAG 摘要  _summarize_strategy() 输出", "STEP 3b", GREEN)
    print(c("  >> 这是真正传给规划器的内容，不是 chunk 原文，是结构化摘要", DIM))
    print(c("  >> 从 chunk metadata 的 poi_names / travel_type_tags / pitfall 提取", DIM))
    print()

    kv("recommended_pois", rag_result.get("recommended_pois", []))
    kv("theme_suggestions", rag_result.get("theme_suggestions", []))
    kv("local_pitfalls", rag_result.get("local_pitfalls", []))
    kv("neighborhood_notes", rag_result.get("neighborhood_notes", []))

    print()
    print(c("  *** 关键: LLM 从未直接读到 chunk 原文！", BOLD, RED))
    print(c("  RAG 输出是结构化字段 -> 纯 Python 规划器消费", DIM))

    pause(auto, "查看城市上下文")

    # ── STEP 4: 城市上下文 ─────────────────────────────────────────────────────
    # 实际 agent._execute() 顺序: get_city_context -> get_strategy_context -> get_weather -> ...
    # 演示里把 RAG 检索提前以便先讲清楚，城市上下文放这里不影响逻辑理解
    header("城市上下文  get_city_context(city, travel_type)", "STEP 4", MAGENTA)
    print(c("  >> 读 3-travel_planner/travel_planner/data/city_profiles/{city_slug}.json，本地文件，无网络", DIM))
    print()

    t0 = time.perf_counter()
    city_ctx = get_city_context(city, travel_type)
    elapsed = time.perf_counter() - t0

    if isinstance(city_ctx, dict):
        area_names = [item.get("name", "") for item in city_ctx.get("recommended_areas", []) if item.get("name")]
        kv("city", city_ctx.get("city", "?"))
        kv("recommended_areas (前5)", area_names[:5])
        kv("signature_foods (前3)", city_ctx.get("signature_foods", [])[:3])
        kv("focus_tags", city_ctx.get("focus_tags", []))
        kv("suggested_queries (前5)", city_ctx.get("suggested_queries", [])[:5])
        kv("pace_note", city_ctx.get("pace_note", ""))
    else:
        kv("输出", str(city_ctx)[:500])
    print(c(f"\n  耗时: {elapsed*1000:.1f}ms（本地 JSON）", DIM))

    pause(auto, "查看天气预报")

    # ── STEP 5: 天气预报 ───────────────────────────────────────────────────────
    header("天气预报  get_weather_forecast(city, trip_days)", "STEP 5", MAGENTA)
    print(c("  >> 实际链路: weather_adapter -> C 组 get_weather_api -> 高德天气 REST", DIM))
    print(c("  >> 若高德失败，真实 fallback 为 C 组 mock_data；不是 city_profiles/fallback_weather", DIM))
    print()

    kv("city", city)
    kv("trip_days", trip_days)
    kv("settings.has_amap_key", settings.has_amap_key)

    t0 = time.perf_counter()
    try:
        weather_result = get_group_c_weather_forecast(city=city, trip_days=trip_days, settings=settings)
        elapsed = time.perf_counter() - t0
        print(c(f"  OK 耗时: {elapsed*1000:.0f}ms", GREEN))
        print()
        if isinstance(weather_result, dict):
            kv("source", weather_result.get("source", "?"))
            kv("provider_city", weather_result.get("provider_city", ""))
            kv("window_note", weather_result.get("window_note", ""))
            forecast = weather_result.get("forecast", [])
            print(c("  forecast (前3天):", BOLD, WHITE))
            for day in forecast[:3]:
                print(c(
                    f"    * {day.get('date', '?')}  {day.get('summary', '?')}  "
                    f"{day.get('temp_min', '?')}~{day.get('temp_max', '?')}°C  "
                    f"precip={day.get('precipitation_probability', '?')}%  "
                    f"outdoor={day.get('outdoor_suitability', '?')}  "
                    f"source={day.get('source', '?')}",
                    DIM,
                ))
        else:
            kv("输出", str(weather_result)[:400])
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(c(f"  WARN 跳过 ({elapsed*1000:.0f}ms): {e}", RED))
        weather_result = {}

    pause(auto, "查看 POI 搜索")

    # ── STEP 6: POI 搜索 ───────────────────────────────────────────────────────
    header("POI 搜索  search_batch_pois(city, queries, limit_per_query)", "STEP 6", MAGENTA)
    print(c("  >> 实际逻辑不是固定“高德 -> Nominatim -> seed_pois”", DIM))
    print(c("  >> 若 query 与 seed_pois 强匹配，会直接返回 profile_seed；否则再尝试 Amap / Nominatim", DIM))
    print(c("  >> 输入: geo_queries + must_visit（合并去重，最多 10 条）", DIM))
    print()

    combined_queries = list(dict.fromkeys(geo_queries + must_visit))[:10]
    kv("geo_queries", geo_queries)
    kv("must_visit", must_visit)
    kv("合并后 queries", combined_queries)
    kv("limit_per_query", 3)
    kv("settings.has_amap_key", settings.has_amap_key)

    print()
    print(c("  >> 开始 POI 搜索...", BOLD, MAGENTA))

    t0 = time.perf_counter()
    try:
        poi_result = search_batch_pois(city=city, queries=combined_queries, limit_per_query=3, settings=settings)
        elapsed = time.perf_counter() - t0
        pois = poi_result.get("results", []) if isinstance(poi_result, dict) else []
        print(c(f"  OK 耗时: {elapsed*1000:.0f}ms  共 {len(pois)} 个 POI", GREEN))
        print()
        kv("provider", poi_result.get("provider", "?") if isinstance(poi_result, dict) else "?")
        kv("missing_queries", poi_result.get("missing_queries", []) if isinstance(poi_result, dict) else [])
        print(c("  前 5 个 POI:", BOLD, WHITE))
        for poi in pois[:5]:
            name  = poi.get("name", "?")
            cat   = poi.get("category", "?")
            dist  = poi.get("district", "?")
            lat   = poi.get("lat", 0)
            lon   = poi.get("lon", 0)
            price = poi.get("ticket_price", 0)
            src   = poi.get("source", [])
            print(c(f"    * {name} [{cat}] {dist}  ({lat:.4f}, {lon:.4f})  票价: ¥{price}  source={src}", DIM))
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(c(f"  WARN 跳过 ({elapsed*1000:.0f}ms): {e}", RED))
        poi_result = {"results": []}
        pois = []

    pause(auto, "查看费用估算")

    # ── STEP 7: 费用估算 ───────────────────────────────────────────────────────
    header("费用估算  get_cost_summary(city, days, budget_level)", "STEP 7", MAGENTA)
    print(c("  >> 实际链路: cost_adapter -> C 组 estimate_cost_api -> 静态城市预算表", DIM))
    print(c("  >> 这里只算酒店 / 餐饮 / 本地交通区间；不是 Day1/Day2 的景点票价", DIM))
    print()

    kv("city", city)
    kv("days", trip_days)
    kv("budget_level", budget_level)

    t0 = time.perf_counter()
    try:
        cost_result = get_group_c_cost_summary(city=city, days=trip_days, budget_level=budget_level)
        elapsed = time.perf_counter() - t0
        print(c(f"  OK 耗时: {elapsed*1000:.0f}ms", GREEN))
        print()
        if isinstance(cost_result, dict):
            kv("source", cost_result.get("source", "?"))
            kv("provider_city", cost_result.get("provider_city", ""))
            kv("budget_level(normalized)", cost_result.get("budget_level", budget_level))
            kv("breakdown", cost_result.get("breakdown", {}))
            kv("totals", cost_result.get("totals", {}))
            kv("pricing_notes", cost_result.get("pricing_notes", []))
        else:
            kv("输出", str(cost_result)[:400])
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(c(f"  WARN 跳过 ({elapsed*1000:.0f}ms): {e}", RED))
        cost_result = {}

    pause(auto, "查看旅行 Tips")

    # ── STEP 8: 旅行 Tips ──────────────────────────────────────────────────────
    header("旅行 Tips  get_travel_tips(city, poi_names, travel_type)", "STEP 8", MAGENTA)
    print(c("  >> Tavily 搜索 -> 启发式 fallback", DIM))
    print(c("  >> poi_names 来自 STEP 6 search_batch_pois 结果前 8 条", DIM))
    print()

    poi_names_for_tips = [p.get("name", "") for p in pois[:8]]
    kv("poi_names (来自 STEP 6)", poi_names_for_tips)
    kv("travel_type", travel_type)
    kv("interests", profile.get("interests", []))

    t0 = time.perf_counter()
    try:
        tips_result = get_travel_tips(
            city=city,
            poi_names=poi_names_for_tips,
            travel_type=travel_type,
            interests=profile.get("interests", []),
            settings=settings,
        )
        elapsed = time.perf_counter() - t0
        print(c(f"  OK 耗时: {elapsed*1000:.0f}ms", GREEN))
        print()
        kv("输出 (前400字)", str(tips_result)[:400])
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(c(f"  WARN 跳过 ({elapsed*1000:.0f}ms): {e}", RED))
        tips_result = {}

    pause(auto, "查看规划器输入汇总")

    # ── STEP 9: 规划器输入汇总 ─────────────────────────────────────────────────
    header("规划器输入汇总（所有工具结果汇合点）", "STEP 9", BLUE)
    print(c("  >> agent._auto_finish() 把以上所有结果打包传给 plan_itinerary()", DIM))
    print()

    print(c("  来自 RAG (_summarize_strategy):", BOLD, WHITE))
    print(c(f"    recommended_pois  -> {rag_result.get('recommended_pois', [])}", DIM))
    print(c(f"    neighborhood_notes-> {[n.get('district') for n in rag_result.get('neighborhood_notes', [])]}", DIM))
    print(c(f"    local_pitfalls    -> {len(rag_result.get('local_pitfalls', []))} 条", DIM))
    print()
    print(c("  来自 UserProfile:", BOLD, WHITE))
    print(c(f"    must_visit  -> {must_visit}", DIM))
    print(c(f"    avoid       -> {profile.get('avoid', [])}", DIM))
    print(c(f"    trip_days   -> {trip_days}", DIM))
    print(c(f"    pace        -> {profile.get('pace', 'balanced')}", DIM))
    print()
    print(c("  来自 POI 搜索:", BOLD, WHITE))
    print(c(f"    {len(pois)} 个带坐标/票价的 POI 丰富候选池", DIM))
    print()
    print(c("  RAG 在规划中的实际作用:", BOLD, YELLOW))
    print(c("    1. recommended_pois -> 候选池（优先级高于纯地图结果）", DIM))
    print(c("    2. neighborhood_notes -> 区域聚类（同天同区域）", DIM))
    print(c("    3. local_pitfalls -> 注入最终报告 tips 区", DIM))
    print(c("    4. theme_suggestions -> 影响行程叙述风格", DIM))

    pause(auto, "查看规划器输出")

    # ── STEP 10: 规划器输出 ────────────────────────────────────────────────────
    header("规划器输出  plan_itinerary(preferences, available_pois, strategy_context)", "STEP 10", GREEN)
    print(c("  >> 纯 Python 确定性规划，无 LLM", DIM))
    print(c("  >> _select_pois() -> _allocate_days() -> review_itinerary()", DIM))
    print()

    try:
        from travel_planner.models import POI
        from datetime import date

        # 用真实 POI 数据（来自 search_batch_pois）
        available_pois: list[POI] = []
        for p in pois:
            try:
                available_pois.append(POI(
                    name=p.get("name", ""),
                    category=p.get("category", "景点"),
                    district=p.get("district", "市区"),
                    lat=float(p.get("lat", 0) or 0),
                    lon=float(p.get("lon", 0) or 0),
                    duration_hours=float(p.get("duration_hours", 2.0) or 2.0),
                    ticket_price=float(p.get("ticket_price", 0) or 0),
                    price_level=p.get("price_level", "free"),
                    indoor_outdoor=p.get("indoor_outdoor", "outdoor"),
                    tags=p.get("tags", []),
                    source=p.get("source", "poi"),
                ))
            except Exception:
                pass

        # 如果 POI 搜索没结果，用 RAG 推荐名称构建最小列表
        if not available_pois:
            print(c("  POI 搜索无结果，用 RAG recommended_pois 构建最小 POI 列表", YELLOW))
            for i, poi_name in enumerate(rag_result.get("recommended_pois", [])[:12]):
                available_pois.append(POI(
                    name=poi_name, category="景点", district="市区",
                    lat=30.0 + i * 0.01, lon=104.0 + i * 0.01,
                    duration_hours=2.0, ticket_price=0, price_level="free",
                    indoor_outdoor="outdoor", tags=[], source="rag",
                ))

        if available_pois:
            # plan_itinerary 接收 dict 格式的 POI 和 user_profile
            candidate_pois_dicts = [
                {
                    "name": p.name, "category": p.category, "district": p.district,
                    "lat": p.lat, "lon": p.lon, "duration_hours": p.duration_hours,
                    "ticket_price": p.ticket_price, "price_level": p.price_level,
                    "indoor_outdoor": p.indoor_outdoor, "tags": p.tags, "source": p.source,
                }
                for p in available_pois
            ]
            kv("输入 POI 数量", len(candidate_pois_dicts))
            t0 = time.perf_counter()
            plan = plan_itinerary(
                user_profile=profile,
                candidate_pois=candidate_pois_dicts,
                weather=weather_result,
                city_context=city_ctx if isinstance(city_ctx, dict) else {},
                travel_tips=tips_result,
                strategy_context=rag_result,
                settings=settings,
            )
            elapsed = time.perf_counter() - t0
            print(c(f"  OK 耗时: {elapsed*1000:.0f}ms", GREEN))
            print()

            days = plan.get("days", []) if isinstance(plan, dict) else []
            kv("总天数", len(days))
            kv("planning_notes", plan.get("planning_notes", []) if isinstance(plan, dict) else [])
            print()
            for day in days:
                if isinstance(day, dict):
                    items = day.get("items", [])
                    names = [it.get("poi_name", "?") for it in items]
                    area  = day.get("area", "?")
                    theme = day.get("theme", "")
                    cost  = day.get("estimated_cost", "?")
                    idx   = day.get("day_index", "?")
                else:
                    items = day.items if hasattr(day, "items") else []
                    names = [it.poi_name if hasattr(it, "poi_name") else it.get("poi_name","?") for it in items]
                    area  = getattr(day, "area", "?")
                    theme = getattr(day, "theme", "")
                    cost  = getattr(day, "estimated_cost", "?")
                    idx   = getattr(day, "day_index", "?")
                print(c(f"  Day {idx}: {area} -- {theme}  (预估 ¥{cost})", BOLD, WHITE))
                print(c(f"    景点: {names}", DIM))
        else:
            print(c("  WARN RAG 无推荐 POI，跳过规划器演示", YELLOW))

    except Exception as e:
        print(c(f"  ERROR 规划器异常: {e}", RED))
        import traceback
        print(c(traceback.format_exc(), DIM))

    # ── 最终汇总 ───────────────────────────────────────────────────────────────
    print()
    hr("=", color=CYAN)
    print(c("  Walk-through 完成", BOLD, GREEN))
    hr("-", color=DIM)
    print(c("  完整链路回顾 (与 agent._execute() 顺序一致):", BOLD, WHITE))
    steps = [
        ("STEP 0",  "用户输入",               "自然语言 -> 原始 query"),
        ("STEP 1",  "_extract_user_profile",   "正则/别名 -> 结构化 profile（纯Python）"),
        ("STEP 2",  "_decompose_request",       "profile -> strategy/geo/condition queries（纯Python）"),
        ("STEP 3",  "get_city_context",         "city -> 城市基础信息 JSON"),
        ("STEP 3a", "get_strategy_context",     "queries -> ChromaDB+BM25 -> raw chunks"),
        ("STEP 3b", "_summarize_strategy",      "chunks -> recommended_pois/pitfalls（纯Python）"),
        ("STEP 5",  "get_weather_forecast",     "city/days -> 高德天气 / C组mock_data"),
        ("STEP 6",  "search_batch_pois",        "queries -> profile_seed 或 Amap/Nominatim"),
        ("STEP 7",  "get_cost_summary",         "city/days/budget -> C组静态预算区间"),
        ("STEP 8",  "get_travel_tips",          "poi_names -> Tavily / 启发式 fallback"),
        ("STEP 9",  "规划器输入汇总",           "RAG摘要 + POI + profile 汇合"),
        ("STEP 10", "plan_itinerary",           "确定性规划 -> DayPlan（纯Python，无LLM）"),
    ]
    for code, name, desc in steps:
        print(c(f"  {code:<8}", BOLD, CYAN) + c(f"{name:<26}", BOLD, WHITE) + c(desc, DIM))
    hr("=", color=CYAN)
    print()


# ── CLI 入口 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Windows 终端 UTF-8
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="RAG Pipeline 交互式逐步演示")
    parser.add_argument("--query", "-q", type=str, default="", help="用户输入（留空则交互式输入）")
    parser.add_argument("--auto", "-a", action="store_true", help="不暂停，自动跑完所有步骤")
    args = parser.parse_args()

    query = args.query.strip()
    if not query:
        print(c("\n  RAG Pipeline 交互式演示", BOLD, CYAN))
        print(c("  每步结束后按 Enter 继续，--auto 可跳过暂停\n", DIM))
        query = input(c("  请输入旅行需求: ", BOLD, YELLOW)).strip()
        if not query:
            query = "我想去成都玩3天，喜欢美食，预算中等"
            print(c(f"  使用默认示例: {query}", DIM))

    run(query, args.auto)
