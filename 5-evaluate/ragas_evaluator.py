"""
RAGAS 生成质量评测脚本

评测三个维度：
  - Faithfulness（忠实度）：回答是否仅依据检索上下文，不引入幻觉
  - Answer Relevancy（答案相关性）：回答是否切题
  - Context Precision（上下文精准度）：检索到的上下文是否与 query 相关

用法:
    cd Travel_agent_7035
    python 5-evaluate/ragas_evaluator.py
    python 5-evaluate/ragas_evaluator.py --cases 5   # 只跑前 5 条
    python 5-evaluate/ragas_evaluator.py --out result.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ── 路径：让脚本能 import search_notes ────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
_RAG_RETRIVAL = _ROOT / "2-rag-retrival"
_RAG_PIPELINE = _ROOT / "1-rag_pipeline_delivery"
for _p in [str(_ROOT), str(_RAG_RETRIVAL), str(_RAG_PIPELINE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from search_notes import search_notes  # noqa: E402
from token_costing import aggregate_token_usage, token_usage_from_response_usage, with_token_cost  # noqa: E402

# ── Azure OpenAI 客户端 ───────────────────────────────────────────────────────
try:
    from openai import AzureOpenAI
except ImportError:
    AzureOpenAI = None  # type: ignore

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(override=False)

_ENDPOINT   = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
_API_KEY    = os.getenv("FOUNDRY_PROJECT_API_KEY", "").strip()
_DEPLOYMENT = os.getenv("FOUNDRY_PROJECT_DEPLOYMENT", "").strip()
_API_VER    = os.getenv("FOUNDRY_API_VERSION", "2024-12-01-preview").strip()


def _make_client():
    if AzureOpenAI is None:
        raise RuntimeError("openai package not installed")
    if not (_ENDPOINT and _API_KEY and _DEPLOYMENT):
        raise RuntimeError(
            "Missing Azure OpenAI credentials. "
            "Set FOUNDRY_PROJECT_ENDPOINT / FOUNDRY_PROJECT_API_KEY / FOUNDRY_PROJECT_DEPLOYMENT in .env"
        )
    return AzureOpenAI(
        azure_endpoint=_ENDPOINT,
        api_key=_API_KEY,
        api_version=_API_VER,
    )


# ── Golden Test Set ───────────────────────────────────────────────────────────
# 每条包含 query / city / ground_truth（人工写的标准答案关键点）
# ground_truth 不需要是完整段落，列出必须覆盖的事实点即可
GOLDEN_CASES: list[dict[str, Any]] = [
    {
        "id": "rag_001",
        "query": "成都熊猫基地怎么去，几点开门",
        "city": "成都",
        "ground_truth": "熊猫基地正式名称是中国大熊猫保护研究中心成都基地，早上开门时间约为7:30-8:00，建议早上去看喂食，可乘坐地铁3号线或专线大巴前往。",
    },
    {
        "id": "rag_002",
        "query": "北京故宫门票怎么买，需要提前预约吗",
        "city": "北京",
        "ground_truth": "故宫门票需要在官方小程序或官网提前网上预约购票，不支持现场购票，旺季需提前数天甚至一周预约，门票价格60元（淡季40元）。",
    },
    {
        "id": "rag_003",
        "query": "上海外滩夜景怎么看，最佳观景点在哪",
        "city": "上海",
        "ground_truth": "上海外滩夜景可从外滩沿岸直接欣赏对岸陆家嘴夜景，也可去东方明珠观光层或上海中心观景台俯瞰，推荐傍晚6-9点，灯光最好。",
    },
    {
        "id": "rag_004",
        "query": "西安回民街必吃什么",
        "city": "西安",
        "ground_truth": "西安回民街必吃肉夹馍、biangbiang面、羊肉泡馍、凉皮、灌汤包，另外葫芦头也值得一试，街上小吃摊多，价格实惠。",
    },
    {
        "id": "rag_005",
        "query": "重庆洪崖洞适合几点去看夜景",
        "city": "重庆",
        "ground_truth": "重庆洪崖洞看夜景建议晚上7点以后，灯光全开后配合嘉陵江倒影效果最佳，节假日人多，工作日较好，可从解放碑步行约10分钟到达。",
    },
    {
        "id": "rag_006",
        "query": "杭州西湖免费吗，有哪些必逛景点",
        "city": "杭州",
        "ground_truth": "西湖核心景区免费开放，苏堤、白堤、断桥、雷峰塔（雷峰塔内部收费）均可步行游览，推荐路线：断桥→白堤→平湖秋月→苏堤，绕湖一圈约15公里。",
    },
    {
        "id": "rag_007",
        "query": "香港维多利亚港夜景怎么看最好",
        "city": "香港",
        "ground_truth": "香港维港夜景最佳观赏点是尖沙咀海滨长廊，每晚8点有幻彩咏香江灯光秀，也可乘坐天星小轮渡海欣赏两岸夜景，票价仅3-5港元。",
    },
    {
        "id": "rag_008",
        "query": "南京夫子庙秦淮河怎么玩",
        "city": "南京",
        "ground_truth": "南京夫子庙秦淮河景区免费，可沿河散步欣赏古建筑，乘坐秦淮画舫游览（约80元），夜晚灯火通明最美，周边有桂花鸭、鸭血粉丝汤等特色美食。",
    },
    {
        "id": "rag_009",
        "query": "厦门鼓浪屿怎么去，值得住一晚吗",
        "city": "厦门",
        "ground_truth": "从厦门轮渡码头乘船约10分钟可到鼓浪屿，船票约35元，岛上禁止机动车，适合步行游览日光岩、菽庄花园，住一晚可感受安静的小岛氛围，民宿价格偏高。",
    },
    {
        "id": "rag_010",
        "query": "广州早茶推荐哪些茶楼，有什么必点",
        "city": "广州",
        "ground_truth": "广州早茶推荐陶陶居、莲香楼、广州酒家等老字号，必点虾饺、烧卖、叉烧包、蛋挞、肠粉，广式早茶讲究一盅两件，人均约50-100元。",
    },
    {
        "id": "rag_011",
        "query": "深圳有哪些适合周末一日游的地方",
        "city": "深圳",
        "ground_truth": "深圳周末一日游推荐大梅沙海滩（免费）、华侨城欢乐谷（需购票）、东部华侨城、南澳岛，深圳地铁发达，大部分景点交通便利。",
    },
    {
        "id": "rag_012",
        "query": "东京浅草寺附近怎么逛，有什么推荐",
        "city": "东京",
        "ground_truth": "浅草寺仲见世通商店街可购买和果子、人形烧等传统小吃，雷门是必拍打卡点，附近有浅草文化观光中心可俯瞰全景，步行可到押上晴空塔。",
    },
]


# ── RAGAS 评测核心逻辑 ────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """你是一个严格、公正的 RAG 系统评测专家。
你的任务是对 RAG 系统的输出从三个维度打分，每个维度 0.0-1.0（保留两位小数）。
必须严格按照指定 JSON 格式输出，不要输出其他内容。"""

_JUDGE_PROMPT = """请对以下 RAG 系统输出进行评分：

