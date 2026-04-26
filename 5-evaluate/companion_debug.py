# -*- coding: utf-8 -*-
"""Standalone debugger for the in-trip CompanionAgent.

Usage examples:
    python 5-evaluate/companion_debug.py --plan chat_response.json --day 2
    python 5-evaluate/companion_debug.py --plan my_4_day_plan.json --day 3 --no-llm --message "We only have 4 hours, replan."

The input can be either a raw itinerary_json object or the full /api/chat
response containing an itinerary_json field.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMPANION_DIR = ROOT / "7-companion-agent"
if str(COMPANION_DIR) not in sys.path:
    sys.path.insert(0, str(COMPANION_DIR))

from companion_agent import CompanionAgent  # noqa: E402
from config import Settings  # noqa: E402
from models import CompanionState  # noqa: E402


SAMPLE_ITINERARY: dict[str, Any] = {
    "city": "Beijing",
    "selected_pois": [
        {
            "name": "Summer Palace",
            "category": "culture",
            "district": "Haidian",
            "indoor_outdoor": "outdoor",
            "duration_hours": 2.5,
            "ticket_price": 30,
            "priority": 5,
            "lat": 39.9999,
            "lon": 116.2755,
        },
        {
            "name": "National Museum",
            "category": "museum",
            "district": "Dongcheng",
            "indoor_outdoor": "indoor",
            "duration_hours": 2.0,
            "ticket_price": 0,
            "priority": 4,
            "lat": 39.9051,
            "lon": 116.3976,
        },
        {
            "name": "Nanluoguxiang",
            "category": "shopping",
            "district": "Dongcheng",
            "indoor_outdoor": "outdoor",
            "duration_hours": 1.5,
            "ticket_price": 0,
            "priority": 2,
            "lat": 39.9337,
            "lon": 116.4030,
        },
    ],
    "days": [
        {"day_index": 1, "items": [{"poi_name": "Summer Palace", "time_slot": "morning"}]},
        {"day_index": 2, "items": [{"poi_name": "National Museum", "time_slot": "afternoon"}]},
        {
            "day_index": 3,
            "items": [
                {"poi_name": "Summer Palace", "time_slot": "afternoon", "duration_hours": 2.5},
                {"poi_name": "National Museum", "time_slot": "afternoon", "duration_hours": 2.0},
                {"poi_name": "Nanluoguxiang", "time_slot": "evening", "duration_hours": 1.5},
            ],
        },
        {"day_index": 4, "items": [{"poi_name": "Nanluoguxiang", "time_slot": "evening"}]},
    ],
}


def load_itinerary(path: Path | None) -> dict[str, Any]:
    if path is None:
        return deepcopy(SAMPLE_ITINERARY)
    raw_text = path.read_text(encoding="utf-8-sig")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return parse_text_itinerary(raw_text)
    if isinstance(payload, dict) and isinstance(payload.get("itinerary_json"), dict):
        return payload["itinerary_json"]
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Unsupported plan shape: {path}")


def parse_text_itinerary(raw_text: str) -> dict[str, Any]:
    """Best-effort parser for a plain-text 4-day strategy.

    Structured itinerary_json is still preferred. This fallback is intentionally
    simple so you can paste a rough guide into a .txt/.md file and start probing
    the companion flow from terminal.
    """
    days: list[dict[str, Any]] = []
    current_day: dict[str, Any] | None = None
    day_pattern = re.compile(r"^\s*(?:#+\s*)?(?:day\s*(\d+)|第\s*([一二三四五六七八九十\d]+)\s*天)", re.IGNORECASE)
    stop_pattern = re.compile(
        r"^\s*(上午|中午|下午|晚上|早上|傍晚|morning|noon|afternoon|evening|night)\s*[:：]\s*(.+)$",
        re.IGNORECASE,
    )
    skip_prefixes = (
        "主题",
        "天气",
        "预计费用",
        "路途时间",
        "原因",
        "天气适配",
        "交通",
        "备注",
        "规划摘要",
        "每日行程",
    )

    def chinese_day_to_int(value: str) -> int:
        mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        if value.isdigit():
            return int(value)
        if value == "十":
            return 10
        if value.startswith("十"):
            return 10 + mapping.get(value[1:], 0)
        if value.endswith("十"):
            return mapping.get(value[:-1], 1) * 10
        if "十" in value:
            left, right = value.split("十", 1)
            return mapping.get(left, 1) * 10 + mapping.get(right, 0)
        return mapping.get(value, len(days) + 1)

    def clean_stop_name(line: str) -> str:
        value = re.sub(r"^\s*[-*•\d.、\)\s]+", "", line).strip()
        value = re.sub(r"^(上午|中午|下午|晚上|早上|傍晚|morning|afternoon|evening|night)[:：\s-]*", "", value, flags=re.IGNORECASE)
        value = re.split(r"[，,。；;｜|:：\-–—]", value, maxsplit=1)[0].strip()
        value = re.sub(r"\([^)]*\)", "", value).strip()
        value = re.sub(r"\s*\([^)]*$", "", value).strip()
        return value[:80]

    city = ""
    first_line = next((line.strip() for line in raw_text.splitlines() if line.strip()), "")
    city_match = re.match(r"^([A-Za-z\u4e00-\u9fff·\s]+?)\s+(?:智能旅行规划|旅行|Travel)", first_line)
    if city_match:
        city = city_match.group(1).strip()

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = day_pattern.search(stripped)
        if match:
            if current_day:
                days.append(current_day)
            raw_day = match.group(1) or match.group(2) or str(len(days) + 1)
            current_day = {"day_index": chinese_day_to_int(raw_day), "items": []}
            continue
        if current_day is None:
            continue
        if stripped.startswith(skip_prefixes):
            continue
        stop_match = stop_pattern.match(stripped)
        if not stop_match:
            continue
        time_slot, stop_text = stop_match.groups()
        name = clean_stop_name(stop_text)
        if name and len(name) >= 2:
            current_day["items"].append(
                {
                    "poi_name": name,
                    "time_slot": time_slot,
                    "duration_hours": 1.5,
                    "indoor_outdoor": "mixed",
                }
            )
    if current_day:
        days.append(current_day)
    if not days:
        raise ValueError("Could not parse itinerary text. Prefer exporting itinerary_json from /api/chat.")
    return {"city": city, "selected_pois": [], "days": days}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _poi_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _find_day(itinerary: dict[str, Any], day_number: int) -> dict[str, Any]:
    days = itinerary.get("days") or []
    if not isinstance(days, list) or not days:
        raise ValueError("itinerary_json.days is empty")
    for day in days:
        if int(day.get("day_index") or 0) == day_number:
            return day
    index = day_number - 1
    if 0 <= index < len(days):
        return days[index]
    raise ValueError(f"Day {day_number} not found. Available days: {len(days)}")


def normalize_companion_node(item: dict[str, Any], idx: int, poi_meta_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    poi = poi_meta_by_name.get(_poi_key(item.get("poi_name") or item.get("name")), {})
    duration = _as_float(item.get("duration_hours", poi.get("duration_hours")), 1.5)
    distance_m = _as_float(item.get("arrival_distance_m"), 0.0)
    node = dict(poi)
    node.update(
        {
            "poi_name": item.get("poi_name") or item.get("name") or poi.get("name") or "",
            "time_slot": item.get("time_slot") or "",
            "duration_hours": duration,
            "category": item.get("category") or poi.get("category") or "",
            "district": item.get("district") or poi.get("district") or "",
            "indoor_outdoor": item.get("indoor_outdoor") or poi.get("indoor_outdoor") or "mixed",
            "est_cost": _as_float(item.get("est_cost", poi.get("ticket_price")), 0.0),
            "transport_hint": item.get("transport_hint") or "",
            "priority": _as_float(item.get("priority", poi.get("priority")), max(1, 5 - idx)),
            "must_visit": bool(item.get("must_visit") or idx == 0),
            "lat": item.get("lat", poi.get("lat")),
            "lon": item.get("lon", poi.get("lon")),
            "address": item.get("address") or poi.get("address") or "",
            "opening_hours": item.get("opening_hours") or poi.get("open_hours") or poi.get("opening_hours") or "",
        }
    )
    if distance_m > 0:
        node["distance_km"] = distance_m / 1000
    elif "distance_km" not in node:
        node["distance_km"] = _as_float(item.get("distance_km"), 0.0)
    return node


def build_state_for_day(
    itinerary: dict[str, Any],
    day_number: int,
    *,
    city_override: str = "",
    current_location: str = "",
    current_coords: tuple[float, float] | None = None,
) -> CompanionState:
    day = _find_day(itinerary, day_number)
    poi_meta_by_name = {
        _poi_key(poi.get("name")): poi
        for poi in itinerary.get("selected_pois", [])
        if isinstance(poi, dict) and poi.get("name")
    }
    state = CompanionState(city=city_override or str(itinerary.get("city") or itinerary.get("city_zh") or ""))
    state.remaining_plan = [
        normalize_companion_node(item, idx, poi_meta_by_name)
        for idx, item in enumerate(day.get("items") or [])
        if isinstance(item, dict)
    ]
    if current_location:
        state.set_current_location(current_location, current_coords)
    return state


def build_states_for_all_days(
    itinerary: dict[str, Any],
    *,
    city_override: str = "",
    current_location: str = "",
    current_coords: tuple[float, float] | None = None,
) -> dict[int, CompanionState]:
    states: dict[int, CompanionState] = {}
    for index, day in enumerate(itinerary.get("days") or [], start=1):
        day_number = int(day.get("day_index") or index)
        states[day_number] = build_state_for_day(
            itinerary,
            day_number,
            city_override=city_override,
            current_location=current_location,
            current_coords=current_coords,
        )
    if not states:
        raise ValueError("No days found in itinerary.")
    return states


def print_days(states_by_day: dict[int, CompanionState], active_day: int) -> None:
    print("\n=== Loaded itinerary days ===")
    for day_number in sorted(states_by_day):
        state = states_by_day[day_number]
        names = [str(node.get("poi_name") or node.get("name") or "") for node in state.remaining_plan]
        marker = "*" if day_number == active_day else " "
        preview = " -> ".join(name for name in names if name) or "(empty)"
        print(f"{marker} Day {day_number}: {preview}")


def print_state(label: str, state: CompanionState) -> None:
    print(f"\n--- {label} ---")
    print(f"city: {state.city}")
    print(f"intent: {state.intent}")
    print(f"current_location: {state.current_location or '(empty)'}")
    print(f"clarification_pending: {state.clarification_pending}")
    print(f"time_budget_hours: {state.time_budget_hours}")
    print(f"completed_nodes: {state.completed_nodes}")
    print(f"skipped_nodes: {state.skipped_nodes}")
    print("remaining_plan:")
    for idx, node in enumerate(state.remaining_plan, start=1):
        print(
            "  "
            f"{idx}. {node.get('poi_name') or node.get('name')} | "
            f"{node.get('time_slot') or 'anytime'} | "
            f"{node.get('duration_hours', 1.5)}h | "
            f"{node.get('indoor_outdoor', 'mixed')} | "
            f"priority={node.get('priority', '')}"
        )


def print_result(result: Any, show_state_json: bool = False) -> None:
    print("\nAgent>")
    print(result.reply)
    print(f"\nintent: {result.intent}")
    if result.warnings:
        print("warnings:")
        print(json.dumps(result.warnings, ensure_ascii=False, indent=2))
    if result.tool_logs:
        print("tool_logs:")
        print(json.dumps(result.tool_logs, ensure_ascii=False, indent=2))
    if result.cards:
        print("cards:")
        print(json.dumps(result.cards[:2], ensure_ascii=False, indent=2))
    if show_state_json and result.state:
        print("state_json:")
        print(json.dumps(result.state.to_dict(), ensure_ascii=False, indent=2))


def build_agent(no_llm: bool) -> CompanionAgent:
    settings = Settings.from_env()
    if no_llm:
        settings.openai_api_key = ""
        settings.openai_model = ""
    return CompanionAgent(settings=settings)


def run_messages(
    agent: CompanionAgent,
    state: CompanionState,
    messages: list[str],
    show_state_json: bool,
    *,
    day_number: int | None = None,
) -> CompanionState:
    for index, message in enumerate(messages, start=1):
        day_label = f" | Day {day_number}" if day_number is not None else ""
        print(f"\n=== Turn {index}{day_label} ===")
        print(f"You> {message}")
        result = agent.run_turn(message, state=state)
        state = result.state or state
        print_result(result, show_state_json=show_state_json)
        print_state("state after turn", state)
    return state


def print_help() -> None:
    print(
        """
