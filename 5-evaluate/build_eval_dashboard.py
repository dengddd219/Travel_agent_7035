# 如需更新数据运行
# python 5-evaluate/build_eval_dashboard.py


# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import json
import os
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from token_costing import aggregate_token_usage, with_token_cost  # noqa: E402


DEFAULT_MODEL = "gpt-5-mini"
SLA_MS = 30_000
KPI_DRAG_SCRIPT = """
  <script>
    (() => {
      const grid = document.querySelector(".kpi-grid");
      if (!grid) return;

      const storageKey = "travel-agent-eval-dashboard-kpi-order";
      let draggedCard = null;

      const cardId = (card) => {
        const existing = card.dataset.kpiId;
        if (existing) return existing;
        const title = card.querySelector(".kpi-title")?.textContent || "";
        const id = title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
        card.dataset.kpiId = id;
        return id;
      };

      const cards = () => Array.from(grid.querySelectorAll(".kpi"));

      const saveOrder = () => {
        try {
          localStorage.setItem(storageKey, JSON.stringify(cards().map(cardId)));
        } catch (_error) {
        }
      };

      const restoreOrder = () => {
        try {
          const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
          saved.forEach((id) => {
            const card = cards().find((item) => cardId(item) === id);
            if (card) grid.appendChild(card);
          });
        } catch (_error) {
        }
      };

      restoreOrder();

      cards().forEach((card) => {
        card.draggable = true;
        card.addEventListener("dragstart", (event) => {
          draggedCard = card;
          card.classList.add("is-dragging");
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", cardId(card));
        });
        card.addEventListener("dragend", () => {
          card.classList.remove("is-dragging");
          draggedCard = null;
          saveOrder();
        });
      });

      grid.addEventListener("dragover", (event) => {
        if (!draggedCard) return;
        event.preventDefault();
        const target = event.target.closest(".kpi");
        if (!target || target === draggedCard || !grid.contains(target)) return;

        const rect = target.getBoundingClientRect();
        const sameRow = event.clientY >= rect.top && event.clientY <= rect.bottom;
        const insertAfter = sameRow
          ? event.clientX > rect.left + rect.width / 2
          : event.clientY > rect.top + rect.height / 2;

        if (insertAfter) {
          target.after(draggedCard);
        } else {
          target.before(draggedCard);
        }
      });

      grid.addEventListener("drop", (event) => {
        event.preventDefault();
        saveOrder();
      });
    })();
  </script>
""".rstrip()
CITY_LABELS = {
    "\u5317\u4eac": "Beijing",
    "\u5317\u4eac\u5e02": "Beijing",
    "\u4e0a\u6d77": "Shanghai",
    "\u4e0a\u6d77\u5e02": "Shanghai",
    "\u6210\u90fd": "Chengdu",
    "\u6210\u90fd\u5e02": "Chengdu",
    "\u9999\u6e2f": "Hong Kong",
    "\u53a6\u95e8": "Xiamen",
    "\u53a6\u95e8\u5e02": "Xiamen",
    "\u676d\u5dde": "Hangzhou",
    "\u676d\u5dde\u5e02": "Hangzhou",
    "\u5e7f\u5dde": "Guangzhou",
    "\u5e7f\u5dde\u5e02": "Guangzhou",
    "\u6df1\u5733": "Shenzhen",
    "\u6df1\u5733\u5e02": "Shenzhen",
    "\u897f\u5b89": "Xian",
    "\u897f\u5b89\u5e02": "Xian",
    "\u5357\u4eac": "Nanjing",
    "\u5357\u4eac\u5e02": "Nanjing",
    "\u91cd\u5e86": "Chongqing",
    "\u91cd\u5e86\u5e02": "Chongqing",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _seconds(ms: float) -> str:
    return f"{ms / 1000:.1f}s"


def _money_usd(value: float) -> str:
    return f"${value:.6f}".rstrip("0").rstrip(".")


def _money_cny(value: float) -> str:
    return f"¥{value:.4f}".rstrip("0").rstrip(".")


def _num(value: float | int) -> str:
    return f"{value:,}"


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * 0.95)))
    return ordered[idx]


def _agent_name(record: dict[str, Any]) -> str:
    return str(record.get("agent") or "travel_planner_legacy")


def _city_label(value: Any) -> str:
    city = str(value or "-")
    return CITY_LABELS.get(city, city)


def _usage_with_cost(usage: dict[str, Any] | None) -> dict[str, Any]:
    usage = dict(usage or {})
    model = usage.get("model") or DEFAULT_MODEL
    return with_token_cost(usage, model=str(model))


def _usage_preserve_existing_cost(usage: dict[str, Any] | None) -> dict[str, Any]:
    usage = dict(usage or {})
    if isinstance(usage.get("estimated_cost"), dict):
        return usage
    return _usage_with_cost(usage)


def _extract_cost(usage: dict[str, Any] | None) -> dict[str, float]:
    normalized = _usage_with_cost(usage)
    cost = normalized.get("estimated_cost") or {}
    return {
        "usd": _safe_float(cost.get("total_usd")),
        "cny": _safe_float(cost.get("total_cny")),
    }


def summarize_trace() -> dict[str, Any]:
    path = EVAL_DIR / "eval_trace.jsonl"
    records = _read_jsonl(path)
    normalized_usages = [_usage_with_cost(item.get("token_usage")) for item in records]
    total_usage = aggregate_token_usage(normalized_usages, model=DEFAULT_MODEL, source="eval_dashboard_trace")
    total_cost = total_usage.get("estimated_cost") or {}

    latencies = [_safe_float((item.get("latency_ms") or {}).get("total")) for item in records]
    sla_violations = [item for item in records if _safe_float((item.get("latency_ms") or {}).get("total")) > SLA_MS]

    by_agent: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        by_agent.setdefault(_agent_name(item), []).append(item)

    agents: list[dict[str, Any]] = []
    for agent, items in sorted(by_agent.items()):
        agent_latencies = [_safe_float((item.get("latency_ms") or {}).get("total")) for item in items]
        agent_usage = aggregate_token_usage(
            [_usage_with_cost(item.get("token_usage")) for item in items],
            model=DEFAULT_MODEL,
            source=f"{agent}_dashboard_trace",
        )
        agent_cost = agent_usage.get("estimated_cost") or {}
        agent_sla = [item for item in items if _safe_float((item.get("latency_ms") or {}).get("total")) > SLA_MS]
        agents.append(
            {
                "name": agent,
                "records": len(items),
                "avg_latency_ms": _mean(agent_latencies),
                "p95_latency_ms": _p95(agent_latencies),
                "max_latency_ms": max(agent_latencies) if agent_latencies else 0.0,
                "sla_rate": len(agent_sla) / len(items) if items else 0.0,
                "tokens": _safe_int(agent_usage.get("total_tokens")),
                "input_tokens": _safe_int(agent_usage.get("input_tokens")),
                "output_tokens": _safe_int(agent_usage.get("output_tokens")),
                "cost_usd": _safe_float(agent_cost.get("total_usd")),
                "cost_cny": _safe_float(agent_cost.get("total_cny")),
            }
        )

    recent_turns: list[dict[str, Any]] = []
    for item in records[-12:]:
        usage = _usage_with_cost(item.get("token_usage"))
        cost = _extract_cost(usage)
        recent_turns.append(
            {
                "time": str(item.get("timestamp") or ""),
                "agent": _agent_name(item),
                "city": _city_label(item.get("city")),
                "turn": str(item.get("turn") or "-"),
                "latency_ms": _safe_float((item.get("latency_ms") or {}).get("total")),
                "tokens": _safe_int(usage.get("total_tokens")),
                "cost_usd": cost["usd"],
                "cost_cny": cost["cny"],
                "alerts": ", ".join(str(alert) for alert in item.get("alerts", [])) or "-",
            }
        )

    return {
        "path": path,
        "record_count": len(records),
        "total_tokens": _safe_int(total_usage.get("total_tokens")),
        "input_tokens": _safe_int(total_usage.get("input_tokens")),
        "output_tokens": _safe_int(total_usage.get("output_tokens")),
        "cost_usd": _safe_float(total_cost.get("total_usd")),
        "cost_cny": _safe_float(total_cost.get("total_cny")),
        "avg_latency_ms": _mean(latencies),
        "median_latency_ms": _median(latencies),
        "p95_latency_ms": _p95(latencies),
        "max_latency_ms": max(latencies) if latencies else 0.0,
        "sla_violations": len(sla_violations),
        "sla_rate": len(sla_violations) / len(records) if records else 0.0,
        "avg_cost_usd": _safe_float(total_cost.get("total_usd")) / len(records) if records else 0.0,
        "agents": agents,
        "recent_turns": recent_turns,
    }


