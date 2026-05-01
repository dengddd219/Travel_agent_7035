# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import html
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_RUN_DIR = EVAL_DIR / "companion_eval_runs" / "full_llm_k4_merged"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def pct(value: Any, digits: int = 1) -> str:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number * 100:.{digits}f}%"


def num(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def money_usd(value: Any) -> str:
    try:
        return f"${float(value or 0.0):.6f}"
    except (TypeError, ValueError):
        return "$0.000000"


def money_cny(value: Any) -> str:
    try:
        return f"\u00a5{float(value or 0.0):.4f}"
    except (TypeError, ValueError):
        return "\u00a50.0000"


def safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def snippet(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def css_width(value: Any, scale: float = 1.0, minimum: float = 2.0) -> str:
    width = max(0.0, min(100.0, safe_float(value) * scale * 100.0))
    if width > 0:
        width = max(minimum, width)
    return f"{width:.1f}%"


def kpi(title: str, value: str, meta: str, tone: str = "blue") -> str:
    return f"""
    <section class="kpi kpi-{tone}">
      <div class="kpi-title">{esc(title)}</div>
      <div class="kpi-value">{esc(value)}</div>
      <div class="kpi-meta">{esc(meta)}</div>
    </section>
    """


def paired_metric_rows(metrics: dict[str, Any]) -> str:
    baseline = metrics["run"]["baseline_rule_offline"]
    overall = metrics["overall"]
    rows = [
        ("\u4e25\u683c\u6210\u529f\u7387", "strict_success_rate", "strict_success_rate"),
        ("\u5e73\u5747 Rubric \u5f97\u5206", "avg_rubric_score", "avg_rubric_score"),
        ("\u5de5\u5177\u6210\u529f\u7387", "avg_tool_success", "avg_tool_success"),
    ]
    chunks: list[str] = []
    for label, full_key, base_key in rows:
        full_value = safe_float(overall.get(full_key))
        base_value = safe_float(baseline.get(base_key))
        delta = full_value - base_value
        chunks.append(
            f"""
            <div class="paired-row">
              <div class="paired-label">{esc(label)}</div>
              <div class="paired-bars">
                <div class="bar-line"><span>Full LLM</span><div class="bar-track"><div class="bar-fill blue" style="width:{css_width(full_value)}"></div></div><strong>{pct(full_value)}</strong></div>
                <div class="bar-line"><span>Rule</span><div class="bar-track"><div class="bar-fill muted" style="width:{css_width(base_value)}"></div></div><strong>{pct(base_value)}</strong></div>
              </div>
              <div class="delta {'positive' if delta >= 0 else 'negative'}">{delta * 100:+.1f}pt</div>
            </div>
            """
        )
    return "\n".join(chunks)


def radar_svg(scores: dict[str, Any]) -> str:
    labels = [
        ("\u63a8\u7406", safe_float(scores.get("reasoning"))),
        ("\u5de5\u5177", safe_float(scores.get("tool"))),
        ("\u4ea4\u4e92", safe_float(scores.get("interaction"))),
    ]
    cx = cy = 150.0
    radius = 94.0

    def point(index: int, value: float) -> tuple[float, float]:
        angle = -math.pi / 2 + index * 2 * math.pi / len(labels)
        return (cx + math.cos(angle) * radius * value, cy + math.sin(angle) * radius * value)

    grid = []
    for level in [0.25, 0.5, 0.75, 1.0]:
        pts = " ".join(f"{point(i, level)[0]:.1f},{point(i, level)[1]:.1f}" for i in range(len(labels)))
        grid.append(f'<polygon points="{pts}" class="radar-grid" />')

    axes = []
    label_nodes = []
    for i, (label, value) in enumerate(labels):
        x, y = point(i, 1.0)
        axes.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" class="radar-axis" />')
        lx, ly = point(i, 1.18)
        anchor = "middle"
        if lx < cx - 10:
            anchor = "end"
        elif lx > cx + 10:
            anchor = "start"
        label_nodes.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" class="radar-label">{esc(label)} {pct(value)}</text>'
        )

    poly_points = " ".join(f"{point(i, value)[0]:.1f},{point(i, value)[1]:.1f}" for i, (_label, value) in enumerate(labels))
    return f"""
    <svg class="radar" viewBox="0 0 300 300" role="img" aria-label="dimension radar">
      {"".join(grid)}
      {"".join(axes)}
      <polygon points="{poly_points}" class="radar-area" />
      <polyline points="{poly_points} {poly_points.split()[0]}" class="radar-stroke" />
      {"".join(label_nodes)}
    </svg>
    """


def city_rows(metrics: dict[str, Any]) -> str:
    rows: list[str] = []
    for row in metrics.get("by_city", []):
        rows.append(
            f"""
            <tr>
              <td><strong>{esc(row.get("city"))}</strong><span class="muted-text"> / {esc(row.get("city_zh"))}</span></td>
              <td>{pct(row.get("strict_success_rate"))}<div class="mini-track"><span class="mini-fill blue" style="width:{css_width(row.get("strict_success_rate"))}"></span></div></td>
              <td>{pct(row.get("avg_rubric_score"))}<div class="mini-track"><span class="mini-fill teal" style="width:{css_width(row.get("avg_rubric_score"))}"></span></div></td>
              <td>{pct(row.get("avg_tool_success"))}<div class="mini-track"><span class="mini-fill amber" style="width:{css_width(row.get("avg_tool_success"))}"></span></div></td>
              <td>{pct(row.get("reasoning"))}</td>
              <td>{pct(row.get("interaction"))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def failure_rows(items: list[dict[str, Any]], label_key: str, value_key: str = "count") -> str:
    max_value = max((safe_float(item.get(value_key)) for item in items), default=0.0)
    rows: list[str] = []
    for index, item in enumerate(items[:10], start=1):
        count = safe_float(item.get(value_key))
        width = 0.0 if max_value <= 0 else count / max_value
        label = item.get(label_key)
        if label_key == "rubric":
            label = f"{item.get('key')} / {item.get('dimension')}"
        rows.append(
            f"""
            <div class="rank-row">
              <div class="rank-number">{index}</div>
              <div class="rank-body">
                <div class="rank-label">{esc(label)}</div>
                <div class="rank-track"><div class="rank-fill" style="width:{css_width(width)}"></div></div>
              </div>
              <div class="rank-value">{int(count)}<span>{pct(item.get("trial_rate"))}</span></div>
            </div>
            """
        )
    return "\n".join(rows) or '<div class="empty">No data</div>'


def trajectory_lookup(trajectories: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for item in trajectories:
        task_id = str(item.get("task_id") or "")
        trial_index = int(item.get("trial_index") or 0)
        if task_id and trial_index:
            lookup[(task_id, trial_index)] = item
    return lookup


def trajectory_summary(trajectory: dict[str, Any] | None) -> dict[str, Any]:
    events = (trajectory or {}).get("events") or []
    user_messages = [event.get("content") for event in events if event.get("type") == "user_message"]
    assistant_messages = [event.get("content") for event in events if event.get("type") == "assistant_message"]
    tool_calls = [
        str(event.get("tool"))
        for event in events
        if event.get("type") == "tool_call" and event.get("tool")
    ]
    return {
        "user_message": user_messages[0] if user_messages else "",
        "assistant_final": assistant_messages[-1] if assistant_messages else "",
        "tool_calls": tool_calls,
    }


def root_cause(row: dict[str, Any], tool_calls: list[str]) -> str:
    tags = set(str(tag) for tag in row.get("failure_tags") or [])
    failed = row.get("failed_rubrics") or []
    failed_keys = {str(item.get("key") or "") for item in failed}
    failed_dims = {str(item.get("dimension") or "") for item in failed}
    if "missed_clarification" in tags and {"get_weather_now", "retrieve_candidates", "score_candidates"} & set(tool_calls):
        return "\u672a\u6f84\u6e05\u5f53\u524d\u4f4d\u7f6e\uff0c\u610f\u56fe\u8dd1\u504f\u5230\u5929\u6c14/\u5ba4\u5185\u66ff\u4ee3\u63a8\u8350"
    if "call_replan_tool" in failed_keys:
        return "\u5df2\u8fdb\u5165\u6f84\u6e05/\u89c4\u5212\uff0c\u4f46\u672a\u7ee7\u7eed\u5230 replan_itinerary \u5de5\u5177\u95ed\u73af"
    if "missed_clarification" in tags:
        return "\u672a\u5148\u6f84\u6e05\u5173\u952e\u6761\u4ef6\uff0c\u610f\u56fe\u5bb9\u6613\u8dd1\u5411\u5176\u4ed6\u63a8\u8350\u94fe\u8def"
    if "tool" in failed_dims and safe_float(row.get("tool_success")) <= 0:
        missing = ", ".join(sorted(key for key in failed_keys if key)[:3])
        return f"\u5de5\u5177\u94fe\u672a\u5b8c\u6210\uff1a{missing or 'required tool missing'}"
    if {"missed_deadline", "overpacked_plan", "closing_time_ignored"} & tags:
        return "\u65f6\u95f4\u622a\u6b62\u70b9/\u884c\u7a0b\u5bc6\u5ea6\u6ca1\u6709\u843d\u5230\u8def\u7ebf\u548c buffer"
    if {"weather_guess", "keeps_bad_weather_outdoor"} & tags or "indoor_constraint" in failed_keys:
        return "\u5929\u6c14\u6216\u5ba4\u5185\u7ea6\u675f\u6ca1\u6709\u8f6c\u5316\u4e3a\u53ef\u6267\u884c\u7684\u91cd\u6392"
    if "no_route_check" in tags or "route_checked" in failed_keys:
        return "\u6ca1\u6709\u505a\u8def\u7ebf/\u8ddd\u79bb\u53ef\u884c\u6027\u6821\u9a8c"
    if not tool_calls:
        return "\u6ca1\u6709\u8bb0\u5f55\u5230\u6709\u6548\u5de5\u5177\u8c03\u7528"
    return "\u591a\u4e2a rubric \u672a\u8fbe\u6807\uff0c\u9700\u8981\u68c0\u67e5\u610f\u56fe\u8bc6\u522b\u548c\u6267\u884c\u95ed\u73af"


def build_bad_case_analysis(run_dir: Path, metrics: dict[str, Any]) -> dict[str, Any]:
    results = read_jsonl(run_dir / "trial_results.jsonl")
    trajectories = trajectory_lookup(read_jsonl(run_dir / "trajectories.jsonl"))
    failed = [row for row in results if not row.get("strict_success")]

    tag_counts: Counter[str] = Counter()
    rubric_counts: Counter[tuple[str, str]] = Counter()
    tool_gap_count = 0
    route_time_gap_count = 0
    weather_gap_count = 0
    clarification_gap_count = 0
    for row in failed:
        tags = {str(tag) for tag in row.get("failure_tags") or []}
        tag_counts.update(tags)
        failed_rubrics = row.get("failed_rubrics") or []
        for item in failed_rubrics:
            key = str(item.get("key") or "")
            dim = str(item.get("dimension") or "")
            rubric_counts[(key, dim)] += 1
            if dim == "tool":
                tool_gap_count += 1
        if {"missed_deadline", "overpacked_plan", "closing_time_ignored", "no_route_check"} & tags:
            route_time_gap_count += 1
        if {"weather_guess", "keeps_bad_weather_outdoor"} & tags:
            weather_gap_count += 1
        if "missed_clarification" in tags:
            clarification_gap_count += 1

    high_risk_tasks = [
        row
        for row in sorted(
            metrics.get("by_task", []),
            key=lambda item: (
                int(item.get("strict_successes") or 0),
                safe_float(item.get("avg_rubric_score")),
                safe_float(item.get("avg_tool_success")),
                str(item.get("task_id") or ""),
            ),
        )
        if int(row.get("strict_successes") or 0) < int(row.get("trials") or 0)
    ][:8]

    bad_trials: list[dict[str, Any]] = []
    preferred = {("companion_beijing_001", 1), ("companion_beijing_001", 2)}
    ordered_failed = sorted(
        failed,
        key=lambda item: (
            0 if (str(item.get("task_id")), int(item.get("trial_index") or 0)) in preferred else 1,
            safe_float(item.get("rubric_score")),
            safe_float(item.get("tool_success")),
            str(item.get("task_id") or ""),
            int(item.get("trial_index") or 0),
        ),
    )
    seen: set[tuple[str, int]] = set()
    for row in ordered_failed:
        task_id = str(row.get("task_id") or "")
        trial_index = int(row.get("trial_index") or 0)
        key = (task_id, trial_index)
        if key in seen:
            continue
        seen.add(key)
        trace = trajectory_summary(trajectories.get(key))
        failed_keys = [
            str(item.get("key") or "")
            for item in row.get("failed_rubrics") or []
            if item.get("key")
        ]
        bad_trials.append(
            {
                "task_id": task_id,
                "city": row.get("city"),
                "trial_index": trial_index,
                "rubric_score": safe_float(row.get("rubric_score")),
                "tool_success": safe_float(row.get("tool_success")),
                "failure_tags": list(row.get("failure_tags") or [])[:4],
                "failed_rubrics": failed_keys[:5],
                "user_message": trace["user_message"],
                "assistant_final": trace["assistant_final"],
                "tool_calls": trace["tool_calls"],
                "root_cause": root_cause(row, trace["tool_calls"]),
            }
        )
        if len(bad_trials) >= 8:
            break

    pattern_cards = [
        {
            "title": "\u5de5\u5177\u8c03\u7528\u65ad\u70b9",
            "count": tool_gap_count,
            "description": "\u4e3b\u8981\u8868\u73b0\u4e3a replan_itinerary / get_route / buffer \u68c0\u67e5\u672a\u6267\u884c\u6216\u672a\u88ab\u8bc4\u6d4b\u5230\u3002",
        },
        {
            "title": "\u65f6\u95f4\u4e0e\u8def\u7ebf\u53ef\u884c\u6027\u4e0d\u8db3",
            "count": route_time_gap_count,
            "description": "\u6709\u622a\u6b62\u65f6\u95f4\u3001\u8f66\u7ad9 buffer \u6216\u8def\u7ebf\u7ea6\u675f\u65f6\uff0c\u5bb9\u6613\u7ed9\u51fa\u8fc7\u6ee1\u6216\u672a\u6821\u9a8c\u7684\u65b9\u6848\u3002",
        },
        {
            "title": "\u5929\u6c14/\u5ba4\u5185\u7ea6\u675f\u843d\u5730\u5f31",
            "count": weather_gap_count,
            "description": "\u4e0b\u96e8\u3001\u5ba4\u5185\u4f18\u5148\u7b49\u6761\u4ef6\u6709\u65f6\u88ab\u731c\u6d4b\u6216\u6ca1\u6709\u8f6c\u4e3a\u660e\u786e\u8c03\u6574\u3002",
        },
        {
            "title": "\u6f84\u6e05\u540e\u672a\u95ed\u73af",
            "count": clarification_gap_count,
            "description": "\u80fd\u95ee\u5230\u90e8\u5206\u5173\u952e\u4fe1\u606f\uff0c\u4f46\u6ca1\u6709\u7ee7\u7eed\u63a8\u8fdb\u5230\u5de5\u5177\u8c03\u7528\u548c\u91cd\u6392\u7ed3\u679c\u3002",
        },
    ]

    return {
        "failed_trial_count": len(failed),
        "failure_rate": len(failed) / len(results) if results else 0.0,
        "pattern_cards": pattern_cards,
        "top_tags": tag_counts.most_common(6),
        "top_rubrics": rubric_counts.most_common(6),
        "high_risk_tasks": high_risk_tasks,
        "bad_trials": bad_trials,
    }


def bad_pattern_cards(analysis: dict[str, Any]) -> str:
    cards = []
    for item in analysis.get("pattern_cards", []):
        cards.append(
            f"""
            <div class="bad-pattern-card">
              <div class="bad-pattern-title">{esc(item.get("title"))}</div>
              <div class="bad-pattern-count">{num(item.get("count"))}</div>
              <div class="bad-pattern-desc">{esc(item.get("description"))}</div>
            </div>
            """
        )
    return "\n".join(cards)


def high_risk_task_rows(analysis: dict[str, Any]) -> str:
    rows: list[str] = []
    for row in analysis.get("high_risk_tasks", []):
        rows.append(
            f"""
            <tr>
              <td><code>{esc(row.get("task_id"))}</code></td>
              <td>{esc(row.get("city"))}</td>
              <td>{int(row.get("strict_successes") or 0)}/{int(row.get("trials") or 0)}</td>
              <td>{pct(row.get("avg_rubric_score"))}</td>
              <td>{pct(row.get("avg_tool_success"))}</td>
              <td>{'Y' if row.get("pass_at_4") else 'N'}</td>
            </tr>
            """
        )
    return "\n".join(rows) or '<tr><td colspan="6">No data</td></tr>'


def bad_trial_rows(analysis: dict[str, Any]) -> str:
    rows: list[str] = []
    for row in analysis.get("bad_trials", []):
        tools = ", ".join(row.get("tool_calls") or [])
        failed = ", ".join(row.get("failed_rubrics") or [])
        tags = ", ".join(row.get("failure_tags") or [])
        rows.append(
            f"""
            <tr>
              <td><code>{esc(row.get("task_id"))} t{esc(row.get("trial_index"))}</code><br><span class="muted-text">{esc(row.get("city"))}</span></td>
              <td>{pct(row.get("rubric_score"))}</td>
              <td>{pct(row.get("tool_success"))}</td>
              <td>{esc(row.get("root_cause"))}<br><span class="small-text">tags: {esc(tags or '-')}</span><br><span class="small-text">rubrics: {esc(failed or '-')}</span></td>
              <td class="small-text">{esc(snippet(row.get("user_message"), 120))}</td>
              <td class="small-text">{esc(snippet(row.get("assistant_final"), 150))}</td>
              <td class="small-text">{esc(snippet(tools or "-", 120))}</td>
            </tr>
            """
        )
    return "\n".join(rows) or '<tr><td colspan="7">No data</td></tr>'


def task_rows(metrics: dict[str, Any]) -> str:
    rows: list[str] = []
    for row in metrics.get("by_task", []):
        status = "ok" if row.get("pass_at_4") else "fail"
        rows.append(
            f"""
            <tr>
              <td><code>{esc(row.get("task_id"))}</code></td>
              <td>{esc(row.get("city"))}</td>
              <td>{int(row.get("strict_successes") or 0)}/{int(row.get("trials") or 0)}</td>
              <td>{pct(row.get("avg_at_4"))}</td>
              <td><span class="pill {status}">{"Y" if row.get("pass_at_4") else "N"}</span></td>
              <td><span class="pill {status if row.get("pass_power_4") else "fail"}">{"Y" if row.get("pass_power_4") else "N"}</span></td>
              <td>{pct(row.get("avg_rubric_score"))}</td>
              <td>{pct(row.get("avg_tool_success"))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def case_rows(metrics: dict[str, Any]) -> str:
    rows: list[str] = []
    for case in metrics.get("case_studies", []):
        status = "ok" if case.get("strict_success") else "fail"
        tools = ", ".join(str(tool.get("tool")) for tool in case.get("tool_calls", []) if tool.get("tool"))
        rows.append(
            f"""
            <tr>
              <td><strong>{esc(case.get("label"))}</strong><br><code>{esc(case.get("task_id"))} t{esc(case.get("trial_index"))}</code></td>
              <td><span class="pill {status}">{"Y" if case.get("strict_success") else "N"}</span></td>
              <td>{pct(case.get("rubric_score"))}</td>
              <td>{pct(case.get("tool_success"))}</td>
              <td>{esc(case.get("ppt_takeaway"))}</td>
              <td class="small-text">{esc(tools or "-")}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def build_html(metrics: dict[str, Any], source_path: Path) -> str:
    overall = metrics["overall"]
    dimensions = metrics["dimension_scores"]
    token = metrics["token_cost_latency"]
    agent_usage = token["trial_token_usage_agent_side"]
    available_usage = token["available_total_usage"]
    latency = token["latency"]
    bad_analysis = build_bad_case_analysis(source_path.parent, metrics)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    kpis = "\n".join(
        [
            kpi("\u4e25\u683c\u6210\u529f\u7387", pct(overall["strict_success_rate"]), f"Avg@4 {pct(overall['avg_at_4'])}", "blue"),
            kpi("Rubric \u5e73\u5747\u5f97\u5206", pct(overall["avg_rubric_score"]), f"{overall['task_count']} tasks / {overall['trial_count']} trials", "teal"),
            kpi("\u5de5\u5177\u6210\u529f\u7387", pct(overall["avg_tool_success"]), f"Tool dimension {pct(dimensions.get('tool'))}", "amber"),
            kpi("Pass@4", pct(overall["pass_at_4"]), f"Pass^4 {pct(overall['pass_power_4'])}", "green"),
            kpi("Agent Tokens", num(agent_usage["total_tokens"]), f"{agent_usage['llm_call_count']} LLM calls", "purple"),
            kpi("Agent Cost", f"{money_usd(agent_usage['estimated_cost_usd'])} / {money_cny(agent_usage['estimated_cost_cny'])}", f"Avg {money_usd(agent_usage['avg_cost_usd_per_trial'])}/trial", "green"),
            kpi("\u5e73\u5747\u5ef6\u8fdf", f"{latency['avg_seconds_per_trial']:.2f}s", f"P95 {latency['p95_ms'] / 1000:.1f}s", "red"),
            kpi("\u53ef\u7528\u603b Token", num(available_usage["total_tokens"]), f"{money_usd(available_usage['estimated_cost_usd'])} available total", "slate"),
        ]
    )

    chart_items = "\n".join(f"<li>{esc(item)}</li>" for item in metrics.get("recommended_charts", []))
    source_rel = source_path.as_posix()

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Companion Agent Full LLM Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #172033;
      --text: #344054;
      --muted: #667085;
      --border: #d9e2ef;
      --soft: #edf2f8;
      --blue: #2563eb;
      --teal: #0f766e;
      --amber: #b7791f;
      --green: #15803d;
      --purple: #7c3aed;
      --red: #b42318;
      --slate: #475467;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, "Microsoft YaHei", sans-serif;
      line-height: 1.45;
    }}
    .shell {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px 24px 40px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 24px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      color: var(--ink);
      letter-spacing: 0;
    }}
    .subtitle {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    .stamp {{
      color: var(--muted);
      font-size: 12px;
      text-align: right;
      white-space: nowrap;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .kpi, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }}
    .kpi {{
      min-height: 118px;
      padding: 15px;
      border-top: 4px solid var(--blue);
    }}
    .kpi-blue {{ border-top-color: var(--blue); }}
    .kpi-teal {{ border-top-color: var(--teal); }}
    .kpi-amber {{ border-top-color: var(--amber); }}
    .kpi-green {{ border-top-color: var(--green); }}
    .kpi-purple {{ border-top-color: var(--purple); }}
    .kpi-red {{ border-top-color: var(--red); }}
    .kpi-slate {{ border-top-color: var(--slate); }}
    .kpi-title {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .kpi-value {{
      color: var(--ink);
      font-size: 25px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }}
    .kpi-meta {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 8px;
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
    .wide {{
      margin-bottom: 14px;
    }}
    h2 {{
      margin: 0 0 12px;
      color: var(--ink);
      font-size: 18px;
      letter-spacing: 0;
    }}
    .note {{
      color: var(--muted);
      font-size: 12px;
      margin: -6px 0 12px;
    }}
    .paired-row {{
      display: grid;
      grid-template-columns: 130px 1fr 64px;
      gap: 12px;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid var(--soft);
    }}
    .paired-row:last-child {{ border-bottom: 0; }}
    .paired-label {{
      color: var(--ink);
      font-weight: 600;
    }}
    .bar-line {{
      display: grid;
      grid-template-columns: 64px 1fr 58px;
      align-items: center;
      gap: 8px;
      min-height: 24px;
      font-size: 12px;
      color: var(--muted);
    }}
    .bar-track, .rank-track, .mini-track {{
      background: #eef3f8;
      border: 1px solid #e2e8f0;
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar-track {{ height: 10px; }}
    .bar-fill, .rank-fill, .mini-fill {{
      display: block;
      height: 100%;
      border-radius: 999px;
    }}
    .blue {{ background: var(--blue); }}
    .teal {{ background: var(--teal); }}
    .amber {{ background: var(--amber); }}
    .green {{ background: var(--green); }}
    .muted {{ background: #98a2b3; }}
    .delta {{
      text-align: right;
      font-weight: 700;
      color: var(--muted);
    }}
    .delta.positive {{ color: var(--green); }}
    .delta.negative {{ color: var(--red); }}
    .radar-wrap {{
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 14px;
      align-items: center;
    }}
    .radar {{
      width: 100%;
      max-width: 320px;
      aspect-ratio: 1 / 1;
    }}
    .radar-grid {{
      fill: none;
      stroke: #d9e2ef;
      stroke-width: 1;
    }}
    .radar-axis {{
      stroke: #c7d2e1;
      stroke-width: 1;
    }}
    .radar-area {{
      fill: rgba(37, 99, 235, 0.18);
    }}
    .radar-stroke {{
      fill: none;
      stroke: var(--blue);
      stroke-width: 3;
    }}
    .radar-label {{
      fill: var(--text);
      font-size: 12px;
      font-weight: 600;
    }}
    .dimension-list {{
      display: grid;
      gap: 10px;
    }}
    .dimension-item {{
      display: grid;
      grid-template-columns: 96px 1fr 58px;
      gap: 10px;
      align-items: center;
      font-size: 13px;
    }}
    .rank-row {{
      display: grid;
      grid-template-columns: 28px 1fr 72px;
      gap: 10px;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px solid var(--soft);
    }}
    .rank-row:last-child {{ border-bottom: 0; }}
    .rank-number {{
      width: 24px;
      height: 24px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: #f1f5f9;
      color: var(--slate);
      font-weight: 700;
      font-size: 12px;
    }}
    .rank-label {{
      color: var(--ink);
      font-size: 13px;
      margin-bottom: 6px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .rank-track {{ height: 9px; }}
    .rank-fill {{ background: var(--red); }}
    .rank-value {{
      text-align: right;
      color: var(--ink);
      font-weight: 700;
      font-size: 13px;
    }}
    .rank-value span {{
      display: block;
      color: var(--muted);
      font-weight: 400;
      font-size: 11px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 9px 8px;
      border-bottom: 1px solid #e6ebf2;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      background: #f8fafc;
      font-weight: 600;
    }}
    .mini-track {{
      height: 6px;
      margin-top: 6px;
    }}
    .muted-text {{
      color: var(--muted);
    }}
    .small-text {{
      color: var(--muted);
      font-size: 12px;
      max-width: 300px;
    }}
    .pill {{
      display: inline-flex;
      min-width: 26px;
      justify-content: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid transparent;
    }}
    .pill.ok {{
      color: #067647;
      background: #ecfdf3;
      border-color: #abefc6;
    }}
    .pill.fail {{
      color: #b42318;
      background: #fef3f2;
      border-color: #fecdca;
    }}
    code {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      color: #344054;
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 2px 5px;
      overflow-wrap: anywhere;
    }}
    .chart-list {{
      margin: 0;
      padding-left: 18px;
      color: var(--text);
      font-size: 13px;
    }}
    .chart-list li {{ margin: 7px 0; }}
    .bad-pattern-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 8px;
    }}
    .bad-pattern-card {{
      border: 1px solid #fecdca;
      background: #fffbfa;
      border-radius: 8px;
      padding: 12px;
      min-height: 128px;
    }}
    .bad-pattern-title {{
      color: var(--red);
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    .bad-pattern-count {{
      color: var(--ink);
      font-size: 24px;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    .bad-pattern-desc {{
      color: var(--muted);
      font-size: 12px;
    }}
    .table-scroll {{
      overflow-x: auto;
    }}
    @media (max-width: 1100px) {{
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .grid {{ grid-template-columns: 1fr; }}
      .bad-pattern-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .shell {{ padding: 18px 12px 30px; }}
      header {{ flex-direction: column; align-items: flex-start; }}
      .stamp {{ text-align: left; }}
      .kpi-grid {{ grid-template-columns: 1fr; }}
      .paired-row {{ grid-template-columns: 1fr; }}
      .bar-line {{ grid-template-columns: 58px 1fr 52px; }}
      .radar-wrap {{ grid-template-columns: 1fr; }}
      .bad-pattern-grid {{ grid-template-columns: 1fr; }}
      table {{ font-size: 12px; }}
      th, td {{ padding: 8px 6px; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1>Companion Agent \u5168 LLM \u6d4b\u8bc4\u770b\u677f</h1>
        <div class="subtitle">30 tasks x 4 trials = 120 trials. \u6570\u636e\u6e90\uff1a<code>{esc(source_rel)}</code></div>
      </div>
      <div class="stamp">Generated at<br>{esc(generated_at)}</div>
    </header>

    <section class="kpi-grid">
      {kpis}
    </section>

    <section class="grid">
      <div class="panel">
        <h2>\u603b\u4f53\u6307\u6807 vs \u79bb\u7ebf\u89c4\u5219 Baseline</h2>
        <div class="note">Full LLM \u7ed3\u679c\u76f8\u5bf9\u4e8e\u79bb\u7ebf\u89c4\u5219\u6d4b\u8bc4\u5747\u6709\u5c0f\u5e45\u63d0\u5347\uff0c\u4f46\u5de5\u5177\u8c03\u7528\u4ecd\u662f\u4e3b\u8981\u74f6\u9888\u3002</div>
        {paired_metric_rows(metrics)}
      </div>
      <div class="panel">
        <h2>\u80fd\u529b\u7ef4\u5ea6\u96f7\u8fbe</h2>
        <div class="radar-wrap">
          {radar_svg(dimensions)}
          <div class="dimension-list">
            <div class="dimension-item"><strong>Reasoning</strong><div class="bar-track"><span class="bar-fill teal" style="width:{css_width(dimensions.get('reasoning'))}"></span></div><span>{pct(dimensions.get('reasoning'))}</span></div>
            <div class="dimension-item"><strong>Tool</strong><div class="bar-track"><span class="bar-fill amber" style="width:{css_width(dimensions.get('tool'))}"></span></div><span>{pct(dimensions.get('tool'))}</span></div>
            <div class="dimension-item"><strong>Interaction</strong><div class="bar-track"><span class="bar-fill blue" style="width:{css_width(dimensions.get('interaction'))}"></span></div><span>{pct(dimensions.get('interaction'))}</span></div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel wide">
      <h2>\u6309\u57ce\u5e02\u5bf9\u6bd4</h2>
      <div class="note">\u6bcf\u57ce 3 \u9898 x 4 trials = 12 \u6761\u3002\u53ef\u76f4\u63a5\u622a\u53d6\u7528\u4e8e PPT \u57ce\u5e02\u5bf9\u6bd4\u9875\u3002</div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>City</th>
              <th>Strict</th>
              <th>Rubric</th>
              <th>Tool</th>
              <th>Reasoning</th>
              <th>Interaction</th>
            </tr>
          </thead>
          <tbody>{city_rows(metrics)}</tbody>
        </table>
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Failure Tags Pareto</h2>
        <div class="note">\u4efb\u52a1\u7ea7 failure_tags \u7684 Top 10\uff0c\u7528\u4e8e\u8bf4\u660e\u5931\u8d25\u6765\u6e90\u3002</div>
        {failure_rows(metrics.get("failure_tags_top", []), "tag")}
      </div>
      <div class="panel">
        <h2>Failed Rubrics Top 10</h2>
        <div class="note">\u4ece rubric \u89d2\u5ea6\u770b\u6700\u5e38\u6ca1\u6709\u8fbe\u5230\u7684\u8981\u6c42\u3002</div>
        {failure_rows(metrics.get("failed_rubrics_top", []), "rubric")}
      </div>
    </section>

    <section class="panel wide">
      <h2>Bad Case \u5206\u6790</h2>
      <div class="note">\u4e25\u683c\u5931\u8d25 {num(bad_analysis["failed_trial_count"])} / {num(overall["trial_count"])} trials\uff0c\u5931\u8d25\u7387 {pct(bad_analysis["failure_rate"])}\u3002\u4e0b\u9762\u628a\u5931\u8d25\u62c6\u6210\u53ef\u8ffd\u8e2a\u7684\u6267\u884c\u95ee\u9898\uff0c\u4fbf\u4e8e PPT \u8bb2\u201c\u4e3a\u4ec0\u4e48\u6ca1\u6210\u529f\u201d\u3002</div>
      <div class="bad-pattern-grid">
        {bad_pattern_cards(bad_analysis)}
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>\u9ad8\u98ce\u9669\u4efb\u52a1</h2>
        <div class="note">\u6309 strict \u6210\u529f\u6b21\u6570\u3001rubric \u5f97\u5206\u548c tool \u5f97\u5206\u6392\u5e8f\uff0c\u4f18\u5148\u770b\u8fde\u7eed\u5931\u8d25\u7684\u9898\u3002</div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>City</th>
                <th>Strict</th>
                <th>Rubric</th>
                <th>Tool</th>
                <th>Pass@4</th>
              </tr>
            </thead>
            <tbody>{high_risk_task_rows(bad_analysis)}</tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <h2>Bad Case \u9605\u8bfb\u65b9\u6cd5</h2>
        <ul class="chart-list">
          <li>\u5148\u770b\u201c\u6839\u56e0\u5224\u65ad\u201d\uff1a\u5b83\u628a failed rubrics \u548c failure tags \u538b\u7f29\u6210\u53ef\u8bb2\u7684\u95ee\u9898\u7c7b\u578b\u3002</li>
          <li>\u518d\u770b Tool Calls\uff1a\u80fd\u5224\u65ad\u662f\u610f\u56fe\u8dd1\u504f\u3001\u5de5\u5177\u6ca1\u8c03\uff0c\u8fd8\u662f\u8c03\u4e86\u4f46\u6ca1\u5f62\u6210\u7ed3\u679c\u3002</li>
          <li>\u6700\u540e\u5bf9\u7167\u7528\u6237\u8bf7\u6c42\u548c\u6700\u7ec8\u56de\u590d\uff1a\u770b\u662f\u5426\u771f\u6b63\u89e3\u51b3\u4e86\u573a\u666f\u7ea6\u675f\u3002</li>
        </ul>
      </div>
    </section>

    <section class="panel wide">
      <h2>\u4ee3\u8868\u6027 Bad Cases</h2>
      <div class="note">\u524d\u4e24\u6761\u56fa\u5b9a\u4fdd\u7559\u5317\u4eac 001 trial 1/2\uff1b\u5176\u4f59\u6309 rubric/tool \u4f4e\u5206\u81ea\u52a8\u62bd\u53d6\u3002</div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Trial</th>
              <th>Rubric</th>
              <th>Tool</th>
              <th>\u6839\u56e0\u5224\u65ad</th>
              <th>User Request</th>
              <th>Final Reply</th>
              <th>Tool Calls</th>
            </tr>
          </thead>
          <tbody>{bad_trial_rows(bad_analysis)}</tbody>
        </table>
      </div>
    </section>

    <section class="panel wide">
      <h2>\u6309\u9898\u7ed3\u679c</h2>
      <div class="note">Avg@4 = 4 \u6b21\u4e2d\u7684\u5e73\u5747\u4e25\u683c\u6210\u529f\u7387\uff1bPass@4 = \u81f3\u5c11\u4e00\u6b21\u6210\u529f\uff1bPass^4 = 4 \u6b21\u5168\u90e8\u6210\u529f\u3002</div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Task</th>
              <th>City</th>
              <th>Strict</th>
              <th>Avg@4</th>
              <th>Pass@4</th>
              <th>Pass^4</th>
              <th>Rubric</th>
              <th>Tool</th>
            </tr>
          </thead>
          <tbody>{task_rows(metrics)}</tbody>
        </table>
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Token / Cost / Latency</h2>
        <table>
          <tbody>
            <tr><th>Agent-side trial tokens</th><td>{num(agent_usage["total_tokens"])}</td></tr>
            <tr><th>Agent-side LLM calls</th><td>{num(agent_usage["llm_call_count"])}</td></tr>
            <tr><th>Agent-side estimated cost</th><td>{money_usd(agent_usage["estimated_cost_usd"])} / {money_cny(agent_usage["estimated_cost_cny"])}</td></tr>
            <tr><th>Available total tokens</th><td>{num(available_usage["total_tokens"])}</td></tr>
            <tr><th>Available total estimated cost</th><td>{money_usd(available_usage["estimated_cost_usd"])} / {money_cny(available_usage["estimated_cost_cny"])}</td></tr>
            <tr><th>Total latency</th><td>{latency["total_minutes"]:.2f} min</td></tr>
            <tr><th>Avg / P95 latency</th><td>{latency["avg_seconds_per_trial"]:.2f}s / {latency["p95_ms"] / 1000:.1f}s</td></tr>
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h2>PPT \u5efa\u8bae\u56fe\u8868</h2>
        <ul class="chart-list">
          {chart_items}
        </ul>
      </div>
    </section>

    <section class="panel wide">
      <h2>\u6210\u529f/\u5931\u8d25\u6848\u4f8b\u5bf9\u6bd4</h2>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Case</th>
              <th>Strict</th>
              <th>Rubric</th>
              <th>Tool</th>
              <th>PPT Takeaway</th>
              <th>Tool Calls</th>
            </tr>
          </thead>
          <tbody>{case_rows(metrics)}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a static dashboard for CompanionAgent full-LLM evaluation.")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR, help="Directory containing ppt_metrics.json.")
    parser.add_argument("--out", type=Path, default=None, help="Output HTML path. Defaults to <run-dir>/dashboard.html.")
    args = parser.parse_args()

    run_dir = args.run_dir
    metrics_path = run_dir / "ppt_metrics.json"
    output_path = args.out or (run_dir / "dashboard.html")
    metrics = read_json(metrics_path)
    write_text(output_path, build_html(metrics, metrics_path))
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