Commands:
  /days              list all injected day states
  /day N             switch active day
  /plan [N]          print remaining_plan for active day or day N
  /state [N]         print compact CompanionState for active day or day N
  /debug on|off      toggle cards/tool/state-json verbosity
  /save PATH         save all day states to JSON
  /exit              quit

Anything else is sent to CompanionAgent for the active day.
Examples:
  我现在在外滩，老人摔跤了怎么办
  我们只剩4小时了，帮我重排
  已经逛完外滩了，后面不想去豫园
""".strip()
    )


def resolve_day_arg(parts: list[str], active_day: int, states_by_day: dict[int, CompanionState]) -> int:
    if len(parts) < 2:
        return active_day
    try:
        day_number = int(parts[1])
    except ValueError as exc:
        raise ValueError("Day must be a number.") from exc
    if day_number not in states_by_day:
        raise ValueError(f"Day {day_number} not loaded.")
    return day_number


def save_all_states(path: Path, states_by_day: dict[int, CompanionState], active_day: int) -> None:
    payload = {
        "active_day": active_day,
        "days": {str(day): state.to_dict() for day, state in sorted(states_by_day.items())},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved all companion states: {path}")


def interactive_loop(
    agent: CompanionAgent,
    states_by_day: dict[int, CompanionState],
    active_day: int,
    *,
    show_state_json: bool,
) -> tuple[dict[int, CompanionState], int]:
    verbose = show_state_json
    print_days(states_by_day, active_day)
    print_help()
    while True:
        try:
            raw = input(f"\nDay {active_day} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw.lower() in {"/exit", "exit", "quit", "/quit"}:
            break
        if raw == "/help":
            print_help()
            continue

        parts = raw.split()
        command = parts[0].lower()
        try:
            if command == "/days":
                print_days(states_by_day, active_day)
                continue
            if command == "/day":
                active_day = resolve_day_arg(parts, active_day, states_by_day)
                print_state(f"active day {active_day}", states_by_day[active_day])
                continue
            if command == "/plan":
                day_number = resolve_day_arg(parts, active_day, states_by_day)
                print_state(f"day {day_number}", states_by_day[day_number])
                continue
            if command == "/state":
                day_number = resolve_day_arg(parts, active_day, states_by_day)
                print_state(f"day {day_number}", states_by_day[day_number])
                print(json.dumps(states_by_day[day_number].to_dict(), ensure_ascii=False, indent=2))
                continue
            if command == "/debug":
                if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
                    print("Usage: /debug on|off")
                    continue
                verbose = parts[1].lower() == "on"
                print(f"debug verbosity: {'on' if verbose else 'off'}")
                continue
            if command == "/save":
                if len(parts) < 2:
                    print("Usage: /save PATH")
                    continue
                save_all_states(Path(parts[1]), states_by_day, active_day)
                continue
        except ValueError as exc:
            print(f"Command error: {exc}")
            continue

        states_by_day[active_day] = run_messages(
            agent,
            states_by_day[active_day],
            [raw],
            show_state_json=verbose,
            day_number=active_day,
        )
    return states_by_day, active_day


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone CompanionAgent debugger")
    parser.add_argument("--plan", type=Path, help="Path to itinerary_json or full /api/chat response JSON.")
    parser.add_argument("--day", type=int, default=1, help="Initial active day number.")
    parser.add_argument("--message", action="append", default=[], help="Message to send. Repeat for multi-turn debugging.")
    parser.add_argument("--city", default="", help="Override city injected into CompanionState.")
    parser.add_argument("--current-location", default="", help="Seed current location to skip the clarification/location-resolve step.")
    parser.add_argument("--current-lat", type=float, help="Optional latitude for --current-location.")
    parser.add_argument("--current-lon", type=float, help="Optional longitude for --current-location.")
    parser.add_argument("--no-llm", action="store_true", help="Force deterministic fallback mode.")
    parser.add_argument("--state-json", action="store_true", help="Print full state JSON after each turn.")
    parser.add_argument("--save-state", type=Path, help="Write final CompanionState JSON to this path.")
    args = parser.parse_args()

    itinerary = load_itinerary(args.plan)
    coords = None
    if args.current_lat is not None and args.current_lon is not None:
        coords = (args.current_lat, args.current_lon)
    states_by_day = build_states_for_all_days(
        itinerary,
        city_override=args.city,
        current_location=args.current_location,
        current_coords=coords,
    )
    active_day = args.day if args.day in states_by_day else sorted(states_by_day)[0]
    agent = build_agent(no_llm=args.no_llm)

    print(f"\nLLM enabled: {bool(agent.client)}")
    print("Tip: use --no-llm to isolate deterministic task flow.")

    if args.message:
        print_days(states_by_day, active_day)
        states_by_day[active_day] = run_messages(
            agent,
            states_by_day[active_day],
            args.message,
            show_state_json=args.state_json,
            day_number=active_day,
        )
    else:
        states_by_day, active_day = interactive_loop(
            agent,
            states_by_day,
            active_day,
            show_state_json=args.state_json,
        )

    if args.save_state:
        args.save_state.parent.mkdir(parents=True, exist_ok=True)
        save_all_states(args.save_state, states_by_day, active_day)


if __name__ == "__main__":
    main()
