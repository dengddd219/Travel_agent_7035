from __future__ import annotations

from models import CompanionState


def test_phase1_state_fields_round_trip():
    state = CompanionState(city="Beijing")
    state.current_location = "Hotel"
    state.completed_nodes = ["Summer Palace"]
    state.skipped_nodes = ["Nanluoguxiang"]
    state.deferred_nodes = ["National Museum"]
    state.time_budget_hours = 4
    state.current_task = {"intent": "replan"}
    state.task_stack = [{"intent": "replan"}]
    state.subtasks = [{"name": "fit_time_budget", "status": "pending"}]
    state.task_status = "needs_clarification"
    state.clarification_pending = "current_location"
    state.clarification_resume_intent = "replan"
    state.self_check_results = [{"ok": True}]

    restored = CompanionState.from_dict(state.to_dict())

    assert restored.current_location == "Hotel"
    assert restored.completed_nodes == ["Summer Palace"]
    assert restored.skipped_nodes == ["Nanluoguxiang"]
    assert restored.deferred_nodes == ["National Museum"]
    assert restored.time_budget_hours == 4
    assert restored.current_task == {"intent": "replan"}
    assert restored.task_stack == [{"intent": "replan"}]
    assert restored.subtasks == [{"name": "fit_time_budget", "status": "pending"}]
    assert restored.task_status == "needs_clarification"
    assert restored.clarification_pending == "current_location"
    assert restored.clarification_resume_intent == "replan"
    assert restored.self_check_results == [{"ok": True}]
