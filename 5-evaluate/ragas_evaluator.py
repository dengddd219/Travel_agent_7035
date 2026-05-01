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
    python 5-evaluate/ragas_evaluator.py --judge-model gpt-5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
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
from token_costing import aggregate_token_usage, token_usage_from_response_usage  # noqa: E402

# ── Azure OpenAI 客户端 ───────────────────────────────────────────────────────
try:
    from openai import AzureOpenAI, OpenAI
except ImportError:
    AzureOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(override=False)

_ANSWER_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
_ANSWER_API_KEY = os.getenv("FOUNDRY_PROJECT_API_KEY", "").strip()
_ANSWER_MODEL = os.getenv("FOUNDRY_PROJECT_DEPLOYMENT", "").strip()
_ANSWER_API_VER = os.getenv(
    "FOUNDRY_API_VERSION",
    os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
).strip()

_JUDGE_ENDPOINT = os.getenv("RAGAS_JUDGE_ENDPOINT", os.getenv("AZURE_OPENAI_ENDPOINT", "")).strip()
_JUDGE_API_KEY = os.getenv("RAGAS_JUDGE_API_KEY", os.getenv("AZURE_OPENAI_API_KEY", "")).strip()
_JUDGE_MODEL = os.getenv("RAGAS_JUDGE_MODEL", "gpt-5").strip()
_JUDGE_API_VER = os.getenv(
    "RAGAS_JUDGE_API_VERSION",
    os.getenv("AZURE_OPENAI_API_VERSION", _ANSWER_API_VER),
).strip()


def _make_responses_client(endpoint: str, api_key: str, api_version: str, *, label: str):
    if OpenAI is None:
        raise RuntimeError("openai package not installed")
    if not (endpoint and api_key):
        raise RuntimeError(
            f"Missing {label} credentials. "
            "Set the corresponding endpoint and API key in .env"
        )
    # gpt-5-mini on Azure AI Foundry only returns content via the Responses API;
    # chat.completions returns empty strings. Use OpenAI client at the *resource*
    # level with api-version as a default query parameter.
    endpoint = endpoint.rstrip("/")
    if "services.ai.azure.com" in endpoint:
        import re as _re
        m = _re.match(r"(https://[^/]+\.services\.ai\.azure\.com)", endpoint)
        resource_base = m.group(1) if m else endpoint
        return OpenAI(
            base_url=resource_base + "/openai/",
            api_key=api_key,
            default_query={"api-version": "2025-03-01-preview"},
            timeout=120.0,
            max_retries=2,
        )
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
        timeout=120.0,
        max_retries=2,
    )


def _make_answer_client(answer_model: str):
    if not answer_model:
        raise RuntimeError("Missing answer model. Set FOUNDRY_PROJECT_DEPLOYMENT in .env or pass --answer-model.")
    return _make_responses_client(
        _ANSWER_ENDPOINT,
        _ANSWER_API_KEY,
        _ANSWER_API_VER,
        label="answer model",
    )


def _make_judge_client(judge_model: str):
    if not judge_model:
        raise RuntimeError("Missing judge model. Set RAGAS_JUDGE_MODEL in .env or pass --judge-model.")
    return _make_responses_client(
        _JUDGE_ENDPOINT,
        _JUDGE_API_KEY,
        _JUDGE_API_VER,
        label="judge model",
    )


def _response_extra_kwargs(model: str) -> dict[str, Any]:
    normalized = (model or "").strip().lower()
    if normalized.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"reasoning": {"effort": "low"}}
    return {}


# ── Golden Test Set ───────────────────────────────────────────────────────────
# 每条包含 query / city / ground_truth（人工写的标准答案关键点）
# ground_truth 不需要是完整段落，列出必须覆盖的事实点即可
_GOLDEN_CASES_PATH = Path(__file__).with_name("golden_cases.json")


