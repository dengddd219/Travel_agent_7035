from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(slots=True)
class CompanionState:
    city: str = "北京"
    current_location: str = ""
    current_coords: tuple[float, float] | None = None
    current_time: str = field(default_factory=_now_iso)
    location_updated_at: str = field(default_factory=_now_iso)
    base_location: str = ""
    party: dict[str, int] = field(
        default_factory=lambda: {"adults": 2, "elderly": 0, "children": 0}
    )
    confirmed_constraints: list[str] = field(default_factory=list)
    inferred_constraints: list[str] = field(default_factory=list)
    mobility_state: dict[str, Any] = field(default_factory=dict)
    remaining_plan: list[dict[str, Any]] = field(default_factory=list)
    destination_deadlines: list[dict[str, Any]] = field(default_factory=list)
    weather_snapshot: dict[str, Any] = field(default_factory=dict)
    active_orders: list[dict[str, Any]] = field(default_factory=list)
    turn_history: list[dict[str, str]] = field(default_factory=list)

    def update_time(self) -> None:
        self.current_time = _now_iso()

    def set_current_location(self, name: str, coords: tuple[float, float] | None = None) -> None:
        self.current_location = name
        self.current_coords = coords
        self.location_updated_at = _now_iso()

    def add_turn(self, role: str, content: str) -> None:
        self.turn_history.append({"role": role, "content": content})

    def to_dict(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "current_location": self.current_location,
            "current_coords": list(self.current_coords) if self.current_coords else None,
            "current_time": self.current_time,
            "location_updated_at": self.location_updated_at,
            "base_location": self.base_location,
            "party": self.party,
            "confirmed_constraints": self.confirmed_constraints,
            "inferred_constraints": self.inferred_constraints,
            "mobility_state": self.mobility_state,
            "remaining_plan": self.remaining_plan,
            "destination_deadlines": self.destination_deadlines,
            "weather_snapshot": self.weather_snapshot,
            "active_orders": self.active_orders,
            "turn_history": self.turn_history,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CompanionState":
        if not payload:
            return cls()

        coords = payload.get("current_coords")
        return cls(
            city=payload.get("city", "北京"),
            current_location=payload.get("current_location", ""),
            current_coords=tuple(coords) if coords else None,
            current_time=payload.get("current_time", _now_iso()),
            location_updated_at=payload.get("location_updated_at", _now_iso()),
            base_location=payload.get("base_location", ""),
            party=payload.get("party", {"adults": 2, "elderly": 0, "children": 0}),
            confirmed_constraints=payload.get("confirmed_constraints", []),
            inferred_constraints=payload.get("inferred_constraints", []),
            mobility_state=payload.get("mobility_state", {}),
            remaining_plan=payload.get("remaining_plan", []),
            destination_deadlines=payload.get("destination_deadlines", []),
            weather_snapshot=payload.get("weather_snapshot", {}),
            active_orders=payload.get("active_orders", []),
            turn_history=payload.get("turn_history", []),
        )


@dataclass(slots=True)
class AgentTurnResult:
    reply: str
    intent: str
    cards: list[dict[str, Any]] = field(default_factory=list)
    tool_logs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    state: CompanionState | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
