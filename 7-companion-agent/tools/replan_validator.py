from __future__ import annotations

from datetime import datetime, time
from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _node_name(node: dict[str, Any]) -> str:
    return str(node.get("poi_name") or node.get("name") or "").strip()


def _parse_close_time(value: Any) -> time | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    # Common formats: "09:00-17:00", "17:00", "2026-04-26T17:00:00".
    if "-" in text and "T" not in text:
        text = text.split("-")[-1].strip()
    if "T" in text:
        try:
            return datetime.fromisoformat(text).time()
        except ValueError:
            return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _has_closing_risk(node: dict[str, Any], current_time: str | None) -> bool:
    close_time = _parse_close_time(node.get("closing_time") or node.get("close_time") or node.get("opening_hours"))
    if not close_time or not current_time:
        return False
    try:
        now = datetime.fromisoformat(current_time).time()
    except ValueError:
        return False
    return now >= close_time


def validate_replan(result: dict[str, Any], constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    constraints = constraints or {}
    new_plan = result.get("new_plan") or []
    warnings = list(result.get("warnings") or [])
    reasons: list[str] = []

    time_budget_hours = constraints.get("time_budget_hours")
    if time_budget_hours is not None:
        total_hours = sum(_as_float(node.get("duration_hours"), 1.0) for node in new_plan)
        if total_hours > _as_float(time_budget_hours):
            reasons.append("over_time_budget")
            warnings.append(
                f"Plan duration {total_hours:.1f}h exceeds budget {_as_float(time_budget_hours):.1f}h."
            )

    if constraints.get("prefer_indoor"):
        outdoor_nodes = [
            _node_name(node)
            for node in new_plan
            if str(node.get("indoor_outdoor", "")).lower() == "outdoor"
        ]
        if outdoor_nodes:
            reasons.append("weather_mismatch")
            warnings.append("Outdoor nodes remain despite indoor preference: " + ", ".join(outdoor_nodes))

    max_distance_km = constraints.get("max_distance_km")
    if max_distance_km is not None:
        far_nodes = [
            _node_name(node)
            for node in new_plan
            if _as_float(node.get("distance_km"), 0.0) > _as_float(max_distance_km)
        ]
        if far_nodes:
            reasons.append("too_far")
            warnings.append("Some nodes are farther than allowed: " + ", ".join(far_nodes))

    if constraints.get("mobility_risk") == "high":
        demanding_nodes = [
            _node_name(node)
            for node in new_plan
            if str(node.get("mobility_level", "")).lower() == "high"
            or _as_float(node.get("walking_km"), 0.0) > 2.0
        ]
        if demanding_nodes:
            reasons.append("mobility_risk")
            warnings.append("Some nodes may be too demanding: " + ", ".join(demanding_nodes))

    current_time = constraints.get("current_time")
    closing_nodes = [_node_name(node) for node in new_plan if _has_closing_risk(node, current_time)]
    if closing_nodes:
        reasons.append("closing_soon")
        warnings.append("Some nodes may already be closed or closing soon: " + ", ".join(closing_nodes))

    if new_plan and not any(node.get("must_visit") or _as_float(node.get("priority"), 0.0) >= 4 for node in new_plan):
        reasons.append("no_core_experience")
        warnings.append("Plan does not preserve any high-priority or must-visit POI.")

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "ok": not unique_reasons,
        "reasons": unique_reasons,
        "warnings": warnings,
    }
