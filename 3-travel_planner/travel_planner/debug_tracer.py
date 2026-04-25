"""Debug tracer for RAG+Agent pipeline observability.

Set env var DEBUG_AGENT=1 to activate terminal tracing.
Production runs are unaffected when the var is absent.
"""
from __future__ import annotations

import json
import os
import textwrap
import time
from contextlib import contextmanager
from typing import Any

_ENABLED = os.getenv("DEBUG_AGENT", "").strip() in ("1", "true", "yes")

# ANSI color codes
_C = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "dim":    "\033[2m",
    "cyan":   "\033[36m",
    "yellow": "\033[33m",
    "green":  "\033[32m",
    "blue":   "\033[34m",
    "magenta":"\033[35m",
    "red":    "\033[31m",
    "white":  "\033[97m",
}


def _c(text: str, *codes: str) -> str:
    if not _ENABLED:
        return text
    prefix = "".join(_C.get(c, "") for c in codes)
    return f"{prefix}{text}{_C['reset']}"


def _hr(char: str = "─", width: int = 72, color: str = "dim") -> None:
    if _ENABLED:
        print(_c(char * width, color))


def _header(title: str, icon: str = "▶", color: str = "cyan") -> None:
    if not _ENABLED:
        return
    _hr("═", color=color)
    print(_c(f"{icon}  {title}", "bold", color))
    _hr("─", color="dim")


def _kv(key: str, value: Any, indent: int = 2) -> None:
    if not _ENABLED:
        return
    pad = " " * indent
    vstr = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    # wrap long values
    wrapped = textwrap.fill(vstr, width=90, subsequent_indent=pad + "  ")
    print(f"{pad}{_c(key + ':', 'bold', 'white')} {_c(wrapped, 'dim')}")


def _json_block(data: Any, indent: int = 2, max_items: int | None = None) -> None:
    if not _ENABLED:
        return
    pad = " " * indent
    if isinstance(data, list) and max_items is not None:
        data = data[:max_items]
    text = json.dumps(data, ensure_ascii=False, indent=2)
    for line in text.splitlines():
        print(pad + _c(line, "dim"))


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def trace_session_start(user_request: str, turn: int = 1) -> None:
    if not _ENABLED:
        return
    print()
    _hr("═", color="cyan")
    print(_c(f"  DEBUG_AGENT  |  Turn {turn}", "bold", "cyan"))
    _hr("═", color="cyan")
    _kv("User request", user_request)
    print()


def trace_profile(user_profile: dict) -> None:
    if not _ENABLED:
        return
    _header("STEP 1 — Intent Extraction (user profile)", "①", "yellow")
    for k, v in user_profile.items():
        _kv(k, v)
    print()


def trace_decomposition(decomposition: dict) -> None:
    if not _ENABLED:
        return
    _header("STEP 2 — Query Decomposition", "②", "yellow")
    _kv("strategy_queries", decomposition.get("strategy_queries", []))
    _kv("geo_queries",      decomposition.get("geo_queries", []))
    _kv("condition_queries",decomposition.get("condition_queries", {}))
    print()


def trace_rag_input(queries: list[str], city: str, travel_type: str, top_k: int) -> None:
    if not _ENABLED:
        return
    _header("STEP 3 — RAG Retrieval INPUT", "③", "blue")
    _kv("city",        city)
    _kv("travel_type", travel_type)
    _kv("top_k",       top_k)
    _kv("queries",     queries)
    print()


def trace_rag_output(result: dict) -> None:
    if not _ENABLED:
        return
    _header("STEP 3 — RAG Retrieval OUTPUT", "③", "green")
    _kv("retrieval_mode",    result.get("retrieval_mode", "?"))
    _kv("source",            result.get("source", "?"))
    _kv("total_chunks",      len(result.get("results", [])))
    _kv("recommended_pois",  result.get("recommended_pois", []))
    _kv("theme_suggestions", result.get("theme_suggestions", []))
    _kv("local_pitfalls",    result.get("local_pitfalls", []))

    # Per-query diagnostics
    print(_c("  Per-query diagnostics:", "bold", "white"))
    for q in result.get("queries", []):
        print(_c(f"    • [{q.get('search_backend','?')}] score_count={q.get('result_count',0)}", "dim"))
        print(_c(f"      query: {q.get('query','')}", "dim"))
        print(_c(f"      top chunks: {q.get('top_chunk_ids',[])}", "dim"))

    # Show top-3 raw chunks
    chunks = result.get("results", [])[:3]
    if chunks:
        print(_c("  Top-3 raw chunks:", "bold", "white"))
        for i, ch in enumerate(chunks, 1):
            snippet = ch.get("chunk_text", "")[:200].replace("\n", " ")
            print(_c(f"    [{i}] score={ch.get('score',0):.4f}  chunk_id={ch.get('chunk_id','?')}", "dim"))
            print(_c(f"        {snippet}…", "dim"))
    print()


def trace_tool_call(tool_name: str, arguments: dict, result: Any) -> None:
    """Trace any non-RAG tool call (city context, weather, POI, cost, tips)."""
    if not _ENABLED:
        return
    icons = {
        "get_city_context":    ("④", "magenta"),
        "search_batch_pois":   ("⑤", "magenta"),
        "get_weather_forecast":("⑥", "magenta"),
        "get_cost_summary":    ("⑦", "magenta"),
        "get_travel_tips":     ("⑧", "magenta"),
    }
    icon, color = icons.get(tool_name, ("•", "white"))
    _header(f"TOOL — {tool_name}", icon, color)
    _kv("arguments", arguments)

    # Summarize result rather than dumping everything
    if isinstance(result, dict):
        summary: dict = {}
        if "results" in result:
            summary["result_count"] = len(result["results"])
            summary["sample_names"] = [r.get("name", r.get("chunk_id", "?")) for r in result["results"][:4]]
        for field in ("provider", "retrieval_mode", "city", "total_cost", "daily_cost",
                      "budget_level", "forecast", "tips_count"):
            if field in result:
                summary[field] = result[field]
        if "tips" in result:
            summary["tips_count"] = len(result["tips"])
        _kv("result_summary", summary)
    else:
        _kv("result", str(result)[:200])
    print()


def trace_planner_input(strategy_context: dict, selected_poi_count: int) -> None:
    if not _ENABLED:
        return
    _header("STEP 4 — Planner INPUT (how RAG feeds planning)", "④", "blue")
    _kv("rag_recommended_pois (fed to planner)", strategy_context.get("recommended_pois", []))
    _kv("neighborhood_notes_count", len(strategy_context.get("neighborhood_notes", [])))
    _kv("total_pois_before_select", selected_poi_count)
    print()


def trace_plan_output(plan: dict) -> None:
    if not _ENABLED:
        return
    _header("STEP 5 — Final Plan OUTPUT", "⑤", "green")
    days = plan.get("days", [])
    _kv("total_days", len(days))
    for day in days:
        items = day.get("items", [])
        names = [it.get("poi_name", "?") for it in items]
        print(_c(f"  Day {day.get('day_index','?')}: {day.get('area','?')} | {day.get('theme','')}", "bold", "white"))
        print(_c(f"    POIs: {names}", "dim"))
    _kv("planning_notes", plan.get("planning_notes", []))
    print()
    _hr("═", color="cyan")
    print()


@contextmanager
def trace_step_timer(label: str):
    """Context manager that prints elapsed time for a step."""
    if not _ENABLED:
        yield
        return
    t0 = time.perf_counter()
    yield
    elapsed = time.perf_counter() - t0
    print(_c(f"  ⏱  {label}: {elapsed:.2f}s", "dim"))
    print()
