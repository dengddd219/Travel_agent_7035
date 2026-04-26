"""Optional terminal tracing for the travel-planner pipeline.

Set ``DEBUG_AGENT=1`` to print compact orchestration traces. All functions are
no-ops by default, so production and tests do not pay for debug output.
"""
from __future__ import annotations

import json
import os
import textwrap
import time
from contextlib import contextmanager
from typing import Any

_TRUTHY = {"1", "true", "yes", "on"}
_ENABLED = (
    os.getenv("DEBUG_AGENT", "").strip().lower() in _TRUTHY
    or os.getenv("TRACE_AGENT", "").strip().lower() in _TRUTHY
)

_C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "red": "\033[31m",
    "white": "\033[97m",
}


def is_debug_enabled() -> bool:
    return _ENABLED


def _trace_full() -> bool:
    return os.getenv("TRACE_FULL", "").strip().lower() in _TRUTHY


def _preview_chars(default: int = 1200) -> int:
    raw = os.getenv("TRACE_PREVIEW_CHARS", "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _rag_chunk_limit(default: int = 3) -> int:
    raw = os.getenv("TRACE_RAG_CHUNKS", "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _c(text: str, *codes: str) -> str:
    if not _ENABLED:
        return text
    prefix = "".join(_C.get(code, "") for code in codes)
    return f"{prefix}{text}{_C['reset']}"


def _hr(char: str = "-", width: int = 72, color: str = "dim") -> None:
    if _ENABLED:
        print(_c(char * width, color))


def _header(title: str, color: str = "cyan") -> None:
    if not _ENABLED:
        return
    _hr("=", color=color)
    print(_c(title, "bold", color))
    _hr("-", color="dim")


def _short_json(value: Any, limit: int | None = None) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        text = str(value)
    if _trace_full():
        return text
    limit = _preview_chars() if limit is None else limit
    return text if limit <= 0 or len(text) <= limit else text[:limit].rstrip() + "..."


def _kv(key: str, value: Any, indent: int = 2) -> None:
    if not _ENABLED:
        return
    pad = " " * indent
    text = value if isinstance(value, str) else _short_json(value)
    wrapped = textwrap.fill(str(text), width=96, subsequent_indent=pad + "  ")
    print(f"{pad}{_c(key + ':', 'bold', 'white')} {_c(wrapped, 'dim')}")


def trace_session_start(user_request: str, turn: int | None = None) -> None:
    if not _ENABLED:
        return
    print()
    _header(f"Travel planner run{f' | turn {turn}' if turn else ''}", "cyan")
    _kv("user_request", user_request)
    print()


def trace_turn_understanding(understanding: Any) -> None:
    if not _ENABLED:
        return
    _header("Step 1 | Turn understanding", "yellow")
    _kv("source", getattr(understanding, "source", "unknown"))
    _kv("needs_clarification", getattr(understanding, "needs_clarification", False))
    _kv("missing_profile_slots", getattr(understanding, "missing_profile_slots", []))
    _kv("resolved_profile", getattr(understanding, "resolved_profile", {}))
    overrides = getattr(understanding, "decomposition_overrides", {})
    if overrides:
        _kv("decomposition_overrides", overrides)
    print()


def trace_profile(user_profile: dict) -> None:
    if not _ENABLED:
        return
    _header("Step 2 | Resolved profile", "yellow")
    _kv("profile", user_profile)
    print()


def trace_decomposition(decomposition: dict) -> None:
    if not _ENABLED:
        return
    _header("Step 3 | Retrieval decomposition", "blue")
    _kv("strategy_queries", decomposition.get("strategy_queries", []))
    _kv("geo_queries", decomposition.get("geo_queries", []))
    _kv("condition_queries", decomposition.get("condition_queries", {}))
    print()


def trace_rag_input(queries: list[str], city: str, travel_type: str, top_k: int) -> None:
    if not _ENABLED:
        return
    _header("Step 4 | RAG input", "blue")
    _kv("city", city)
    _kv("travel_type", travel_type)
    _kv("top_k", top_k)
    _kv("queries", queries)
    print()


def trace_rag_output(result: dict) -> None:
    if not _ENABLED:
        return
    _header("Step 4 | RAG output", "green")
    _kv("retrieval_mode", result.get("retrieval_mode", ""))
    _kv("source", result.get("source", ""))
    _kv("result_count", len(result.get("results", [])))
    _kv("recommended_pois", result.get("recommended_pois", []))
    _kv("theme_suggestions", result.get("theme_suggestions", []))
    _kv("local_pitfalls", result.get("local_pitfalls", []))
    _kv("evidence_chunk_count", len(result.get("evidence_chunks", []) or []))
    _kv("route_pair_hint_count", len(result.get("route_pair_hints", []) or []))
    _kv("pitfall_evidence_count", len(result.get("pitfall_evidence", []) or []))
    for item in result.get("queries", [])[:5]:
        _kv("query_diag", item, indent=4)
    results = result.get("results", []) or []
    limit = len(results) if _trace_full() else min(len(results), _rag_chunk_limit())
    if results and limit:
        _kv("chunk_trace_count", f"{limit}/{len(results)}")
    for index, item in enumerate(results[:limit], start=1):
        if not isinstance(item, dict):
            _kv(f"chunk_{index}", item, indent=4)
            continue
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        _kv(
            f"chunk_{index}",
            {
                "chunk_id": item.get("chunk_id", ""),
                "score": item.get("score", item.get("hybrid_score", "")),
                "title": metadata.get("title", ""),
                "source": metadata.get("source", metadata.get("file", "")),
                "poi_names": metadata.get("poi_names", []),
                "districts": metadata.get("districts", []),
                "tags": metadata.get("tags", []),
                "chunk_text": item.get("chunk_text", ""),
            },
            indent=4,
        )
    print()


def trace_tool_call(tool_name: str, arguments: dict, result: Any) -> None:
    if not _ENABLED:
        return
    _header(f"Tool | {tool_name}", "magenta")
    _kv("arguments", arguments)
    if isinstance(result, dict):
        summary: dict[str, Any] = {}
        for field in (
            "provider",
            "retrieval_mode",
            "source",
            "city",
            "budget_level",
            "total_cost",
            "daily_cost",
        ):
            if field in result:
                summary[field] = result[field]
        if "results" in result:
            summary["result_count"] = len(result.get("results", []))
            summary["sample"] = [
                item.get("name") or item.get("chunk_id") or item.get("title")
                for item in result.get("results", [])[:4]
                if isinstance(item, dict)
            ]
        if "forecast" in result:
            summary["forecast_days"] = len(result.get("forecast", []))
        if "tips" in result:
            summary["tips_count"] = len(result.get("tips", []))
        _kv("result_summary", summary or result)
    else:
        _kv("result", result)
    print()


def trace_planner_input(strategy_context: dict, selected_poi_count: int) -> None:
    if not _ENABLED:
        return
    _header("Step 5 | Planner input", "blue")
    _kv("selected_poi_count", selected_poi_count)
    _kv("rag_recommended_pois", strategy_context.get("recommended_pois", []))
    _kv("neighborhood_notes_count", len(strategy_context.get("neighborhood_notes", [])))
    print()


def trace_plan_output(plan: dict) -> None:
    if not _ENABLED:
        return
    _header("Step 6 | Plan output", "green")
    _kv("city", plan.get("city", ""))
    _kv("trip_days", plan.get("trip_days", ""))
    for day in plan.get("days", []):
        names = [item.get("poi_name", "?") for item in day.get("items", [])]
        _kv(f"day_{day.get('day_index', '?')}", names)
    _kv("review_summary", plan.get("review_summary", ""))
    print()


@contextmanager
def trace_step_timer(label: str):
    if not _ENABLED:
        yield
        return
    started_at = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started_at
        print(_c(f"  {label}: {elapsed:.2f}s", "dim"))
        print()