def _select_companion_run() -> Path | None:
    preferred = EVAL_DIR / "companion_eval_runs" / "full_llm_k4" / "partial_summary.json"
    if preferred.exists():
        return preferred
    runs = sorted(
        (EVAL_DIR / "companion_eval_runs").glob("*/partial_summary.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return runs[0] if runs else None


def summarize_companion() -> dict[str, Any]:
    summary_path = _select_companion_run()
    if not summary_path:
        return {}

    summary = _read_json(summary_path)
    overall = summary.get("overall") or {}
    token_usage = _usage_with_cost(overall.get("token_usage"))
    cost = token_usage.get("estimated_cost") or {}
    run_dir = summary_path.parent
    trials = _read_jsonl(run_dir / "trial_results.jsonl")
    latencies = [_safe_float((item.get("latency_ms") or {}).get("total")) for item in trials]
    trial_costs = [_extract_cost(item.get("token_usage"))["usd"] for item in trials]

    failure_tags = summary.get("failure_tag_counts") or {}
    top_failures = sorted(
        [{"tag": str(tag), "count": _safe_int(count)} for tag, count in failure_tags.items()],
        key=lambda item: item["count"],
        reverse=True,
    )[:10]

    dimension_scores = overall.get("dimension_scores") or {}
    return {
        "run_name": run_dir.name,
        "path": summary_path,
        "task_count": _safe_int(overall.get("task_count")),
        "trial_count": _safe_int(overall.get("trial_count")),
        "k": _safe_int(overall.get("k")),
        "strict_success_rate": _safe_float(overall.get("strict_success_rate")),
        "failure_rate": 1.0 - _safe_float(overall.get("strict_success_rate")),
        "pass_at_k": _safe_float(overall.get("pass_at_k")),
        "pass_all_k": _safe_float(overall.get("pass_all_k")),
        "avg_at_k": _safe_float(overall.get("avg_at_k")),
        "avg_rubric_score": _safe_float(overall.get("avg_rubric_score")),
        "tool_success": _safe_float(overall.get("avg_tool_success")),
        "interaction_score": _safe_float(overall.get("avg_interaction_score")),
        "final_response_score": _safe_float(overall.get("avg_final_response_score")),
        "dimension_scores": {
            "interaction": _safe_float(dimension_scores.get("interaction")),
            "reasoning": _safe_float(dimension_scores.get("reasoning")),
            "tool": _safe_float(dimension_scores.get("tool")),
        },
        "progress": summary.get("progress") or {},
        "total_tokens": _safe_int(token_usage.get("total_tokens")),
        "avg_tokens_per_trial": _safe_float(overall.get("avg_tokens_per_trial")),
        "cost_usd": _safe_float(cost.get("total_usd")),
        "cost_cny": _safe_float(cost.get("total_cny")),
        "avg_latency_ms": _mean(latencies),
        "p95_latency_ms": _p95(latencies),
        "avg_cost_usd": _mean(trial_costs),
        "top_failures": top_failures,
    }


def _load_ragas_summary_prefix(text: str) -> dict[str, Any]:
    details_match = re.search(r'\n\s*"details"\s*:', text)
    if not details_match:
        return {}
    prefix = text[: details_match.start()].rstrip()
    if prefix.endswith(","):
        prefix = prefix[:-1]
    try:
        return json.loads(prefix + "\n}")
    except json.JSONDecodeError:
        return {}


def _regex_number(text: str, key: str) -> float:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*([0-9.]+)', text)
    return _safe_float(match.group(1)) if match else 0.0


def _regex_int(text: str, key: str) -> int:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(\d+)', text)
    return _safe_int(match.group(1)) if match else 0


def _regex_avg_latency(text: str, key: str) -> float:
    values = [_safe_float(item) for item in re.findall(rf'"{re.escape(key)}"\s*:\s*(\d+)', text)]
    return _mean(values)


def _select_ragas_result() -> Path | None:
    override_value = os.getenv("EVAL_DASHBOARD_RAGAS_RESULT", "").strip()
    if override_value:
        override = Path(override_value)
        if not override.is_absolute():
            override = EVAL_DIR / override
        if override.exists():
            return override
    results = sorted(EVAL_DIR.glob("ragas_result*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return results[0] if results else None


def summarize_ragas() -> dict[str, Any]:
    path = _select_ragas_result()
    if not path:
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    full_summary = _read_json(path)
    summary = full_summary or _load_ragas_summary_prefix(text)

    avg_scores = summary.get("avg_scores") or {}
    token_usage = _usage_preserve_existing_cost(summary.get("token_usage"))
    cost = token_usage.get("estimated_cost") or {}
    models = summary.get("models") or {}
    answer_model = summary.get("answer_model") or models.get("answer") or summary.get("model") or DEFAULT_MODEL
    judge_model = summary.get("judge_model") or models.get("judge") or summary.get("model") or answer_model
    retrieve_ms = _regex_avg_latency(text, "retrieve")
    generate_ms = _regex_avg_latency(text, "generate")
    judge_ms = _regex_avg_latency(text, "judge")
    details = summary.get("details") if isinstance(summary.get("details"), list) else []

    detail_rows: list[dict[str, Any]] = []
    by_city_map: dict[str, list[dict[str, Any]]] = {}
    for item in details:
        if not isinstance(item, dict):
            continue
        scores = item.get("scores") or {}
        faithfulness = _safe_float(scores.get("faithfulness"))
        relevancy = _safe_float(scores.get("answer_relevancy"))
        precision = _safe_float(scores.get("context_precision"))
        overall = (faithfulness + relevancy + precision) / 3
        row = {
            "id": str(item.get("id") or ""),
            "city": str(item.get("city") or "-"),
            "query": str(item.get("query") or ""),
            "faithfulness": faithfulness,
            "answer_relevancy": relevancy,
            "context_precision": precision,
            "overall": overall,
            "reasoning": str(item.get("reasoning") or ""),
        }
        detail_rows.append(row)
        by_city_map.setdefault(row["city"], []).append(row)

    by_city: list[dict[str, Any]] = []
    for city, items in sorted(by_city_map.items()):
        by_city.append(
            {
                "city": city,
                "case_count": len(items),
                "faithfulness": _mean([item["faithfulness"] for item in items]),
                "answer_relevancy": _mean([item["answer_relevancy"] for item in items]),
                "context_precision": _mean([item["context_precision"] for item in items]),
                "overall": _mean([item["overall"] for item in items]),
            }
        )
    by_city = sorted(by_city, key=lambda item: _safe_float(item.get("overall")), reverse=True)

    score_bands = [
        {"band": ">= 0.90", "count": sum(1 for item in detail_rows if item["overall"] >= 0.90)},
        {"band": "0.80 - 0.89", "count": sum(1 for item in detail_rows if 0.80 <= item["overall"] < 0.90)},
        {"band": "0.70 - 0.79", "count": sum(1 for item in detail_rows if 0.70 <= item["overall"] < 0.80)},
        {"band": "< 0.70", "count": sum(1 for item in detail_rows if item["overall"] < 0.70)},
    ]
    lowest_cases = sorted(detail_rows, key=lambda item: item["overall"])[:12]

    return {
        "path": path,
        "answer_model": str(answer_model),
        "judge_model": str(judge_model),
        "pricing_source": str(cost.get("pricing_source") or ""),
        "case_count": _safe_int(summary.get("case_count")) or _regex_int(text, "case_count"),
        "top_k": _safe_int(summary.get("top_k")) or _regex_int(text, "top_k"),
        "faithfulness": _safe_float(avg_scores.get("faithfulness")) or _regex_number(text, "faithfulness"),
        "answer_relevancy": _safe_float(avg_scores.get("answer_relevancy")) or _regex_number(text, "answer_relevancy"),
        "context_precision": _safe_float(avg_scores.get("context_precision")) or _regex_number(text, "context_precision"),
        "overall": _safe_float(avg_scores.get("overall")) or _regex_number(text, "overall"),
        "total_tokens": _safe_int(token_usage.get("total_tokens")) or _regex_int(text, "total_tokens"),
        "input_tokens": _safe_int(token_usage.get("input_tokens")) or _regex_int(text, "input_tokens"),
        "output_tokens": _safe_int(token_usage.get("output_tokens")) or _regex_int(text, "output_tokens"),
        "cost_usd": _safe_float(cost.get("total_usd")),
        "cost_cny": _safe_float(cost.get("total_cny")),
        "retrieve_ms": retrieve_ms,
        "generate_ms": generate_ms,
        "judge_ms": judge_ms,
        "avg_total_latency_ms": retrieve_ms + generate_ms + judge_ms,
        "by_city": by_city,
        "score_bands": score_bands,
        "lowest_cases": lowest_cases,
    }


def _select_rag_retrieval_report() -> Path | None:
    override_value = os.getenv("EVAL_DASHBOARD_RAG_RETRIEVAL_REPORT", "").strip()
    if override_value:
        override = Path(override_value)
        if not override.is_absolute():
            override = ROOT / override
        if override.exists():
            return override

    candidates = [
        ROOT / "1-rag_pipeline_delivery" / "evaluation_report.md",
        EVAL_DIR / "RAG_EVALUATION_GUIDE.md",
    ]
    return next((path for path in candidates if path.exists()), None)


def _markdown_section(text: str, heading_pattern: str) -> str:
    match = re.search(heading_pattern, text)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"\n##\s+", text[start:])
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end]


def _parse_markdown_table(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells):
            continue
        rows.append(cells)
    return rows


def _markdown_boldless(value: str) -> str:
    return re.sub(r"\*\*", "", value).strip()


def _percentish_to_float(value: Any) -> float:
    text = _markdown_boldless(str(value or "")).strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    number = _safe_float(match.group(0))
    if "%" in text:
        return number / 100.0
    return number


def _parse_hit_fraction(value: Any) -> tuple[int, int, float]:
    text = _markdown_boldless(str(value or ""))
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if not match:
        score = _percentish_to_float(text)
        return 0, 0, score
    hits = _safe_int(match.group(1))
    total = _safe_int(match.group(2))
    return hits, total, hits / total if total else 0.0


def summarize_rag_retrieval() -> dict[str, Any]:
    path = _select_rag_retrieval_report()
    if not path:
        return {}

    text = path.read_text(encoding="utf-8", errors="replace")
    generated_match = re.search(r"生成时间:\s*([^\n>]+)", text)
    version_match = re.search(r"最新版本:\s*([^\n>]+)", text)
    generated_date = generated_match.group(1).strip() if generated_match else ""
    latest_version = version_match.group(1).strip() if version_match else ""

    current_section = _markdown_section(text, r"##\s+三、当前最优结果")
    current_rows = _parse_markdown_table(current_section)
    current_metrics: dict[str, str] = {}
    for cells in current_rows[1:]:
        if len(cells) >= 2:
            current_metrics[_markdown_boldless(cells[0])] = _markdown_boldless(cells[1])

    detail_match = re.search(r"###\s+各类别详细结果(?P<body>.*?)(?:\n##|\n###\s+V7|\Z)", text, re.S)
    detail_rows_raw = _parse_markdown_table(detail_match.group("body") if detail_match else "")
    details: list[dict[str, Any]] = []
    for cells in detail_rows_raw[1:]:
        if len(cells) < 4:
            continue
        category = _markdown_boldless(cells[0])
        query = _markdown_boldless(cells[1])
        hits, total, hit_rate = _parse_hit_fraction(cells[2])
        city, _, topic = category.partition("-")
        details.append(
            {
                "category": category,
                "city": city or "-",
                "topic": topic or category,
                "query": query,
                "hits": hits,
                "total": total,
                "hit_rate": hit_rate,
                "mrr": _percentish_to_float(cells[3]),
            }
        )

    by_city_map: dict[str, list[dict[str, Any]]] = {}
    for item in details:
        by_city_map.setdefault(str(item["city"]), []).append(item)

    by_city: list[dict[str, Any]] = []
    for city, items in sorted(by_city_map.items()):
        by_city.append(
            {
                "city": city,
                "case_count": len(items),
                "hit_rate": _mean([_safe_float(item["hit_rate"]) for item in items]),
                "mrr": _mean([_safe_float(item["mrr"]) for item in items]),
            }
        )

    version_section = _markdown_section(text, r"##\s+四、优化历程")
    version_rows_raw = _parse_markdown_table(version_section)
    version_history: list[dict[str, Any]] = []
    for cells in version_rows_raw[1:]:
        if len(cells) < 4:
            continue
        version_history.append(
            {
                "version": _markdown_boldless(cells[0]),
                "change": _markdown_boldless(cells[1]),
                "hit_rate": _percentish_to_float(cells[2]),
                "mrr": _percentish_to_float(cells[3]),
                "note": _markdown_boldless(cells[4]) if len(cells) > 4 else "",
            }
        )

    top_k = max((_safe_int(item["total"]) for item in details), default=5)
    avg_hit_rate = _percentish_to_float(current_metrics.get("平均 Hit Rate@5"))
    avg_mrr = _percentish_to_float(current_metrics.get("平均 MRR"))
    if details:
        avg_hit_rate = avg_hit_rate or _mean([_safe_float(item["hit_rate"]) for item in details])
        avg_mrr = avg_mrr or _mean([_safe_float(item["mrr"]) for item in details])

    weak_cases = sorted(details, key=lambda item: (_safe_float(item["hit_rate"]), _safe_float(item["mrr"])))[:8]

    return {
        "path": path,
        "generated_date": generated_date,
        "latest_version": latest_version or (version_history[-1]["version"] if version_history else ""),
        "case_count": len(details),
        "top_k": top_k,
        "avg_hit_rate": avg_hit_rate,
        "avg_mrr": avg_mrr,
        "best_params": current_metrics.get("最优参数", ""),
        "by_city": by_city,
        "weak_cases": weak_cases,
        "version_history": version_history,
    }


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _bar_rows(
    rows: list[dict[str, Any]],
    *,
    label_key: str,
    value_key: str,
    display,
    color_class: str = "bar-blue",
) -> str:
    max_value = max((_safe_float(row.get(value_key)) for row in rows), default=0.0)
    chunks: list[str] = []
    for row in rows:
        value = _safe_float(row.get(value_key))
        width = 0.0 if max_value <= 0 else max(4.0, value / max_value * 100)
        chunks.append(
            f"""
            <div class="bar-row">
              <div class="bar-label">{_escape(row.get(label_key))}</div>
              <div class="bar-track"><div class="bar-fill {color_class}" style="width: {width:.1f}%"></div></div>
              <div class="bar-value">{_escape(display(value, row))}</div>
            </div>
            """
        )
    return "\n".join(chunks) or '<div class="empty">No data</div>'


def _score_rows(rows: list[tuple[str, float]], color_class: str = "bar-teal") -> str:
    return _bar_rows(
        [{"label": label, "value": value} for label, value in rows],
        label_key="label",
        value_key="value",
        display=lambda value, _row: _percent(value),
        color_class=color_class,
    )


def _score_distribution_pie(rows: list[dict[str, Any]]) -> str:
    total = sum(_safe_int(row.get("count")) for row in rows)
    if total <= 0:
        return '<div class="empty">No data</div>'

    palette = ["donut-green", "donut-teal", "donut-amber", "donut-red"]
    segments: list[str] = []
    legend_rows: list[str] = []
    offset = 0.0
    for index, row in enumerate(rows):
        count = _safe_int(row.get("count"))
        pct = count / total * 100
        color_class = palette[index % len(palette)]
        segments.append(
            f"""
            <circle class="donut-segment {color_class}" cx="90" cy="90" r="64"
              pathLength="100" stroke-dasharray="{pct:.4f} {100 - pct:.4f}"
              stroke-dashoffset="{-offset:.4f}" transform="rotate(-90 90 90)">
              <title>{_escape(row.get("band"))}: {count} cases ({pct:.1f}%)</title>
            </circle>
            """
        )
        legend_rows.append(
            f"""
            <div class="donut-legend-row">
              <span class="donut-swatch {color_class}"></span>
              <span class="donut-band">{_escape(row.get("band"))}</span>
              <span class="donut-value">{_escape(f"{count} / {pct:.1f}%")}</span>
            </div>
            """
        )
        offset += pct

    return f"""
    <div class="donut-wrap">
      <svg class="donut-chart" viewBox="0 0 180 180" role="img" aria-label="RAGAS score distribution pie chart">
        <circle class="donut-bg" cx="90" cy="90" r="64"></circle>
        {"".join(segments)}
        <text class="donut-total" x="90" y="84" text-anchor="middle">{_escape(total)}</text>
        <text class="donut-caption" x="90" y="105" text-anchor="middle">cases</text>
      </svg>
      <div class="donut-legend">
        {"".join(legend_rows)}
      </div>
    </div>
    """


def _score_class(value: float) -> str:
    if value >= 0.9:
        return "score-good"
    if value >= 0.7:
        return "score-mid"
    return "score-low"


def _score_pill(value: float) -> str:
    return f'<span class="score-pill {_score_class(value)}">{_escape(f"{value:.2f}")}</span>'


def _ragas_city_rows(rows: list[dict[str, Any]]) -> str:
    html_rows: list[str] = []
    for row in rows:
        overall = _safe_float(row.get("overall"))
        html_rows.append(
            f"""
            <tr>
              <td>{_escape(row.get("city"))}</td>
              <td>{_escape(row.get("case_count"))}</td>
              <td>{_score_pill(overall)}</td>
              <td>{_score_pill(_safe_float(row.get("faithfulness")))}</td>
              <td>{_score_pill(_safe_float(row.get("answer_relevancy")))}</td>
              <td>{_score_pill(_safe_float(row.get("context_precision")))}</td>
            </tr>
            """
        )
    return "\n".join(html_rows) or '<tr><td colspan="6">No data</td></tr>'


def _ragas_low_case_rows(rows: list[dict[str, Any]]) -> str:
    html_rows: list[str] = []
    for row in rows:
        overall = _safe_float(row.get("overall"))
        html_rows.append(
            f"""
            <tr>
              <td><code>{_escape(row.get("id"))}</code></td>
              <td>{_escape(row.get("city"))}</td>
              <td>{_escape(row.get("query"))}</td>
              <td>{_score_pill(overall)}</td>
              <td>{_score_pill(_safe_float(row.get("faithfulness")))}</td>
              <td>{_score_pill(_safe_float(row.get("answer_relevancy")))}</td>
              <td>{_score_pill(_safe_float(row.get("context_precision")))}</td>
              <td>{_escape(str(row.get("reasoning") or "")[:140])}</td>
            </tr>
            """
        )
    return "\n".join(html_rows) or '<tr><td colspan="8">No data</td></tr>'


def _rag_retrieval_trend_chart(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No data</div>'

    width = 720
    height = 320
    left = 54
    right = 24
    top = 24
    bottom = 52
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_step = plot_width / max(1, len(rows) - 1)

    def point(row_index: int, value: float) -> tuple[float, float]:
        x = left + row_index * x_step
        y = top + plot_height * (1.0 - max(0.0, min(1.0, value)))
        return x, y

    hit_points = [point(index, _safe_float(row.get("hit_rate"))) for index, row in enumerate(rows)]
    mrr_points = [point(index, _safe_float(row.get("mrr"))) for index, row in enumerate(rows)]
    hit_polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in hit_points)
    mrr_polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in mrr_points)

    grid_lines: list[str] = []
    for tick in [0.0, 0.25, 0.5, 0.75, 1.0]:
        y = top + plot_height * (1.0 - tick)
        grid_lines.append(
            f"""
            <line class="chart-grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"></line>
            <text class="chart-y-label" x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">{_escape(_percent(tick))}</text>
            """
        )

    x_labels: list[str] = []
    hit_circles: list[str] = []
    mrr_circles: list[str] = []
    for index, row in enumerate(rows):
        version = str(row.get("version") or f"V{index + 1}")
        x, _ = point(index, 0)
        x_labels.append(
            f'<text class="chart-x-label" x="{x:.1f}" y="{height - 20}" text-anchor="middle">{_escape(version)}</text>'
        )
        hit_x, hit_y = hit_points[index]
        mrr_x, mrr_y = mrr_points[index]
        hit_value = _safe_float(row.get("hit_rate"))
        mrr_value = _safe_float(row.get("mrr"))
        hit_circles.append(
            f"""
            <circle class="chart-point chart-hit-point" cx="{hit_x:.1f}" cy="{hit_y:.1f}" r="4.5">
              <title>{_escape(version)} Hit Rate@5: {_percent(hit_value)}</title>
            </circle>
            """
        )
        mrr_circles.append(
            f"""
            <circle class="chart-point chart-mrr-point" cx="{mrr_x:.1f}" cy="{mrr_y:.1f}" r="4.5">
              <title>{_escape(version)} MRR: {mrr_value:.2f}</title>
            </circle>
            """
        )

    latest = rows[-1]
    return f"""
    <div class="line-chart-wrap">
      <div class="chart-legend" aria-hidden="true">
        <span><i class="legend-swatch legend-hit"></i>Hit Rate@5</span>
        <span><i class="legend-swatch legend-mrr"></i>MRR</span>
      </div>
      <svg class="line-chart" viewBox="0 0 {width} {height}" role="img" aria-label="RAG optimization trend: Hit Rate@5 and MRR">
        <line class="chart-axis" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"></line>
        <line class="chart-axis" x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}"></line>
        {"".join(grid_lines)}
        <polyline class="chart-line chart-hit-line" points="{hit_polyline}"></polyline>
        <polyline class="chart-line chart-mrr-line" points="{mrr_polyline}"></polyline>
        {"".join(hit_circles)}
        {"".join(mrr_circles)}
        {"".join(x_labels)}
      </svg>
      <div class="chart-summary">
        Latest {_escape(latest.get("version", "-"))}: Hit Rate@5 {_escape(_percent(_safe_float(latest.get("hit_rate"))))}; MRR {_escape(f"{_safe_float(latest.get('mrr')):.2f}")}
      </div>
    </div>
    """


def _kpi(title: str, value: str, meta: str, tone: str = "blue") -> str:
    return f"""
    <section class="kpi kpi-{tone}">
      <div class="kpi-title">{_escape(title)}</div>
      <div class="kpi-value">{_escape(value)}</div>
      <div class="kpi-meta">{_escape(meta)}</div>
    </section>
    """


def _agent_kpis(agents: list[dict[str, Any]]) -> list[str]:
    labels = {
        "companion": "Companion",
        "travel_planner": "Travel Planner",
        "travel_planner_legacy": "Legacy",
    }
    tones = {
        "companion": "teal",
        "travel_planner": "blue",
        "travel_planner_legacy": "purple",
    }
    rows = {str(row.get("name")): row for row in agents}
    cards: list[str] = []
    for key in ["companion", "travel_planner", "travel_planner_legacy"]:
        row = rows.get(key)
        if not row:
            continue
        records = _safe_int(row.get("records"))
        cards.append(
            _kpi(
                f"{labels[key]} Avg Latency",
                _seconds(row.get("avg_latency_ms", 0.0)),
                f"{records} records, SLA timeout {_percent(row.get('sla_rate', 0.0))}",
                tones[key],
            )
        )
    for key in ["companion", "travel_planner", "travel_planner_legacy"]:
        row = rows.get(key)
        if not row:
            continue
        records = _safe_int(row.get("records"))
        tokens = _safe_int(row.get("tokens"))
        avg_tokens = round(tokens / records) if records else 0
        cards.append(
            _kpi(
                f"{labels[key]} Avg Tokens",
                f"{_num(avg_tokens)} tok/turn",
                f"{_num(tokens)} tok / {records} records",
                "amber",
            )
        )
    return cards


def _recent_rows(rows: list[dict[str, Any]]) -> str:
    html_rows: list[str] = []
    for row in reversed(rows):
        html_rows.append(
            f"""
            <tr>
              <td>{_escape(row["agent"])}</td>
              <td>{_escape(row["city"])}</td>
              <td>{_escape(row["turn"])}</td>
              <td>{_escape(_seconds(row["latency_ms"]))}</td>
              <td>{_escape(_num(row["tokens"]))}</td>
              <td>{_escape(_money_usd(row["cost_usd"]))} / {_escape(_money_cny(row["cost_cny"]))}</td>
              <td>{_escape(row["alerts"])}</td>
            </tr>
            """
        )
    return "\n".join(html_rows) or '<tr><td colspan="7">No data</td></tr>'


def _agent_rows(rows: list[dict[str, Any]]) -> str:
    html_rows: list[str] = []
    for row in rows:
        html_rows.append(
            f"""
            <tr>
              <td>{_escape(row["name"])}</td>
              <td>{_escape(row["records"])}</td>
              <td>{_escape(_seconds(row["avg_latency_ms"]))}</td>
              <td>{_escape(_seconds(row["p95_latency_ms"]))}</td>
              <td>{_escape(_percent(row["sla_rate"]))}</td>
              <td>{_escape(_num(row["tokens"]))}</td>
              <td>{_escape(_money_usd(row["cost_usd"]))}</td>
            </tr>
            """
        )
    return "\n".join(html_rows) or '<tr><td colspan="7">No data</td></tr>'


def _rag_weak_rows(rows: list[dict[str, Any]]) -> str:
    html_rows: list[str] = []
    for row in rows:
        total = _safe_int(row.get("total"))
        hit_value = f"{_safe_int(row.get('hits'))}/{total}" if total else _percent(_safe_float(row.get("hit_rate")))
        html_rows.append(
            f"""
            <tr>
              <td>{_escape(row.get("category"))}</td>
              <td>{_escape(row.get("query"))}</td>
              <td>{_escape(hit_value)}</td>
              <td>{_escape(f"{_safe_float(row.get('mrr')):.2f}")}</td>
            </tr>
            """
        )
    return "\n".join(html_rows) or '<tr><td colspan="4">No data</td></tr>'


def _rag_version_rows(rows: list[dict[str, Any]]) -> str:
    html_rows: list[str] = []
    for row in rows:
        html_rows.append(
            f"""
            <tr>
              <td>{_escape(row.get("version"))}</td>
              <td>{_escape(_percent(_safe_float(row.get("hit_rate"))))}</td>
              <td>{_escape(f"{_safe_float(row.get('mrr')):.2f}")}</td>
              <td>{_escape(row.get("change"))}</td>
            </tr>
            """
        )
    return "\n".join(html_rows) or '<tr><td colspan="4">No data</td></tr>'


def _source_list(trace: dict[str, Any], companion: dict[str, Any], ragas: dict[str, Any], rag_retrieval: dict[str, Any]) -> str:
    sources = [
        ("Online trace", trace.get("path")),
        ("Companion benchmark", companion.get("path")),
        ("RAGAS result", ragas.get("path")),
        ("RAG retrieval report", rag_retrieval.get("path")),
    ]
    items = []
    for label, path in sources:
        if path:
            rel = Path(path).resolve().relative_to(ROOT)
            items.append(f"<li><span>{_escape(label)}</span><code>{_escape(rel)}</code></li>")
    return "\n".join(items)


def build_html() -> str:
    trace = summarize_trace()
    companion = summarize_companion()
    ragas = summarize_ragas()
    rag_retrieval = summarize_rag_retrieval()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    completion = _safe_float((companion.get("progress") or {}).get("completion_rate"))
    completed_trials = _safe_int((companion.get("progress") or {}).get("completed_trials"))
    total_trials = _safe_int((companion.get("progress") or {}).get("total_trials"))

    kpis = "\n".join(
        [
            _kpi("Online Records", _num(trace["record_count"]), f"SLA timeout rate {_percent(trace['sla_rate'])}", "blue"),
            _kpi("Avg Response Time", _seconds(trace["avg_latency_ms"]), f"P95 {_seconds(trace['p95_latency_ms'])}", "teal"),
            _kpi("Total Tokens", _num(trace["total_tokens"]), f"Input {_num(trace['input_tokens'])} / Output {_num(trace['output_tokens'])}", "amber"),
            _kpi("Estimated Cost", f"{_money_usd(trace['cost_usd'])} / {_money_cny(trace['cost_cny'])}", f"Avg {_money_usd(trace['avg_cost_usd'])}/turn", "green"),
            *_agent_kpis(trace["agents"]),
            _kpi("Strict Resolution Rate", _percent(companion.get("strict_success_rate", 0.0)), f"Pass@{companion.get('k', 0)} {_percent(companion.get('pass_at_k', 0.0))}", "purple"),
            _kpi("Task Failure Rate", _percent(companion.get("failure_rate", 0.0)), f"{companion.get('trial_count', 0)} trials / {companion.get('task_count', 0)} tasks", "red"),
            _kpi(
                "RAGAS Overall",
                _percent(ragas.get("overall", 0.0)),
                f"{ragas.get('case_count', 0)} cases, {ragas.get('answer_model', DEFAULT_MODEL)} judged by {ragas.get('judge_model', DEFAULT_MODEL)}",
                "blue",
            ),
            _kpi(
                "RAGAS Cost",
                f"{_money_usd(ragas.get('cost_usd', 0.0))} / {_money_cny(ragas.get('cost_cny', 0.0))}",
                f"Input {_num(ragas.get('input_tokens', 0))} / Output {_num(ragas.get('output_tokens', 0))}",
                "green",
            ),
            _kpi(
                f"RAG Hit Rate@{rag_retrieval.get('top_k', 5)}",
                _percent(rag_retrieval.get("avg_hit_rate", 0.0)),
                f"{rag_retrieval.get('case_count', 0)} golden queries, {rag_retrieval.get('latest_version', '-')}",
                "teal",
            ),
            _kpi(
                "RAG Retrieval MRR",
                f"{_safe_float(rag_retrieval.get('avg_mrr')):.2f}",
                f"Best params: {rag_retrieval.get('best_params', '-')}",
                "amber",
            ),
        ]
    )

    latency_bars = _bar_rows(
        trace["agents"],
        label_key="name",
        value_key="avg_latency_ms",
        display=lambda value, _row: _seconds(value),
        color_class="bar-blue",
    )
    token_bars = _bar_rows(
        trace["agents"],
        label_key="name",
        value_key="tokens",
        display=lambda value, row: f"{_num(int(value))} tok / {_money_usd(row['cost_usd'])}",
        color_class="bar-amber",
    )
    companion_scores = _score_rows(
        [
            ("Interaction", _safe_float((companion.get("dimension_scores") or {}).get("interaction"))),
            ("Reasoning", _safe_float((companion.get("dimension_scores") or {}).get("reasoning"))),
            ("Tool", _safe_float((companion.get("dimension_scores") or {}).get("tool"))),
            ("Rubric Avg", _safe_float(companion.get("avg_rubric_score"))),
            ("Strict", _safe_float(companion.get("strict_success_rate"))),
        ],
        color_class="bar-teal",
    )
    ragas_scores = _score_rows(
        [
            ("Faithfulness", _safe_float(ragas.get("faithfulness"))),
            ("Answer Relevancy", _safe_float(ragas.get("answer_relevancy"))),
            ("Context Precision", _safe_float(ragas.get("context_precision"))),
            ("Overall", _safe_float(ragas.get("overall"))),
        ],
        color_class="bar-green",
    )
    ragas_city_bars = _bar_rows(
        ragas.get("by_city") or [],
        label_key="city",
        value_key="overall",
        display=lambda value, row: (
            f"{_percent(value)}  F {_safe_float(row.get('faithfulness')):.2f} / "
            f"R {_safe_float(row.get('answer_relevancy')):.2f} / P {_safe_float(row.get('context_precision')):.2f}"
        ),
        color_class="bar-green",
    )
    ragas_score_bands = _score_distribution_pie(ragas.get("score_bands") or [])
    rag_retrieval_city_bars = _bar_rows(
        rag_retrieval.get("by_city") or [],
        label_key="city",
        value_key="hit_rate",
        display=lambda value, row: f"{_percent(value)} hit / MRR {_safe_float(row.get('mrr')):.2f}",
        color_class="bar-teal",
    )
    rag_retrieval_trend_chart = _rag_retrieval_trend_chart(rag_retrieval.get("version_history") or [])
    failure_bars = _bar_rows(
        companion.get("top_failures") or [],
        label_key="tag",
        value_key="count",
        display=lambda value, _row: f"{int(value)}",
        color_class="bar-red",
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Travel Agent Evaluation Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f9fb;
      --panel: #ffffff;
      --text: #172638;
      --muted: #5d6876;
      --border: #e0e5eb;
      --blue: #1c4aff;
      --teal: #00aafb;
      --amber: #8c99a8;
      --green: #2ff3e8;
      --purple: #5874ff;
      --red: #d92d20;
      --ink: #001c2d;
      --navy: #001c2d;
      --navy-2: #082f49;
      --cyan: #2ff3e8;
      --electric: #00aafb;
      --light-grey: #e6e6e6;
      --ice: #f0f6fc;
      --line: #e6e6e6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, sans-serif;
      line-height: 1.45;
    }}
    .shell {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px 24px 40px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-end;
      background: var(--navy);
      color: #ffffff;
      border: 1px solid #0b3b5c;
      border-radius: 8px;
      padding: 22px 24px;
      margin-bottom: 20px;
      box-shadow: 0 8px 22px rgba(0, 28, 45, 0.18);
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin-top: 8px;
      color: #d7e8f6;
      font-size: 14px;
    }}
    .stamp {{
      color: #d9edf8;
      font-size: 13px;
      text-align: right;
      white-space: nowrap;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .kpi, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(5, 28, 44, 0.05);
    }}
    .kpi {{
      padding: 16px;
      min-height: 118px;
      border-top: 5px solid var(--blue);
      cursor: grab;
      user-select: none;
    }}
    .kpi:active {{ cursor: grabbing; }}
    .kpi.is-dragging {{
      opacity: 0.55;
      transform: scale(0.98);
    }}
    .kpi-teal {{ border-top-color: var(--teal); }}
    .kpi-amber {{ border-top-color: var(--amber); }}
    .kpi-green {{ border-top-color: var(--green); }}
    .kpi-purple {{ border-top-color: var(--purple); }}
    .kpi-red {{ border-top-color: var(--red); }}
    .kpi-title {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 10px;
      text-transform: none;
      letter-spacing: 0;
    }}
    .kpi-value {{
      font-size: 27px;
      font-weight: 700;
      color: var(--ink);
      overflow-wrap: anywhere;
    }}
    .kpi-meta {{
      margin-top: 9px;
      color: var(--muted);
      font-size: 12px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 14px;
    }}
    .panel {{
      padding: 16px;
      min-width: 0;
    }}
    .panel h2 {{
      margin: 0 0 12px;
      font-size: 18px;
      letter-spacing: 0;
      color: var(--navy);
    }}
    .panel-note {{
      color: var(--muted);
      font-size: 12px;
      margin-top: -6px;
      margin-bottom: 12px;
    }}
    .bar-row {{
      display: grid;
      grid-template-columns: minmax(118px, 0.8fr) minmax(160px, 2fr) minmax(92px, 0.7fr);
      gap: 10px;
      align-items: center;
      min-height: 30px;
      font-size: 13px;
    }}
    .bar-label {{
      color: var(--text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .bar-track {{
      height: 10px;
      background: var(--ice);
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid var(--line);
    }}
    .bar-fill {{
      height: 100%;
      border-radius: 999px;
    }}
    .bar-blue {{ background: var(--blue); }}
    .bar-teal {{ background: var(--teal); }}
    .bar-amber {{ background: var(--amber); }}
    .bar-green {{ background: var(--green); }}
    .bar-red {{ background: var(--red); }}
    .bar-value {{
      color: var(--muted);
      text-align: right;
      white-space: nowrap;
    }}
    .line-chart-wrap {{
      width: 100%;
      min-height: 320px;
    }}
    .chart-legend {{
      display: flex;
      gap: 18px;
      align-items: center;
      margin: 2px 0 8px;
      color: var(--muted);
      font-size: 12px;
    }}
    .chart-legend span {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      white-space: nowrap;
    }}
    .legend-swatch {{
      width: 22px;
      height: 3px;
      border-radius: 999px;
      display: inline-block;
    }}
    .legend-hit {{ background: var(--teal); }}
    .legend-mrr {{ background: var(--amber); }}
    .line-chart {{
      width: 100%;
      height: auto;
      display: block;
      overflow: visible;
    }}
    .chart-grid {{
      stroke: var(--line);
      stroke-width: 1;
    }}
    .chart-axis {{
      stroke: #b8c7d9;
      stroke-width: 1.2;
    }}
    .chart-line {{
      fill: none;
      stroke-width: 3;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .chart-hit-line {{ stroke: var(--teal); }}
    .chart-mrr-line {{ stroke: var(--amber); }}
    .chart-point {{
      stroke: #ffffff;
      stroke-width: 2;
    }}
    .chart-hit-point {{ fill: var(--teal); }}
    .chart-mrr-point {{ fill: var(--amber); }}
    .chart-y-label,
    .chart-x-label {{
      fill: var(--muted);
      font-size: 12px;
      font-family: Arial, sans-serif;
    }}
    .chart-summary {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
    }}
    .donut-wrap {{
      display: grid;
      grid-template-columns: minmax(180px, 0.8fr) minmax(210px, 1fr);
      gap: 16px;
      align-items: center;
      min-height: 250px;
    }}
    .donut-chart {{
      width: 100%;
      max-width: 260px;
      margin: 0 auto;
      display: block;
    }}
    .donut-bg {{
      fill: none;
      stroke: var(--ice);
      stroke-width: 28;
    }}
    .donut-segment {{
      fill: none;
      stroke-width: 28;
      stroke-linecap: butt;
      transition: stroke-width 0.15s ease;
    }}
    .donut-segment:hover {{
      stroke-width: 32;
    }}
    .donut-green {{ stroke: var(--green); background: var(--green); }}
    .donut-teal {{ stroke: var(--teal); background: var(--teal); }}
    .donut-amber {{ stroke: var(--amber); background: var(--amber); }}
    .donut-red {{ stroke: var(--red); background: var(--red); }}
    .donut-total {{
      fill: var(--ink);
      font-weight: 700;
      font-size: 30px;
      font-family: Arial, sans-serif;
    }}
    .donut-caption {{
      fill: var(--muted);
      font-size: 12px;
      font-family: Arial, sans-serif;
    }}
    .donut-legend {{
      display: grid;
      gap: 10px;
    }}
    .donut-legend-row {{
      display: grid;
      grid-template-columns: 14px minmax(96px, 1fr) minmax(86px, auto);
      gap: 9px;
      align-items: center;
      font-size: 13px;
    }}
    .donut-swatch {{
      width: 12px;
      height: 12px;
      border-radius: 3px;
      display: inline-block;
    }}
    .donut-band {{
      color: var(--text);
    }}
    .donut-value {{
      color: var(--muted);
      text-align: right;
      white-space: nowrap;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 9px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      background: #f7fafd;
    }}
    td {{
      color: var(--text);
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
    }}
    .score-pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 46px;
      padding: 3px 8px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 12px;
      border: 1px solid transparent;
      white-space: nowrap;
    }}
    .score-good {{
      color: #084c61;
      background: #d9fffc;
      border-color: #9bf8f1;
    }}
    .score-mid {{
      color: #334155;
      background: #eef4ff;
      border-color: #cbd6ff;
    }}
    .score-low {{
      color: #991b1b;
      background: #fee2e2;
      border-color: #fecaca;
    }}
    .metric-list {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 6px;
    }}
    .metric-box {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #f9fbfe;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 7px;
    }}
    .metric-value {{
      font-size: 18px;
      font-weight: 700;
      color: var(--ink);
    }}
    .sources {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      font-size: 13px;
    }}
    .sources li {{
      margin: 8px 0;
    }}
    .sources span {{
      display: inline-block;
      min-width: 140px;
      color: var(--text);
    }}
    code {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      color: var(--navy-2);
      background: #eef5fb;
      border: 1px solid #d5e4f2;
      border-radius: 6px;
      padding: 2px 5px;
      overflow-wrap: anywhere;
    }}
    .formula {{
      background: var(--navy);
      color: #e5e7eb;
      border-radius: 8px;
      padding: 12px;
      font-family: Consolas, "Courier New", monospace;
      font-size: 13px;
      overflow-x: auto;
    }}
    .empty {{
      color: var(--muted);
      font-size: 13px;
      padding: 8px 0;
    }}
    @media (max-width: 980px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      .stamp {{ text-align: left; }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .grid {{ grid-template-columns: 1fr; }}
      .metric-list {{ grid-template-columns: 1fr; }}
      .donut-wrap {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 640px) {{
      .shell {{ padding: 18px 12px 28px; }}
      .kpi-grid {{ grid-template-columns: 1fr; }}
      .bar-row {{
        grid-template-columns: 1fr;
        gap: 5px;
        padding: 8px 0;
        border-bottom: 1px solid #edf0f5;
      }}
      .bar-value {{ text-align: left; }}
      table {{ font-size: 12px; }}
      th, td {{ padding: 8px 6px; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1>Travel Agent Evaluation Dashboard</h1>
        <div class="subtitle">Current-stage summary of resolution rate, response time, error rate, tokens, and cost. Designed for direct PPT screenshots.</div>
      </div>
      <div class="stamp">Generated at<br>{_escape(generated_at)}</div>
    </header>

    <section class="kpi-grid">
      {kpis}
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Response Time by Agent</h2>
        <div class="panel-note">End-to-end latency from <code>eval_trace.jsonl</code>. SLA threshold: 30s.</div>
        {latency_bars}
      </div>
      <div class="panel">
        <h2>Tokens and Cost by Agent</h2>
        <div class="panel-note">Estimated with the default gpt-5-mini pricing table. Older trace records without model metadata are backfilled with the current default model.</div>
        {token_bars}
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Companion Resolution and Capability Scores</h2>
        <div class="panel-note">Run: <code>{_escape(companion.get("run_name", "-"))}</code>; progress {_escape(completed_trials)}/{_escape(total_trials)} ({_escape(_percent(completion))}).</div>
        {companion_scores}
      </div>
      <div class="panel">
        <h2>RAGAS Generation Quality</h2>
        <div class="panel-note">Faithfulness / Answer Relevancy / Context Precision / Overall. Answer model: {_escape(ragas.get("answer_model", DEFAULT_MODEL))}; Judge model: {_escape(ragas.get("judge_model", DEFAULT_MODEL))}.</div>
        {ragas_scores}
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>RAGAS City Performance</h2>
        <div class="panel-note">Overall score by city across 10 golden cases each. F = Faithfulness, R = Answer Relevancy, P = Context Precision.</div>
        {ragas_city_bars}
      </div>
      <div class="panel">
        <h2>RAGAS Score Distribution</h2>
        <div class="panel-note">Overall score bands across all {_escape(ragas.get("case_count", 0))} RAGAS cases.</div>
        {ragas_score_bands}
      </div>
    </section>

    <section class="panel" style="margin-bottom: 14px;">
      <h2>RAGAS City Score Table</h2>
      <div class="panel-note">Sorted by city-level overall score. Green is >=0.90, amber is 0.70-0.89, red is below 0.70.</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>City</th>
              <th>Cases</th>
              <th>Overall</th>
              <th>Faith</th>
              <th>Relevancy</th>
              <th>Precision</th>
            </tr>
          </thead>
          <tbody>
            {_ragas_city_rows(ragas.get("by_city") or [])}
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel" style="margin-bottom: 14px;">
      <h2>RAGAS Lowest Scoring Cases</h2>
      <div class="panel-note">These cases explain the main quality loss: missing key facts, noisy context, or partially answered multi-part questions.</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>City</th>
              <th>Query</th>
              <th>Overall</th>
              <th>Faith</th>
              <th>Relevancy</th>
              <th>Precision</th>
              <th>Judge Reason</th>
            </tr>
          </thead>
          <tbody>
            {_ragas_low_case_rows(ragas.get("lowest_cases") or [])}
          </tbody>
        </table>
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>RAG Retrieval Quality</h2>
        <div class="panel-note">Non-RAGAS retrieval metrics from golden queries. Report date: {_escape(rag_retrieval.get("generated_date", "-"))}; version {_escape(rag_retrieval.get("latest_version", "-"))}.</div>
        {rag_retrieval_city_bars}
      </div>
      <div class="panel">
        <h2>RAG Optimization Trend</h2>
        <div class="panel-note">Historical Hit Rate@5 and MRR from the retrieval evaluation report.</div>
        {rag_retrieval_trend_chart}
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Lowest Retrieval Cases</h2>
        <div class="panel-note">Queries with the lowest keyword hit ratio or ranking quality. These are the first places to improve data coverage or retrieval weighting.</div>
        <table>
          <thead>
            <tr>
              <th>Category</th>
              <th>Query</th>
              <th>Hit@{_escape(rag_retrieval.get("top_k", 5))}</th>
              <th>MRR</th>
            </tr>
          </thead>
          <tbody>
            {_rag_weak_rows(rag_retrieval.get("weak_cases") or [])}
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h2>RAG Version Details</h2>
        <div class="panel-note">Retrieval-side metrics are independent from LLM-as-judge RAGAS scores.</div>
        <table>
          <thead>
            <tr>
              <th>Version</th>
              <th>Hit Rate</th>
              <th>MRR</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody>
            {_rag_version_rows(rag_retrieval.get("version_history") or [])}
          </tbody>
        </table>
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Top Failure Drivers</h2>
        <div class="panel-note">Failure tags from the Companion benchmark, useful for explaining the error-rate sources.</div>
        {failure_bars}
      </div>
      <div class="panel">
        <h2>RAGAS Average Latency Breakdown</h2>
        <div class="metric-list">
          <div class="metric-box"><div class="metric-label">Retrieve</div><div class="metric-value">{_escape(_seconds(ragas.get("retrieve_ms", 0.0)))}</div></div>
          <div class="metric-box"><div class="metric-label">Generate</div><div class="metric-value">{_escape(_seconds(ragas.get("generate_ms", 0.0)))}</div></div>
          <div class="metric-box"><div class="metric-label">Judge</div><div class="metric-value">{_escape(_seconds(ragas.get("judge_ms", 0.0)))}</div></div>
        </div>
        <div class="panel-note" style="margin-top: 12px;">Average total latency per case is about {_escape(_seconds(ragas.get("avg_total_latency_ms", 0.0)))}.</div>
      </div>
    </section>

    <section class="panel" style="margin-bottom: 14px;">
      <h2>Agent Detail Summary</h2>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Records</th>
            <th>Avg Response</th>
            <th>P95 Response</th>
            <th>Timeout Rate</th>
            <th>Token</th>
            <th>Cost USD</th>
          </tr>
        </thead>
        <tbody>
          {_agent_rows(trace["agents"])}
        </tbody>
      </table>
    </section>

    <section class="panel" style="margin-bottom: 14px;">
      <h2>Recent Per-Turn Cost</h2>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>City</th>
            <th>Turn</th>
            <th>Latency</th>
            <th>Token</th>
            <th>Per-Turn Cost</th>
            <th>Alerts</th>
          </tr>
        </thead>
        <tbody>
          {_recent_rows(trace["recent_turns"])}
        </tbody>
      </table>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Cost Methodology</h2>
        <div class="formula">cost = token_usage estimated_cost from each result when available
mixed-model RAGAS runs sum child costs across answer and judge calls
CNY = USD * 7.2</div>
        <div class="panel-note" style="margin-top: 12px;">This is a token-based estimate using <code>token_costing.py</code>. It is not the actual cloud billing amount.</div>
      </div>
      <div class="panel">
        <h2>Data Sources</h2>
        <ul class="sources">
          {_source_list(trace, companion, ragas, rag_retrieval)}
        </ul>
      </div>
    </section>
  </main>
{KPI_DRAG_SCRIPT}
</body>
</html>
"""


def main() -> None:
    out = EVAL_DIR / "eval_dashboard.html"
    out.write_text(build_html(), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
