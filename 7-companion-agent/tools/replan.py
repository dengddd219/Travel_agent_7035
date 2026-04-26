from __future__ import annotations

from typing import Any

from tools.replan_validator import validate_replan


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _node_name(node: dict[str, Any]) -> str:
    return str(node.get("poi_name") or node.get("name") or "").strip()


def _matches_any(name: str, blocked_names: set[str]) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    return any(blocked and (normalized == blocked or blocked in normalized) for blocked in blocked_names)


def _priority(node: dict[str, Any]) -> float:
    if node.get("must_visit"):
        return 100.0
    return _as_float(node.get("priority"), 0.0)


def _sort_candidates(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        nodes,
        key=lambda node: (
            -_priority(node),
            _as_float(node.get("distance_km"), 0.0),
            _as_float(node.get("duration_hours"), 1.0),
            str(node.get("time_slot") or ""),
        ),
    )


def _should_drop_for_retry(node: dict[str, Any], constraints: dict[str, Any]) -> str | None:
    if constraints.get("_drop_far_nodes") and constraints.get("max_distance_km") is not None:
        if _as_float(node.get("distance_km"), 0.0) > _as_float(constraints.get("max_distance_km")):
            return "too_far"
    if constraints.get("_drop_mobility_risky"):
        if str(node.get("mobility_level", "")).lower() == "high" or _as_float(node.get("walking_km"), 0.0) > 2.0:
            return "mobility_risk"
    return None


def _build_summary(
    new_plan: list[dict[str, Any]],
    removed_nodes: list[dict[str, Any]],
    deferred_nodes: list[dict[str, Any]],
    time_budget_hours: float | None,
) -> str:
    if not new_plan:
        return "No feasible itinerary remains under the current constraints."
    names = ", ".join(_node_name(node) for node in new_plan)
    total_hours = sum(_as_float(node.get("duration_hours"), 1.0) for node in new_plan)
    budget = f" within {time_budget_hours:.1f}h" if time_budget_hours is not None else ""
    parts = [f"Replanned {len(new_plan)} stop(s){budget}: {names}. Estimated visit time: {total_hours:.1f}h."]
    if removed_nodes:
        parts.append("Removed: " + ", ".join(_node_name(node) for node in removed_nodes) + ".")
    if deferred_nodes:
        parts.append("Deferred: " + ", ".join(_node_name(node) for node in deferred_nodes) + ".")
    return " ".join(parts)


def _plan_once(
    remaining_plan: list[dict[str, Any]],
    current_location: str = "",
    time_budget_hours: float | None = None,
    completed_nodes: list[str] | None = None,
    skipped_nodes: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    constraints = dict(constraints or {})
    completed = {name.strip().lower() for name in (completed_nodes or []) if name}
    skipped = {name.strip().lower() for name in (skipped_nodes or constraints.get("avoid_pois") or []) if name}
    prefer_indoor = bool(constraints.get("prefer_indoor"))
    time_budget = time_budget_hours
    if time_budget is None and constraints.get("time_budget_hours") is not None:
        time_budget = _as_float(constraints.get("time_budget_hours"))

    kept_candidates: list[dict[str, Any]] = []
    removed_nodes: list[dict[str, Any]] = []

    for node in remaining_plan:
        copied = dict(node)
        name = _node_name(copied)
        remove_reason = None
        if _matches_any(name, completed):
            remove_reason = "completed"
        elif _matches_any(name, skipped):
            remove_reason = "skipped"
        elif prefer_indoor and str(copied.get("indoor_outdoor", "")).lower() == "outdoor":
            remove_reason = "outdoor_filtered"
        else:
            remove_reason = _should_drop_for_retry(copied, constraints)

        if remove_reason:
            copied["remove_reason"] = remove_reason
            removed_nodes.append(copied)
        else:
            kept_candidates.append(copied)

    selected: list[dict[str, Any]] = []
    deferred_nodes: list[dict[str, Any]] = []
    used_hours = 0.0

    sorted_candidates = _sort_candidates(kept_candidates)
    for node in sorted_candidates:
        duration = _as_float(node.get("duration_hours"), 1.0)
        if time_budget is not None and used_hours + duration > time_budget:
            deferred = dict(node)
            deferred["defer_reason"] = "over_time_budget"
            deferred_nodes.append(deferred)
            continue
        selected.append(node)
        used_hours += duration

    selected.sort(key=lambda node: str(node.get("time_slot") or ""))

    result = {
        "status": "ok" if selected else "no_feasible_plan",
        "current_location": current_location,
        "new_plan": selected,
        "removed_nodes": removed_nodes,
        "deferred_nodes": deferred_nodes,
        "warnings": [],
        "summary": _build_summary(selected, removed_nodes, deferred_nodes, time_budget),
    }

    validation_constraints = dict(constraints)
    if time_budget is not None:
        validation_constraints["time_budget_hours"] = time_budget
    validation = validate_replan(result, validation_constraints)
    result["warnings"] = validation["warnings"]
    result["self_check"] = validation
    if not validation["ok"] and selected:
        result["status"] = "needs_review"
    return result


def _next_retry_constraints(constraints: dict[str, Any], reasons: list[str]) -> dict[str, Any] | None:
    next_constraints = dict(constraints)
    changed = False
    if "too_far" in reasons and constraints.get("max_distance_km") is not None:
        next_constraints["_drop_far_nodes"] = True
        changed = True
    if "weather_mismatch" in reasons:
        next_constraints["prefer_indoor"] = True
        changed = True
    if "mobility_risk" in reasons:
        next_constraints["_drop_mobility_risky"] = True
        changed = True
    if "over_time_budget" in reasons:
        next_constraints["_strict_time_budget"] = True
        changed = True
    return next_constraints if changed and next_constraints != constraints else None


def replan_itinerary(
    remaining_plan: list[dict[str, Any]],
    current_location: str = "",
    time_budget_hours: float | None = None,
    completed_nodes: list[str] | None = None,
    skipped_nodes: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    constraints = dict(constraints or {})
    max_retry_passes = int(_as_float(constraints.get("max_retry_passes"), 2.0))
    max_retry_passes = max(0, min(max_retry_passes, 2))

    result = _plan_once(
        remaining_plan=remaining_plan,
        current_location=current_location,
        time_budget_hours=time_budget_hours,
        completed_nodes=completed_nodes,
        skipped_nodes=skipped_nodes,
        constraints=constraints,
    )
    self_check_history = [dict(result.get("self_check", {}))]
    retry_reasons: list[str] = []

    retry_constraints = dict(constraints)
    for _ in range(max_retry_passes):
        self_check = result.get("self_check", {})
        reasons = list(self_check.get("reasons") or [])
        if self_check.get("ok") or not reasons:
            break
        next_constraints = _next_retry_constraints(retry_constraints, reasons)
        if not next_constraints:
            break
        retry_reasons.extend(reason for reason in reasons if reason not in retry_reasons)
        retry_constraints = next_constraints
        result = _plan_once(
            remaining_plan=remaining_plan,
            current_location=current_location,
            time_budget_hours=time_budget_hours,
            completed_nodes=completed_nodes,
            skipped_nodes=skipped_nodes,
            constraints=retry_constraints,
        )
        self_check_history.append(dict(result.get("self_check", {})))

    result["self_check_history"] = self_check_history
    result["retry_count"] = max(0, len(self_check_history) - 1)
    if result["retry_count"]:
        result["retry_reasons"] = retry_reasons
        result["summary"] += " Self-check retry applied for: " + ", ".join(retry_reasons) + "."
    return result
