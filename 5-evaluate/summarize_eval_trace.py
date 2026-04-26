# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from token_costing import aggregate_token_usage, with_token_cost  # noqa: E402


DEFAULT_TRACE_PATH = Path(__file__).resolve().parent / "eval_trace.jsonl"


def load_trace_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _agent_name(record: dict[str, Any]) -> str:
    return str(record.get("agent") or "travel_planner_legacy")


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_agent.setdefault(_agent_name(record), []).append(record)

    agent_summaries: dict[str, dict[str, Any]] = {}
    for agent, items in sorted(by_agent.items()):
        usage = aggregate_token_usage([item.get("token_usage") for item in items], source=f"{agent}_trace")
        latencies = [int((item.get("latency_ms") or {}).get("total") or 0) for item in items]
        alerts = [alert for item in items for alert in item.get("alerts", [])]
        agent_summaries[agent] = {
            "record_count": len(items),
            "token_usage": usage,
            "avg_tokens_per_turn": round(usage.get("total_tokens", 0) / len(items), 2) if items else 0.0,
            "latency_ms": {
                "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
                "max": max(latencies) if latencies else 0,
            },
            "alert_count": len(alerts),
            "alerts": alerts,
        }

    total_usage = aggregate_token_usage(
        [summary["token_usage"] for summary in agent_summaries.values()],
        source="eval_trace_total",
    )
    return {
        "record_count": len(records),
        "by_agent": agent_summaries,
        "total_token_usage": total_usage,
    }


def print_summary(summary: dict[str, Any]) -> None:
    print("Eval trace resource/cost summary")
    print(f"Records: {summary['record_count']}")
    total = with_token_cost(summary["total_token_usage"])
    total_cost = total.get("estimated_cost", {})
    print(
        "Total tokens: "
        f"{total.get('total_tokens', 0)} "
        f"(input {total.get('input_tokens', 0)}, output {total.get('output_tokens', 0)})"
    )
    print(f"Estimated cost: ${total_cost.get('total_usd', 0):.6f} / CNY {total_cost.get('total_cny', 0):.4f}")
    print()
    for agent, item in summary["by_agent"].items():
        usage = item["token_usage"]
        cost = usage.get("estimated_cost", {})
        print(
            f"- {agent}: records={item['record_count']}, "
            f"tokens={usage.get('total_tokens', 0)}, "
            f"avg_tokens/turn={item['avg_tokens_per_turn']}, "
            f"cost=${cost.get('total_usd', 0):.6f}, "
            f"avg_latency_ms={item['latency_ms']['avg']}, "
            f"alerts={item['alert_count']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize eval_trace.jsonl token and cost usage.")
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    summary = summarize_records(load_trace_records(args.trace))
    print_summary(summary)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