【用户问题】
{query}

【检索到的上下文】
{context}

【系统生成的回答】
{answer}

【参考标准答案（关键事实点）】
{ground_truth}

请从以下三个维度打分（0.0-1.0）：

1. **faithfulness（忠实度）**：回答中的每一个陈述是否都能在检索上下文中找到依据？
   - 1.0：回答完全基于上下文，无任何幻觉
   - 0.5：部分陈述有依据，但有明显超出上下文的内容
   - 0.0：回答几乎与上下文无关，或包含大量错误信息

2. **answer_relevancy（答案相关性）**：回答是否直接回答了用户的问题？
   - 1.0：回答完全切题，信息精准有用
   - 0.5：基本回答了问题，但有冗余或遗漏关键点
   - 0.0：回答与问题无关

3. **context_precision（上下文精准度）**：检索到的上下文是否与问题高度相关？
   - 1.0：上下文直接包含回答问题所需的核心信息
   - 0.5：上下文部分相关，但有较多无关内容
   - 0.0：上下文基本不相关

请严格按照以下 JSON 格式输出（不要有任何其他文字）：
{{"faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "reasoning": "一句话说明主要扣分原因"}}"""


def _retrieve_context(query: str, city: str, top_k: int = 5) -> tuple[list[str], list[dict]]:
    """调用 search_notes 检索，返回 (chunk_texts, raw_results)。"""
    try:
        results = search_notes(query=query, city=city, strategy="hybrid", top_k=top_k)
        texts = [r["chunk_text"] for r in results if r.get("chunk_text")]
        return texts, results
    except Exception as e:
        print(f"  [WARN] 检索失败: {e}", flush=True)
        return [], []


def _compute_route_quality(raw_results: list[dict]) -> dict:
    """Compute route quality metrics from raw retrieval results."""
    PITFALL_TYPES = {"pitfall", "avoid_guide"}
    ROUTE_TYPES = {"route_plan", "attraction_guide", "hidden_gem", "family_route"}
    route_plan_count = sum(
        1 for r in raw_results
        if str(r.get("metadata", {}).get("content_type", "")).lower() in ROUTE_TYPES
    )
    pitfall_count = sum(
        1 for r in raw_results
        if str(r.get("metadata", {}).get("content_type", "")).lower() in PITFALL_TYPES
    )
    return {
        "evidence_chunk_count": len(raw_results),
        "route_plan_chunk_count": route_plan_count,
        "pitfall_chunk_count": pitfall_count,
        "has_pitfall_coverage": pitfall_count >= 1,
        "has_route_plan_coverage": route_plan_count >= 2,
    }


def _generate_answer(client, query: str, context_chunks: list[str]) -> tuple[str, dict]:
    """用检索上下文生成回答，返回 (answer, token_usage)。"""
    if not context_chunks:
        return "暂无相关信息。", {}

    context_text = "\n\n---\n\n".join(context_chunks[:5])
    messages = [
        {
            "role": "system",
            "content": "你是一个旅行助手，请仅根据以下检索到的参考资料回答用户问题，不要添加资料中没有的信息。",
        },
        {
            "role": "user",
            "content": f"参考资料：\n{context_text}\n\n问题：{query}",
        },
    ]
    resp = client.chat.completions.create(
        model=_DEPLOYMENT,
        messages=messages,
        temperature=0.1,
        max_tokens=500,
    )
    answer = (resp.choices[0].message.content or "").strip()
    usage = token_usage_from_response_usage(resp.usage, model=_DEPLOYMENT)
    return answer, usage


def _judge(client, query: str, context_chunks: list[str], answer: str, ground_truth: str) -> dict:
    """让 LLM 作 Judge，返回三维评分 dict。"""
    context_text = "\n\n---\n\n".join(context_chunks[:5]) if context_chunks else "（无检索结果）"
    prompt = _JUDGE_PROMPT.format(
        query=query,
        context=context_text,
        answer=answer,
        ground_truth=ground_truth,
    )
    resp = client.chat.completions.create(
        model=_DEPLOYMENT,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=200,
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        scores = json.loads(raw)
    except json.JSONDecodeError:
        # 容错：尝试提取 JSON 块
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        scores = json.loads(m.group()) if m else {}

    usage = token_usage_from_response_usage(resp.usage, model=_DEPLOYMENT)
    return {"scores": scores, "token_usage": usage, "raw_judge_output": raw}


def run_evaluation(cases: list[dict], top_k: int = 5, delay_s: float = 1.0) -> dict:
    """
    对所有 case 跑完整的 Retrieve → Generate → Judge 流程。
    返回汇总结果 dict。
    """
    client = _make_client()

    results = []
    total_input_tokens = 0
    total_output_tokens = 0
    all_token_usages = []

    for i, case in enumerate(cases):
        cid = case["id"]
        query = case["query"]
        city = case["city"]
        ground_truth = case["ground_truth"]

        print(f"\n[{i+1}/{len(cases)}] {cid} — {query[:40]}", flush=True)

        # Step 1: Retrieve
        t0 = time.monotonic()
        context_chunks, raw_results = _retrieve_context(query, city, top_k=top_k)
        retrieve_ms = int((time.monotonic() - t0) * 1000)
        print(f"  检索: {len(context_chunks)} chunks ({retrieve_ms}ms)", flush=True)

        # Step 2: Generate
        t0 = time.monotonic()
        answer, gen_usage = _generate_answer(client, query, context_chunks)
        gen_ms = int((time.monotonic() - t0) * 1000)
        total_input_tokens += gen_usage.get("input_tokens", 0)
        total_output_tokens += gen_usage.get("output_tokens", 0)
        all_token_usages.append(gen_usage)
        print(f"  生成: {len(answer)} 字 ({gen_ms}ms)", flush=True)

        # Step 3: Judge
        t0 = time.monotonic()
        judge_result = _judge(client, query, context_chunks, answer, ground_truth)
        judge_ms = int((time.monotonic() - t0) * 1000)
        total_input_tokens += judge_result["token_usage"].get("input_tokens", 0)
        total_output_tokens += judge_result["token_usage"].get("output_tokens", 0)
        all_token_usages.append(judge_result["token_usage"])

        scores = judge_result["scores"]
        faithfulness = scores.get("faithfulness", 0.0)
        answer_relevancy = scores.get("answer_relevancy", 0.0)
        context_precision = scores.get("context_precision", 0.0)
        reasoning = scores.get("reasoning", "")

        print(
            f"  评分: faithfulness={faithfulness:.2f}  "
            f"answer_relevancy={answer_relevancy:.2f}  "
            f"context_precision={context_precision:.2f}",
            flush=True,
        )
        if reasoning:
            print(f"  原因: {reasoning}", flush=True)

        results.append({
            "id": cid,
            "query": query,
            "city": city,
            "context_chunk_count": len(context_chunks),
            "answer": answer,
            "ground_truth": ground_truth,
            "scores": {
                "faithfulness": faithfulness,
                "answer_relevancy": answer_relevancy,
                "context_precision": context_precision,
            },
            "reasoning": reasoning,
            "latency_ms": {
                "retrieve": retrieve_ms,
                "generate": gen_ms,
                "judge": judge_ms,
            },
            "token_usage": aggregate_token_usage(
                [gen_usage, judge_result["token_usage"]],
                model=_DEPLOYMENT,
                source="rag_case",
            ),
            "route_quality": _compute_route_quality(raw_results),
        })

        if delay_s > 0 and i < len(cases) - 1:
            time.sleep(delay_s)

    # 汇总
    n = len(results)
    avg_faithfulness = sum(r["scores"]["faithfulness"] for r in results) / n
    avg_relevancy = sum(r["scores"]["answer_relevancy"] for r in results) / n
    avg_precision = sum(r["scores"]["context_precision"] for r in results) / n
    avg_all = (avg_faithfulness + avg_relevancy + avg_precision) / 3

    summary = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model": _DEPLOYMENT,
        "case_count": n,
        "top_k": top_k,
        "avg_scores": {
            "faithfulness": round(avg_faithfulness, 4),
            "answer_relevancy": round(avg_relevancy, 4),
            "context_precision": round(avg_precision, 4),
            "overall": round(avg_all, 4),
        },
        "token_usage": with_token_cost(
            {
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
                "llm_call_count": sum(item.get("llm_call_count", 0) for item in all_token_usages),
                "model": _DEPLOYMENT,
                "source": "ragas_evaluator",
            },
            model=_DEPLOYMENT,
        ),
        "thresholds": {
            "faithfulness": {"target": 0.7, "pass": avg_faithfulness >= 0.7},
            "answer_relevancy": {"target": 0.7, "pass": avg_relevancy >= 0.7},
            "context_precision": {"target": 0.6, "pass": avg_precision >= 0.6},
            "overall": {"target": 0.67, "pass": avg_all >= 0.67},
        },
        "details": results,
    }

    # Route quality summary
    cases_with_pitfall = sum(1 for r in results if r.get("route_quality", {}).get("has_pitfall_coverage"))
    cases_with_route = sum(1 for r in results if r.get("route_quality", {}).get("has_route_plan_coverage"))
    avg_evidence_chunks = sum(r.get("route_quality", {}).get("evidence_chunk_count", 0) for r in results) / max(n, 1)
    summary["route_quality_summary"] = {
        "avg_evidence_chunks": round(avg_evidence_chunks, 1),
        "cases_with_pitfall_coverage": cases_with_pitfall,
        "cases_with_route_plan_coverage": cases_with_route,
        "pitfall_coverage_rate": round(cases_with_pitfall / max(n, 1), 3),
        "route_plan_coverage_rate": round(cases_with_route / max(n, 1), 3),
    }

    return summary


def print_report(summary: dict) -> None:
    """在终端打印可读报告。"""
    avg = summary["avg_scores"]
    thr = summary["thresholds"]
    n = summary["case_count"]

    print("\n" + "=" * 60)
    print("  RAGAS 生成质量评测报告")
    print("=" * 60)
    print(f"  模型: {summary['model']}")
    print(f"  测试集: {n} 条  |  Top-K: {summary['top_k']}")
    print(f"  时间: {summary['timestamp']}")
    print()

    def _mark(passed: bool) -> str:
        return "✅" if passed else "❌"

    print(f"  {'指标':<20} {'均值':>8}  {'目标':>6}  状态")
    print("  " + "-" * 44)
    print(f"  {'Faithfulness':<20} {avg['faithfulness']:>8.4f}  {'≥0.70':>6}  {_mark(thr['faithfulness']['pass'])}")
    print(f"  {'Answer Relevancy':<20} {avg['answer_relevancy']:>8.4f}  {'≥0.70':>6}  {_mark(thr['answer_relevancy']['pass'])}")
    print(f"  {'Context Precision':<20} {avg['context_precision']:>8.4f}  {'≥0.60':>6}  {_mark(thr['context_precision']['pass'])}")
    print(f"  {'Overall':<20} {avg['overall']:>8.4f}  {'≥0.67':>6}  {_mark(thr['overall']['pass'])}")
    print()

    tok = summary["token_usage"]
    cost = tok.get("estimated_cost", {})
    print(f"  Cost estimate: ${cost.get('total_usd', 0):.6f} / CNY {cost.get('total_cny', 0):.4f}")
    print(f"  Token 消耗: 输入 {tok['total_input_tokens']}  输出 {tok['total_output_tokens']}  合计 {tok['total_tokens']}")

    rqs = summary.get("route_quality_summary", {})
    if rqs:
        print(f"\n  路线质量覆盖率:")
        print(f"  {'Avg Evidence Chunks':<24} {rqs.get('avg_evidence_chunks', 0):>6.1f}")
        print(f"  {'Route Plan Coverage':<24} {rqs.get('route_plan_coverage_rate', 0):>6.1%}  (≥2 route_plan chunks/case)")
        print(f"  {'Pitfall Coverage':<24} {rqs.get('pitfall_coverage_rate', 0):>6.1%}  (≥1 pitfall chunk/case)")

    # 逐条明细
    print("\n  逐条明细:")
    print(f"  {'ID':<10} {'城市':<6} {'Faith':>6} {'Relev':>6} {'Prec':>6}  备注")
    print("  " + "-" * 55)
    for r in summary["details"]:
        s = r["scores"]
        print(
            f"  {r['id']:<10} {r['city']:<6} "
            f"{s['faithfulness']:>6.2f} {s['answer_relevancy']:>6.2f} {s['context_precision']:>6.2f}  "
            f"{r['reasoning'][:30]}"
        )
    print("=" * 60)


def export_json(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAGAS RAG 生成质量评测")
    parser.add_argument("--cases", type=int, default=0, help="只跑前 N 条（0=全跑）")
    parser.add_argument("--top-k", type=int, default=5, help="检索返回 chunk 数")
    parser.add_argument("--delay", type=float, default=1.0, help="每条 case 间隔秒数（防限流）")
    parser.add_argument("--out", type=str, default="", help="结果 JSON 输出路径")
    args = parser.parse_args()

    cases = GOLDEN_CASES[: args.cases] if args.cases > 0 else GOLDEN_CASES
    print(f"开始 RAGAS 评测: {len(cases)} 条 case，top_k={args.top_k}")

    summary = run_evaluation(cases, top_k=args.top_k, delay_s=args.delay)
    print_report(summary)

    out_path = Path(args.out) if args.out else Path(__file__).parent / "ragas_result.json"
    export_json(summary, out_path)
