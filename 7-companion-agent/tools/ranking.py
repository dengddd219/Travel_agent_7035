from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _normalize_text(values: list[str]) -> str:
    return " ".join(value.lower() for value in values if value).strip()


def _budget_weight(constraints: list[str], candidate: dict[str, Any]) -> float:
    text = _normalize_text(constraints)
    price_level = candidate.get("price_level")
    if not price_level:
        return 0.0
    if "预算高" in text or "high budget" in text or "预算高一点" in text:
        return 2.0 if price_level >= 3 else 0.5
    if "预算低" in text or "省钱" in text:
        return 2.0 if price_level <= 2 else -1.5
    return 0.0


def _cuisine_penalty(constraints: list[str], candidate: dict[str, Any]) -> float:
    text = _normalize_text(constraints)
    candidate_text = _normalize_text(
        [
            candidate.get("name", ""),
            candidate.get("category", ""),
            candidate.get("type_text", ""),
        ]
    )
    penalty = 0.0
    if "不吃辣" in text and any(token in candidate_text for token in ["川菜", "湘菜", "麻辣", "火锅"]):
        penalty -= 2.0
    if "不喜欢北京菜" in text and any(token in candidate_text for token in ["北京菜", "烤鸭", "京味"]):
        penalty -= 1.5
    return penalty


def _distance_score(candidate: dict[str, Any]) -> float:
    distance = candidate.get("distance_m")
    if distance is None:
        return 0.0
    if distance <= 500:
        return 3.0
    if distance <= 1200:
        return 2.0
    if distance <= 2500:
        return 1.0
    return -1.0


def _family_score(context: dict[str, Any], candidate: dict[str, Any]) -> float:
    party = context.get("party") or {}
    text = _normalize_text([candidate.get("name", ""), candidate.get("category", ""), candidate.get("type_text", "")])
    score = 0.0
    if party.get("children", 0) > 0 and any(token in text for token in ["亲子", "家庭", "商场", "综合体", "咖啡"]):
        score += 1.0
    if party.get("elderly", 0) > 0 and candidate.get("distance_m") and candidate["distance_m"] > 1500:
        score -= 1.0
    return score


def score_candidates(candidates: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    confirmed = context.get("confirmed_constraints", []) or []
    inferred = context.get("inferred_constraints", []) or []
    all_constraints = confirmed + inferred

    ranked: list[tuple[float, dict[str, Any], str]] = []
    for candidate in candidates:
        rating = float(candidate.get("rating") or 0.0)
        score = 0.0
        score += _distance_score(candidate)
        score += _budget_weight(all_constraints, candidate)
        score += _cuisine_penalty(all_constraints, candidate)
        score += _family_score(context, candidate)
        score += min(rating / 2.0, 2.5)

        reason_parts = []
        if candidate.get("distance_m") is not None:
            reason_parts.append(f"距离约 {candidate['distance_m']} 米")
        if rating:
            reason_parts.append(f"评分约 {rating}")
        if candidate.get("price_level"):
            reason_parts.append(f"价格级别 {candidate['price_level']}")
        ranked.append((score, candidate, "，".join(reason_parts)))

    ranked.sort(key=lambda item: item[0], reverse=True)
    primary = []
    backup = []
    reasons = []
    for index, (score, candidate, reason) in enumerate(ranked):
        enriched = dict(candidate)
        enriched["score"] = round(score, 2)
        enriched["ranking_reason"] = reason
        if index < 2:
            primary.append(enriched)
        elif index < 5:
            backup.append(enriched)
        reasons.append(f"{candidate.get('name', '')}: {reason or '综合得分较高'}")

    return {
        "primary": primary,
        "backup": backup,
        "ranking_reason": reasons[:5],
    }


def check_time_feasibility(current_time: str, stops: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.fromisoformat(current_time)
    timeline: list[dict[str, Any]] = []
    warnings: list[str] = []
    cursor = now
    total_travel_min = 0
    total_stay_min = 0

    for stop in stops:
        travel_min = int(stop.get("travel_duration_min", 0) or 0)
        dwell_min = int(stop.get("stay_duration_min", 60) or 60)
        total_travel_min += travel_min
        total_stay_min += dwell_min
        arrival = cursor + timedelta(minutes=travel_min)
        departure = arrival + timedelta(minutes=dwell_min)
        entry = {
            "name": stop.get("name", ""),
            "arrival_time": arrival.isoformat(timespec="minutes"),
            "departure_time": departure.isoformat(timespec="minutes"),
            "travel_duration_min": travel_min,
            "stay_duration_min": dwell_min,
        }
        close_by = stop.get("close_by")
        if close_by:
            try:
                close_dt = datetime.fromisoformat(close_by)
                if arrival > close_dt:
                    warnings.append(f"{stop.get('name', '')} 到达时可能已关闭。")
                elif departure > close_dt:
                    available_minutes = max(0, int((close_dt - arrival).total_seconds() // 60))
                    warnings.append(
                        f"{stop.get('name', '')} 虽然能赶到，但在关闭前大约只剩 {available_minutes} 分钟，不足以正常游览。"
                    )
            except Exception:
                pass
        timeline.append(entry)
        cursor = departure

    latest_departure_time = None
    if stops:
        first = stops[0]
        deadline = first.get("must_arrive_by")
        travel_min = int(first.get("travel_duration_min", 0) or 0)
        if deadline:
            try:
                deadline_dt = datetime.fromisoformat(deadline)
                latest_departure_time = (deadline_dt - timedelta(minutes=travel_min)).isoformat(timespec="minutes")
            except Exception:
                latest_departure_time = None

    return {
        "feasible": not warnings,
        "timeline": timeline,
        "latest_departure_time": latest_departure_time,
        "warnings": warnings,
        "total_travel_min": total_travel_min,
        "total_stay_min": total_stay_min,
    }