def load_golden_cases(path: Path = _GOLDEN_CASES_PATH) -> list[dict[str, Any]]:
    """Load and validate the external golden test set."""
    with path.open("r", encoding="utf-8") as f:
        cases = json.load(f)

    if not isinstance(cases, list):
        raise ValueError(f"{path} must contain a JSON list")

    required = {"id", "query", "city", "ground_truth"}
    seen_ids: set[str] = set()
    for idx, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Case #{idx} must be an object")
        missing = required - set(case)
        if missing:
            raise ValueError(f"Case #{idx} missing required fields: {sorted(missing)}")
        for key in required:
            if not isinstance(case[key], str) or not case[key].strip():
                raise ValueError(f"Case #{idx} field {key!r} must be a non-empty string")
        if case["id"] in seen_ids:
            raise ValueError(f"Duplicate golden case id: {case['id']}")
        seen_ids.add(case["id"])

    return cases


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


def _generate_answer(client, model: str, query: str, context_chunks: list[str]) -> tuple[str, dict]:
    """用检索上下文生成回答，返回 (answer, token_usage)。"""
    if not context_chunks:
        return "暂无相关信息。", {}

    context_text = "\n\n---\n\n".join(context_chunks[:5])
    messages = [
        {
            "role": "developer",
            "content": "你是一个旅行助手，请仅根据以下检索到的参考资料回答用户问题，不要添加资料中没有的信息。请完整但精炼地回答；如果资料缺少某个问题的关键信息，明确说明未检索到。",
        },
        {
            "role": "user",
            "content": f"参考资料：\n{context_text}\n\n问题：{query}",
        },
    ]
    resp = client.responses.create(
        model=model,
        input=messages,
        max_output_tokens=1600,
        **_response_extra_kwargs(model),
    )
    answer = (resp.output_text or "").strip()
    usage = token_usage_from_response_usage(resp.usage, model=model)
    return answer, usage


