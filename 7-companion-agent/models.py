from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(slots=True)
class CompanionState:
    city: str = "北京"
    intent: str = "search"
    current_goal: str = ""
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
    avoid_pois: list[str] = field(default_factory=list)
    prefer_indoor: bool = False
    budget_level: str = ""
    food_constraints: list[str] = field(default_factory=list)
    mobility_risk: str = "normal"
    weather_preference: str = ""
    replan_reason: str = ""
    mobility_state: dict[str, Any] = field(default_factory=dict)
    remaining_plan: list[dict[str, Any]] = field(default_factory=list)
    completed_nodes: list[str] = field(default_factory=list)
    skipped_nodes: list[str] = field(default_factory=list)
    deferred_nodes: list[str] = field(default_factory=list)
    time_budget_hours: float | None = None
    current_task: dict[str, Any] | None = None
    task_stack: list[dict[str, Any]] = field(default_factory=list)
    subtasks: list[dict[str, Any]] = field(default_factory=list)
    task_status: str | None = None
    clarification_pending: str | None = None
    clarification_resume_intent: str | None = None
    self_check_results: list[dict[str, Any]] = field(default_factory=list)
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
            "intent": self.intent,
            "current_goal": self.current_goal,
            "current_location": self.current_location,
            "current_coords": list(self.current_coords) if self.current_coords else None,
            "current_time": self.current_time,
            "location_updated_at": self.location_updated_at,
            "base_location": self.base_location,
            "party": self.party,
            "confirmed_constraints": self.confirmed_constraints,
            "inferred_constraints": self.inferred_constraints,
            "avoid_pois": self.avoid_pois,
            "prefer_indoor": self.prefer_indoor,
            "budget_level": self.budget_level,
            "food_constraints": self.food_constraints,
            "mobility_risk": self.mobility_risk,
            "weather_preference": self.weather_preference,
            "replan_reason": self.replan_reason,
            "mobility_state": self.mobility_state,
            "remaining_plan": self.remaining_plan,
            "completed_nodes": self.completed_nodes,
            "skipped_nodes": self.skipped_nodes,
            "deferred_nodes": self.deferred_nodes,
            "time_budget_hours": self.time_budget_hours,
            "current_task": self.current_task,
            "task_stack": self.task_stack,
            "subtasks": self.subtasks,
            "task_status": self.task_status,
            "clarification_pending": self.clarification_pending,
            "clarification_resume_intent": self.clarification_resume_intent,
            "self_check_results": self.self_check_results,
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
            intent=payload.get("intent", "search"),
            current_goal=payload.get("current_goal", ""),
            current_location=payload.get("current_location", ""),
            current_coords=tuple(coords) if coords else None,
            current_time=payload.get("current_time", _now_iso()),
            location_updated_at=payload.get("location_updated_at", _now_iso()),
            base_location=payload.get("base_location", ""),
            party=payload.get("party", {"adults": 2, "elderly": 0, "children": 0}),
            confirmed_constraints=payload.get("confirmed_constraints", []),
            inferred_constraints=payload.get("inferred_constraints", []),
            avoid_pois=payload.get("avoid_pois", []),
            prefer_indoor=payload.get("prefer_indoor", False),
            budget_level=payload.get("budget_level", ""),
            food_constraints=payload.get("food_constraints", []),
            mobility_risk=payload.get("mobility_risk", "normal"),
            weather_preference=payload.get("weather_preference", ""),
            replan_reason=payload.get("replan_reason", ""),
            mobility_state=payload.get("mobility_state", {}),
            remaining_plan=payload.get("remaining_plan", []),
            completed_nodes=payload.get("completed_nodes", []),
            skipped_nodes=payload.get("skipped_nodes", []),
            deferred_nodes=payload.get("deferred_nodes", []),
            time_budget_hours=payload.get("time_budget_hours"),
            current_task=payload.get("current_task"),
            task_stack=payload.get("task_stack", []),
            subtasks=payload.get("subtasks", []),
            task_status=payload.get("task_status"),
            clarification_pending=payload.get("clarification_pending"),
            clarification_resume_intent=payload.get("clarification_resume_intent"),
            self_check_results=payload.get("self_check_results", []),
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


@dataclass(slots=True)
class AgentAction:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    save_as: str = ""


@dataclass(slots=True)
class AgentPlan:
    intent: str
    goal: str = ""
    needs_clarification: bool = False
    clarification_question: str = ""
    state_updates: dict[str, Any] = field(default_factory=dict)
    actions: list[AgentAction] = field(default_factory=list)
    response_policy: str = "default"
    self_check_focus: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentObservation:
    tool: str
    args: dict[str, Any]
    output: Any
    save_as: str = ""