def _judge(client, model: str, query: str, context_chunks: list[str], answer: str, ground_truth: str) -> dict:
    """让 LLM 作 Judge，返回三维评分 dict。"""
    context_text = "\n\n---\n\n".join(context_chunks[:5]) if context_chunks else "（无检索结果）"
    base_prompt = _JUDGE_PROMPT.format(
        query=query,
        context=context_text,
        answer=answer,
        ground_truth=ground_truth,
    )

    raw = ""
    scores: dict[str, Any] = {}
    usage_records: list[dict[str, Any]] = []
    import re

    for attempt in range(2):
        prompt = base_prompt
        if attempt:
            prompt += "\n\n注意：上一次输出未能解析为 JSON。本次只能输出一个 JSON object，不要输出 Markdown 或解释。"

        resp = client.responses.create(
            model=model,
            input=[
                {"role": "developer", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_output_tokens=2000,
            **_response_extra_kwargs(model),
        )
        raw = (resp.output_text or "").strip()
        usage_records.append(token_usage_from_response_usage(resp.usage, model=model))

        try:
            scores = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    scores = json.loads(m.group())
                except json.JSONDecodeError:
                    scores = {}
        if isinstance(scores, dict) and {"faithfulness", "answer_relevancy", "context_precision"} <= set(scores):
            break

    usage = aggregate_token_usage(usage_records, source="judge_retries")
    if not scores:
        scores = {
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "context_precision": 0.0,
            "reasoning": f"Judge output parse failed; raw output prefix: {raw[:200]}",
        }
    return {"scores": scores, "token_usage": usage, "raw_judge_output": raw}


def run_evaluation(
    cases: list[dict],
    top_k: int = 5,
    delay_s: float = 1.0,
    answer_model: str = _ANSWER_MODEL,
    judge_model: str = _JUDGE_MODEL,
) -> dict:
    """
    对所有 case 跑完整的 Retrieve → Generate → Judge 流程。
    返回汇总结果 dict。
    """
    answer_client = _make_answer_client(answer_model)
    judge_client = _make_judge_client(judge_model)

    results = []
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
        generate_error = ""
        try:
            answer, gen_usage = _generate_answer(answer_client, answer_model, query, context_chunks)
        except Exception as exc:
            generate_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            answer = f"生成失败：{generate_error}"
            gen_usage = {}
        gen_ms = int((time.monotonic() - t0) * 1000)
        all_token_usages.append(gen_usage)
        print(f"  生成: {len(answer)} 字 ({gen_ms}ms)", flush=True)
        if generate_error:
            print(f"  生成错误: {generate_error}", flush=True)

        # Step 3: Judge
        t0 = time.monotonic()
        judge_error = ""
        try:
            judge_result = _judge(judge_client, judge_model, query, context_chunks, answer, ground_truth)
        except Exception as exc:
            judge_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            judge_result = {
                "scores": {
                    "faithfulness": 0.0,
                    "answer_relevancy": 0.0,
                    "context_precision": 0.0,
                    "reasoning": f"Judge failed: {judge_error}",
                },
                "token_usage": {},
                "raw_judge_output": "",
            }
        judge_ms = int((time.monotonic() - t0) * 1000)
        all_token_usages.append(judge_result["token_usage"])
        if judge_error:
            print(f"  Judge 错误: {judge_error}", flush=True)

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
            "answer_model": answer_model,
            "judge_model": judge_model,
            "answer": answer,
            "ground_truth": ground_truth,
            "scores": {
                "faithfulness": faithfulness,
                "answer_relevancy": answer_relevancy,
                "context_precision": context_precision,
            },
            "reasoning": reasoning,
            "errors": {
                "generate": generate_error,
                "judge": judge_error,
            },
            "latency_ms": {
                "retrieve": retrieve_ms,
                "generate": gen_ms,
                "judge": judge_ms,
            },
            "token_usage": aggregate_token_usage(
                [gen_usage, judge_result["token_usage"]],
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

    token_summary = aggregate_token_usage(all_token_usages, source="ragas_evaluator")
    token_summary["total_input_tokens"] = token_summary["input_tokens"]
    token_summary["total_output_tokens"] = token_summary["output_tokens"]

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model": answer_model,
        "answer_model": answer_model,
        "judge_model": judge_model,
        "models": {
            "answer": answer_model,
            "judge": judge_model,
        },
        "case_count": n,
        "top_k": top_k,
        "avg_scores": {
            "faithfulness": round(avg_faithfulness, 4),
            "answer_relevancy": round(avg_relevancy, 4),
            "context_precision": round(avg_precision, 4),
            "overall": round(avg_all, 4),
        },
        "token_usage": token_summary,
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
    print(f"  Answer 模型: {summary.get('answer_model', summary.get('model'))}")
    print(f"  Judge 模型: {summary.get('judge_model', summary.get('model'))}")
    print(f"  测试集: {n} 条  |  Top-K: {summary['top_k']}")
    print(f"  时间: {summary['timestamp']}")
    print()

    def _mark(passed: bool) -> str:
        return "PASS" if passed else "FAIL"

    print(f"  {'指标':<20} {'均值':>8}  {'目标':>6}  状态")
    print("  " + "-" * 44)
    print(f"  {'Faithfulness':<20} {avg['faithfulness']:>8.4f}  {'>=0.70':>6}  {_mark(thr['faithfulness']['pass'])}")
    print(f"  {'Answer Relevancy':<20} {avg['answer_relevancy']:>8.4f}  {'>=0.70':>6}  {_mark(thr['answer_relevancy']['pass'])}")
    print(f"  {'Context Precision':<20} {avg['context_precision']:>8.4f}  {'>=0.60':>6}  {_mark(thr['context_precision']['pass'])}")
    print(f"  {'Overall':<20} {avg['overall']:>8.4f}  {'>=0.67':>6}  {_mark(thr['overall']['pass'])}")
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
    parser.add_argument("--golden-cases", type=str, default=str(_GOLDEN_CASES_PATH), help="golden cases JSON 路径")
    parser.add_argument("--answer-model", type=str, default=_ANSWER_MODEL, help="Answer 生成模型部署名")
    parser.add_argument("--judge-model", type=str, default=_JUDGE_MODEL, help="LLM-as-Judge 模型部署名")
    args = parser.parse_args()

    all_cases = load_golden_cases(Path(args.golden_cases))
    cases = all_cases[: args.cases] if args.cases > 0 else all_cases
    print(
        f"开始 RAGAS 评测: {len(cases)} 条 case，top_k={args.top_k}，"
        f"answer_model={args.answer_model}，judge_model={args.judge_model}"
    )

    summary = run_evaluation(
        cases,
        top_k=args.top_k,
        delay_s=args.delay,
        answer_model=args.answer_model,
        judge_model=args.judge_model,
    )
    print_report(summary)

    out_path = Path(args.out) if args.out else Path(__file__).parent / "ragas_result.json"
    export_json(summary, out_path)
