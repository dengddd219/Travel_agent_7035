# Companion Agent Itinerary-Aware Replan Implementation Plan

## Current Progress

Current stage: **Phase 1 through Phase 5 implemented and tested**.

What already exists:
- `CompanionAgent` exists and can run as an LLM tool-calling agent when credentials are configured.
- The same agent also has a fallback rule path when no LLM credentials are available.
- `CompanionState` already has basic trip state and `remaining_plan`.
- Existing `_handle_replan()` can suggest nearby alternatives, but it is not yet a true itinerary-aware replanner.

What is done in Phase 1:
- Deterministic `replan_itinerary()` exists.
- `replan_validator` exists.
- `CompanionState` can round-trip completed/skipped/deferred nodes and `time_budget_hours`.
- Phase 1 tests pass.

What is done in Phase 2:
- `CompanionState` has task-state fields for `current_task`, `task_stack`, `subtasks`, `task_status`, clarification state, and self-check history.
- `CompanionAgent.run_turn()` has a shared task gate before both LLM and fallback execution.
- Replan requests without location save a pending task and ask for current location.
- Location-only answers can resume the pending replan task.
- Completed/skipped POIs are recorded before replanning.
- Phase 2 tests pass, including the case where an LLM client exists but the clarification gate must run first.

What is done in Phase 3:
- Main backend exposes `/api/companion`.
- `/api/companion` accepts `conversation_state`, runs `CompanionAgent`, and returns updated state.
- Frontend renders a lightweight companion panel after `/api/chat` returns an itinerary.
- Frontend day tabs inject only the selected day's plan into companion state.
- Frontend enriches day-plan items from `selected_pois` so companion receives `indoor_outdoor`, coordinates, address, opening hours, cost, and priority defaults.
- Backend route test and frontend inline JS syntax check pass.

What is done in Phase 4:
- `replan_itinerary()` now runs bounded self-check retry, capped at 2 passes.
- Retry policy can remove too-far nodes, switch toward indoor constraints, and remove mobility-risky nodes.
- Replan results include `self_check_history`, `retry_count`, and `retry_reasons`.
- Companion state stores final self-check, history, and retry count.
- Retry behavior is covered by tests.

What is done in Phase 5:
- `replan_itinerary` is exposed in `TOOL_SCHEMAS` for LLM tool-calling.
- LLM can request itinerary replanning through the deterministic tool.
- The tool is the source of truth for itinerary mutation and updates `state.remaining_plan`.
- Existing shared clarification gate still runs before LLM tool-calling.
- Tool schema and state mutation behavior are covered by tests.

What is not done yet:
- No full browser smoke test has been run because this environment does not have `uvicorn` installed.
- No real OpenAI/Azure LLM live call was executed; LLM integration is covered at schema/tool-call level.

What you should do now:
1. Run a browser smoke test in an environment with `uvicorn` installed.
2. Generate a real itinerary from `/api/chat`.
3. Open the companion panel, pick a day, and ask: "We only have 4 hours, replan."
4. Confirm companion asks for location if missing, then returns a selected-day replan.

Phase 1 completed file scope:
- `7-companion-agent/models.py`
- `7-companion-agent/tools/replan.py`
- `7-companion-agent/tools/replan_validator.py`
- `7-companion-agent/tests/test_replan.py`
- `7-companion-agent/tests/test_replan_validator.py`

Phase 1 success criteria:
- [x] Given a fixed day plan and a 4-hour budget, the replanner returns a shorter feasible afternoon itinerary.
- [x] Completed POIs are removed.
- [x] Skipped POIs are removed.
- [x] High-priority or `must_visit` POIs are preserved first.
- [x] The validator rejects plans that exceed the time budget.

Phase 2 completed file scope:
- `7-companion-agent/models.py`
- `7-companion-agent/companion_agent.py`
- `7-companion-agent/tests/test_companion_task_flow.py`

Phase 2 success criteria:
- [x] User asks for replan without location, and agent asks for current location.
- [x] User answers location only, and agent resumes the saved replan task.
- [x] User says a POI is finished, and state records it in `completed_nodes`.
- [x] The shared gate runs before LLM tool-calling.

Do not start Phase 3 until Phase 2 tests pass. This condition is now met.

Phase 3 completed file scope:
- `backend/server.py`
- `backend/tests/test_companion_route.py`
- `6-UI/UI/chat.html`

Phase 3 success criteria:
- [x] Main backend has `/api/companion`.
- [x] Backend route accepts a selected-day companion state.
- [x] Frontend can build companion state from selected itinerary day.
- [x] Frontend enriches day items from `selected_pois`.
- [x] Frontend can call `/api/companion` and update the panel state.

Do not start Phase 4 until Phase 3 route and JS syntax checks pass. This condition is now met.

Phase 4 completed file scope:
- `7-companion-agent/tools/replan.py`
- `7-companion-agent/companion_agent.py`
- `7-companion-agent/tests/test_replan.py`
- `7-companion-agent/tests/test_companion_task_flow.py`

Phase 4 success criteria:
- [x] If the first result is too far, retry removes far nodes.
- [x] Retry count and self-check history are returned.
- [x] Retry count and self-check history are stored in state.
- [x] Retry loop is bounded to at most 2 passes.

Phase 5 completed file scope:
- `7-companion-agent/companion_agent.py`
- `7-companion-agent/tests/test_companion_task_flow.py`

Phase 5 success criteria:
- [x] `replan_itinerary` appears in LLM tool schemas.
- [x] Tool-call execution updates `state.remaining_plan`.
- [x] Tool-call result declares `source_of_truth: replan_itinerary`.
- [x] Clarification gate remains before LLM tool-calling.

---

> For implementers: follow this plan task-by-task. Use checkbox updates as work proceeds.

**Goal:** 让陪伴 Agent 在旅行当天感知“当天剩余行程”，在用户触发临时调整时先澄清当前位置，再基于剩余节点做局部重排，而不是只给泛泛推荐。

**Architecture:** 主 agent 先生成 itinerary。前端按天展示，每个 day tab 下挂一个 companion 会话。用户切换到某天时，前端把该天的 `DayPlan` 注入 `CompanionState.remaining_plan`。当用户说“下雨了”“不想去这个点了”“老人走不动了”时，companion 先确认当前位置，再调用 `replan_itinerary` 对当天剩余行程做 deterministic 重排。

**Tech Stack:** Python 3.11, FastAPI, OpenAI function calling, Vanilla JS, 高德地图 JS SDK

---

## Reality Check

当前仓库不是从 0 到 1 新建 companion，而是在已有模块上增量改造。

- 已有 `CompanionAgent` 类，支持 LLM tool calling 和 fallback 规则流。
- 当前 `CompanionState` 有 `remaining_plan`，但没有 `completed_nodes` / `clarification_pending`。
- 当前 `_handle_replan()` 更像“找附近替代点”，不是“基于 remaining_plan 的局部重排”。
- 当前 `7-companion-agent/api.py` 是独立 `FastAPI` app，不是 `APIRouter`。
- 当前 `backend/server.py` 没有 `/api/companion`。
- 当前 `chat.html` 没有 day tabs + companion panel。

**关键约束：**

1. 不能只改 fallback，必须同时覆盖 LLM 和 fallback。
2. 不能假设 `DayPlanItem` 自带 `indoor_outdoor`，前端要从 `selected_pois` 回填。
3. 不能同时要求“直接在 backend 写路由”和“再 include_router”；二者必须二选一。

---

## File Map

| 文件 | 动作 | 责任 |
|---|---|---|
| `7-companion-agent/models.py` | 修改 | 扩展 `CompanionState` |
| `7-companion-agent/tools/replan.py` | 新建 | deterministic 局部重排工具 |
| `7-companion-agent/companion_agent.py` | 修改 | 共享澄清闸门、工具接入、状态更新 |
| `backend/server.py` | 修改 | 主后端暴露 `/api/companion` |
| `7-companion-agent/api.py` | 可选修改 | 仅当选择 router 路线时改造 |
| `6-UI/UI/chat.html` | 修改 | day tabs + companion chat + state injection |
| `7-companion-agent/tests/` | 新建目录 | 单测目录 |

---

## Task 0: 先对齐落地策略

- [ ] 明确本次只做“位置澄清 + 当天局部重排”，不做复杂进度推断，不做跨天重排。
- [ ] 先创建 `7-companion-agent/tests/` 目录。
- [ ] 后端接入默认采用 **方案 A**：
  直接在 `backend/server.py` 新增 `/api/companion`。
- [ ] 只有当你明确要做结构清理时，才采用 **方案 B**：
  把 `7-companion-agent/api.py` 改成 `APIRouter` 后再挂载。

---

## Task 1: 扩展 CompanionState

**Files**
- Modify: `7-companion-agent/models.py`
- Create: `7-companion-agent/tests/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
from models import CompanionState

def test_companion_state_has_itinerary_fields():
    state = CompanionState(city="北京")
    assert hasattr(state, "completed_nodes")
    assert state.completed_nodes == []
    assert hasattr(state, "clarification_pending")
    assert state.clarification_pending is None
    assert hasattr(state, "clarification_resume_intent")
    assert state.clarification_resume_intent is None

def test_from_dict_round_trips_new_fields():
    state = CompanionState(city="上海")
    state.completed_nodes = ["外滩", "豫园"]
    state.clarification_pending = "current_location"
    state.clarification_resume_intent = "replan"
    d = state.to_dict()
    restored = CompanionState.from_dict(d)
    assert restored.completed_nodes == ["外滩", "豫园"]
    assert restored.clarification_pending == "current_location"
    assert restored.clarification_resume_intent == "replan"
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd 7-companion-agent
python -m pytest tests/test_models.py -v
```

- [ ] **Step 3: 修改 `models.py`**

在 `remaining_plan` 后添加：

```python
completed_nodes: list[str] = field(default_factory=list)
clarification_pending: str | None = None
clarification_resume_intent: str | None = None
```

同步更新 `to_dict()` / `from_dict()`。

- [ ] **Step 3.5: 明确 `remaining_plan` 的统一 schema**

从本任务开始，`remaining_plan` 里的每个节点统一使用下面的结构：

```python
{
    "poi_name": str,
    "time_slot": str,
    "duration_hours": float,
    "category": str,
    "district": str,
    "indoor_outdoor": str,
    "est_cost": float,
    "transport_hint": str,
    # optional passthrough fields:
    "lat": float,
    "lon": float,
    "address": str,
}
```

后续所有写入 `state.remaining_plan` 的地方都必须遵守这个 schema。

- [ ] **Step 4: 重新跑测试**

```bash
python -m pytest tests/test_models.py -v
```

---

## Task 2: 新建 deterministic `replan_itinerary`

**Files**
- Create: `7-companion-agent/tools/replan.py`
- Create: `7-companion-agent/tests/test_replan.py`

- [ ] **Step 1: 写失败测试**

```python
from tools.replan import replan_itinerary

SAMPLE_REMAINING = [
    {
        "poi_name": "颐和园",
        "time_slot": "afternoon",
        "duration_hours": 2.0,
        "category": "attraction",
        "district": "海淀区",
        "indoor_outdoor": "outdoor",
        "est_cost": 30.0,
        "transport_hint": "打车约20分钟",
    },
    {
        "poi_name": "国家博物馆",
        "time_slot": "afternoon",
        "duration_hours": 2.0,
        "category": "attraction",
        "district": "东城区",
        "indoor_outdoor": "indoor",
        "est_cost": 0.0,
        "transport_hint": "地铁约40分钟",
    },
    {
        "poi_name": "南锣鼓巷",
        "time_slot": "evening",
        "duration_hours": 1.5,
        "category": "attraction",
        "district": "东城区",
        "indoor_outdoor": "outdoor",
        "est_cost": 50.0,
        "transport_hint": "步行可达",
    },
]

def test_replan_removes_completed_nodes():
    result = replan_itinerary(
        remaining_plan=SAMPLE_REMAINING,
        completed_nodes=["颐和园"],
        constraints={},
    )
    names = [n["poi_name"] for n in result["new_plan"]]
    assert "颐和园" not in names
    assert "国家博物馆" in names

def test_replan_prefer_indoor_filters_outdoor():
    result = replan_itinerary(
        remaining_plan=SAMPLE_REMAINING,
        completed_nodes=[],
        constraints={"prefer_indoor": True},
    )
    for node in result["new_plan"]:
        assert node.get("indoor_outdoor") != "outdoor"

def test_replan_avoid_pois_excluded():
    result = replan_itinerary(
        remaining_plan=SAMPLE_REMAINING,
        completed_nodes=[],
        constraints={"avoid_pois": ["南锣鼓巷"]},
    )
    names = [n["poi_name"] for n in result["new_plan"]]
    assert "南锣鼓巷" not in names

def test_replan_returns_summary():
    result = replan_itinerary(
        remaining_plan=SAMPLE_REMAINING,
        completed_nodes=[],
        constraints={},
    )
    assert "summary" in result
    assert "new_plan" in result
    assert isinstance(result["new_plan"], list)
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
python -m pytest tests/test_replan.py -v
```

- [ ] **Step 3: 实现 `tools/replan.py`**

```python
from __future__ import annotations

from typing import Any


def replan_itinerary(
    remaining_plan: list[dict[str, Any]],
    completed_nodes: list[str],
    constraints: dict[str, Any],
) -> dict[str, Any]:
    avoid = set(constraints.get("avoid_pois", []) or [])
    prefer_indoor = constraints.get("prefer_indoor", False)
    mobility_risk = constraints.get("mobility_risk", "normal")
    completed = set(completed_nodes or [])

    filtered: list[dict[str, Any]] = []
    removed_reasons: list[str] = []

    for node in remaining_plan:
        name = node.get("poi_name", "")

        if name in completed:
            removed_reasons.append(f"移除 {name}：已完成")
            continue

        if name in avoid:
            removed_reasons.append(f"移除 {name}：用户回避")
            continue

        if prefer_indoor and node.get("indoor_outdoor") == "outdoor":
            removed_reasons.append(f"移除 {name}：当前偏好室内")
            continue

        if mobility_risk == "high" and node.get("indoor_outdoor") == "outdoor":
            removed_reasons.append(f"移除 {name}：当前体力风险较高")
            continue

        filtered.append(node)

    slot_order = {"morning": 0, "afternoon": 1, "evening": 2}
    filtered.sort(key=lambda n: slot_order.get(n.get("time_slot", "evening"), 2))

    if not filtered:
        summary = "剩余行程已全部完成或移除，建议就近休息或提前返回酒店。"
    else:
        names = " -> ".join(node["poi_name"] for node in filtered)
        summary = f"调整后剩余行程：{names}"
        if removed_reasons:
            summary += "。变更原因：" + "；".join(removed_reasons)

    return {
        "new_plan": filtered,
        "removed_reasons": removed_reasons,
        "summary": summary,
    }
```

- [ ] **Step 4: 重新跑测试**

```bash
python -m pytest tests/test_replan.py -v
```

---

## Task 3: 接入共享澄清闸门 + `replan_itinerary`

**Files**
- Modify: `7-companion-agent/companion_agent.py`
- Create: `7-companion-agent/tests/test_clarification.py`

### Task 3 强约束

- 不能只在 `_run_fallback_turn()` 里做澄清。
- 澄清闸门必须在 `run_turn()` 中、进入 `_run_llm_turn()` / `_run_fallback_turn()` 之前执行。
- `_run_fallback_turn()` 的方法签名应保持现状：`(user_input, state)`。
- 当 agent 主动澄清位置时，必须记住“澄清完之后要恢复哪个原任务”，不能仅仅清掉 pending 状态。
- `remaining_plan` 必须在 companion 内部始终保持统一 schema，不能一处写 `poi_name`、另一处写 `name`。

- [ ] **Step 1: 写失败测试**

```python
from unittest.mock import MagicMock

from companion_agent import CompanionAgent, TOOL_SCHEMAS
from config import Settings
from models import CompanionState


def _make_agent_no_llm():
    s = Settings()
    return CompanionAgent(s)


SAMPLE_REMAINING = [
    {
        "poi_name": "颐和园",
        "time_slot": "afternoon",
        "duration_hours": 2.0,
        "category": "attraction",
        "district": "海淀区",
        "indoor_outdoor": "outdoor",
        "est_cost": 30.0,
        "transport_hint": "打车约20分钟",
    },
    {
        "poi_name": "南锣鼓巷",
        "time_slot": "evening",
        "duration_hours": 1.5,
        "category": "attraction",
        "district": "东城区",
        "indoor_outdoor": "outdoor",
        "est_cost": 50.0,
        "transport_hint": "步行可达",
    },
]


def test_replan_without_location_triggers_clarification():
    agent = _make_agent_no_llm()
    state = CompanionState(city="北京", remaining_plan=SAMPLE_REMAINING)
    result = agent.run_turn("下雨了不想去室外的了", state)
    assert state.clarification_pending == "current_location"
    assert "在哪" in result.reply or "位置" in result.reply


def test_replan_without_location_triggers_clarification_even_if_llm_client_exists():
    agent = _make_agent_no_llm()
    agent.client = MagicMock()
    state = CompanionState(city="北京", remaining_plan=SAMPLE_REMAINING)
    result = agent.run_turn("下雨了不想去室外的了", state)
    assert state.clarification_pending == "current_location"
    assert result.intent == "replan"


def test_clarification_answered_triggers_replan():
    agent = _make_agent_no_llm()
    state = CompanionState(
        city="北京",
        remaining_plan=SAMPLE_REMAINING,
        clarification_pending="current_location",
        clarification_resume_intent="replan",
        prefer_indoor=True,
    )
    result = agent.run_turn("我现在在颐和园门口", state)
    assert state.clarification_pending is None
    assert state.clarification_resume_intent is None
    assert result.intent == "replan"


def test_replan_tool_in_llm_schema():
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert "replan_itinerary" in names


def test_coordinate_writes_normalized_remaining_plan_nodes():
    agent = _make_agent_no_llm()
    state = CompanionState(city="北京", current_location="王府井")
    result = agent.run_turn("我现在在王府井，接下来去故宫和国家博物馆，来得及吗", state)
    assert result.intent == "coordinate"
    assert state.remaining_plan
    assert all("poi_name" in node for node in state.remaining_plan)
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
python -m pytest tests/test_clarification.py -v
```

- [ ] **Step 3: 注册 `replan_itinerary` tool schema**

在 `TOOL_SCHEMAS` 末尾添加：

```python
{
    "type": "function",
    "function": {
        "name": "replan_itinerary",
        "description": (
            "根据用户当前位置和约束，从今天剩余行程中移除已完成或不适合的节点，"
            "输出调整后的新行程安排。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "completed_nodes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "reason": {"type": "string"},
            },
            "required": [],
        },
    },
}
```

- [ ] **Step 4: 注册 `_tool_replan_itinerary`**

在 `tool_impls` 中添加：

```python
"replan_itinerary": self._tool_replan_itinerary,
```

并新增：

```python
def _tool_replan_itinerary(self, arguments: dict[str, Any], state: CompanionState) -> Any:
    from tools.replan import replan_itinerary

    completed = arguments.get("completed_nodes") or []
    for name in completed:
        if name not in state.completed_nodes:
            state.completed_nodes.append(name)

    result = replan_itinerary(
        remaining_plan=state.remaining_plan,
        completed_nodes=state.completed_nodes,
        constraints={
            "prefer_indoor": state.prefer_indoor,
            "avoid_pois": state.avoid_pois,
            "mobility_risk": state.mobility_risk,
        },
    )
    state.remaining_plan = result["new_plan"]
    return result
```

- [ ] **Step 5: 添加共享澄清辅助方法**

```python
def _needs_clarification(self, intent: str, state: CompanionState) -> str | None:
    if intent in ("replan", "coordinate", "emergency"):
        if not state.current_location and not state.current_coords:
            return "current_location"
    return None


def _build_clarification_reply(self, field: str, state: CompanionState) -> str:
    if field == "current_location":
        if state.remaining_plan:
            poi_names = "、".join(
                node.get("poi_name", node.get("name", "")) for node in state.remaining_plan[:3]
            )
            return f"你们现在在哪个地方？比如还在{poi_names}附近，或者已经往下一个点走了？告诉我位置，我来调整安排。"
        return "你们现在在哪个地方？告诉我位置，我来调整安排。"
    return "能告诉我你们现在的情况吗？"


def _maybe_handle_clarification_gate(
    self,
    user_input: str,
    state: CompanionState,
) -> AgentTurnResult | None:
    intent = self._classify_intent(user_input)
    state.intent = intent

    if state.clarification_pending == "current_location":
        resume_intent = state.clarification_resume_intent
        state.clarification_pending = None
        state.clarification_resume_intent = None
        if resume_intent:
            state.intent = resume_intent
        return None

    missing = self._needs_clarification(intent, state)
    if missing:
        state.clarification_pending = missing
        state.clarification_resume_intent = intent
        return AgentTurnResult(
            reply=self._build_clarification_reply(missing, state),
            intent=intent,
        )
    return None
```

- [ ] **Step 6: 在 `run_turn()` 中接入共享澄清闸门**

在 `state.add_turn("user", user_input)` 之后、进入 `_run_llm_turn()` / `_run_fallback_turn()` 之前加入：

```python
gated = self._maybe_handle_clarification_gate(user_input, state)
if gated is not None:
    state.add_turn("assistant", gated.reply)
    gated.state = state
    gated.token_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "llm_call_count": 0,
        "model": self.settings.openai_model,
        "source": "clarification_gate",
    }
    return gated
```

- [ ] **Step 6.5: 在后续执行阶段恢复原任务意图**

仅靠清掉 `clarification_pending` 还不够，因为像“我现在在颐和园门口”这类输入本身未必会再次被分类为 `replan`。

因此在进入具体 handler 之前，要优先使用：

```python
effective_intent = state.intent
```

并保证当上一轮是因为 `replan` / `coordinate` / `emergency` 触发的澄清时，澄清回答这一轮仍然继续原任务，而不是重新掉回默认 `search`。

- [ ] **Step 6.6: 增加统一节点转换函数**

推荐在 `companion_agent.py` 新增：

```python
def _make_remaining_plan_node(
    self,
    *,
    poi_name: str,
    time_slot: str = "afternoon",
    duration_hours: float = 1.5,
    category: str = "attraction",
    district: str = "",
    indoor_outdoor: str = "mixed",
    est_cost: float = 0.0,
    transport_hint: str = "",
    lat: float | None = None,
    lon: float | None = None,
    address: str = "",
) -> dict[str, Any]:
    ...
```

并要求：

- 前端注入 `remaining_plan` 时遵守该 schema
- `_handle_coordinate()` 写入 `state.remaining_plan` 时也遵守该 schema
- `replan_itinerary()` 只接受该统一 schema

- [ ] **Step 7: 在 `_handle_replan()` 中接入 `replan_itinerary`**

注意：这段逻辑必须插在 **`reply` 已经生成之后**、`return AgentTurnResult(...)` 之前，不能提前使用未定义变量。

```python
if state.remaining_plan:
    replan_result = self._run_tool_call(
        "replan_itinerary",
        {"completed_nodes": [], "reason": state.replan_reason or "user_preference"},
        state,
        tool_logs,
    )
    if replan_result.get("summary"):
        reply = reply + "\n\n**今日剩余行程调整：**\n" + replan_result["summary"]
```

- [ ] **Step 8: 更新 `SYSTEM_PROMPT`**

加入两条规则：

- 用户触发 `replan` / `coordinate` / `emergency` 且当前位置未知时，必须先问位置。
- 得到位置后，再继续完成原任务。

- [ ] **Step 9: 重新跑测试**

```bash
python -m pytest tests/test_clarification.py -v
```

期望：4 个测试全部通过。

- [ ] **Step 10: 修正 `_handle_coordinate()` 对 `remaining_plan` 的写法**

当前代码里时间协调流程会写入：

```python
state.remaining_plan.append({"name": destination["name"]})
```

这会破坏 `replan_itinerary` 所需的统一 schema。必须改成类似：

```python
state.remaining_plan.append(
    self._make_remaining_plan_node(
        poi_name=destination["name"],
        time_slot="afternoon",
        duration_hours=(poi_detail.get("recommended_duration_min", 60) or 60) / 60.0,
        category="attraction",
        district=destination.get("district", ""),
        indoor_outdoor="mixed",
        est_cost=float(poi_detail.get("ticket_price") or 0.0),
        transport_hint=route.get("instruction", ""),
        lat=destination.get("lat"),
        lon=destination.get("lon"),
        address=destination.get("address", ""),
    )
)
```

这样才能保证用户先问“来不来得及”，再接着问“下雨了换一下”，不会因为 `remaining_plan` 结构不一致而崩掉。

---

## Task 4: 把 companion 接入主后端

**Files**
- Modify: `backend/server.py`
- Optional Modify: `7-companion-agent/api.py`

### 接入方案

默认走 **方案 A**：
直接在 `backend/server.py` 新增 `/api/companion`。  
只有明确要重构结构时，才走 **方案 B**：先把 `7-companion-agent/api.py` 改成 `APIRouter`。

- [ ] **Step 1: 若采用方案 A，直接在 `backend/server.py` 新增路由**

```python
sys.path.insert(0, str(Path(__file__).parent.parent / "7-companion-agent"))

from companion_agent import CompanionAgent  # type: ignore
from models import CompanionState  # type: ignore

companion_agent = CompanionAgent()
```

再定义：

```python
class CompanionRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    conversation_state: dict | None = None
    debug: bool = False

class CompanionResponse(BaseModel):
    conversation_id: str
    conversation_state: dict
    reply: str
    intent: str
    cards: list[dict] = Field(default_factory=list)
    tool_logs: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: dict | None = None
    token_usage: dict = Field(default_factory=dict)
```

以及：

```python
@app.post("/api/companion", response_model=CompanionResponse)
def companion(req: CompanionRequest) -> CompanionResponse:
    state = CompanionState.from_dict(req.conversation_state)
    result = companion_agent.run_turn(req.message, state=state)
    return CompanionResponse(
        conversation_id=req.conversation_id or "local-companion",
        conversation_state=(result.state or state).to_dict(),
        reply=result.reply,
        intent=result.intent,
        cards=result.cards,
        tool_logs=result.tool_logs if req.debug else [],
        warnings=result.warnings,
        error=result.error,
        token_usage=result.token_usage,
    )
```

- [ ] **Step 2: 若采用方案 B，先把 `7-companion-agent/api.py` 改成真正导出 `router` 的模块**

```python
router = APIRouter()

@router.post("/api/companion")
def companion_chat(req: CompanionRequest) -> CompanionResponse:
    ...
```

- [ ] **Step 3: 不要混用两套方案**

- 方案 A：只在 `backend/server.py` 实现 `/api/companion`，不要再 `include_router()`。
- 方案 B：先改 `api.py`，再在 `backend/server.py` 里 `include_router()`。

- [ ] **Step 4: 启动服务验证**

```bash
cd c:\Users\19841\Desktop\github\7035project\Travel_agent_7035
uvicorn backend.server:app --reload
```

确认 `http://localhost:8000/docs` 中出现 `/api/companion`。

---

## Task 5: UI 改造

**Files**
- Modify: `6-UI/UI/chat.html`

### 强约束

- 不能再引用未声明的 `itineraryMeta` / `poiMetaByName`。
- companion state 注入时必须用 `selected_pois` 回填 `indoor_outdoor`。

- [ ] **Step 1: 在 map panel 里加 tabs + companion 面板**

```html
<div id="itinerary-tabs" style="display:none;">
  <div id="tab-header" style="display:flex; gap:8px; padding:8px 12px; background:#f8f9fa; border-bottom:1px solid #e0e0e0; overflow-x:auto;"></div>
  <div id="tab-day-plan" style="padding:12px; max-height:260px; overflow-y:auto; font-size:13px; line-height:1.6; border-bottom:1px solid #e0e0e0;"></div>
  <div id="companion-panel" style="padding:8px 12px;">
    <div id="companion-messages" style="max-height:200px; overflow-y:auto; margin-bottom:8px;"></div>
    <div style="display:flex; gap:8px;">
      <textarea id="companion-input" rows="2" style="flex:1; padding:8px; border:1px solid #ddd; border-radius:8px; resize:none; font-size:13px;" placeholder="在这里问当天的问题，比如：下雨了怎么办？附近哪里吃饭？"></textarea>
      <button id="companion-send" style="padding:8px 14px; background:#1a73e8; color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:13px;">发送</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: 使用下面这份自洽的 JS 骨架**

```javascript
let companionState = null;
let currentDayIndex = 0;
let itineraryMeta = null;
let itineraryDays = [];
let poiMetaByName = {};

function renderItineraryTabs(itineraryJson) {
  if (!itineraryJson || !itineraryJson.days || itineraryJson.days.length === 0) return;
  itineraryMeta = itineraryJson;
  itineraryDays = itineraryJson.days;
  poiMetaByName = Object.fromEntries(
    (itineraryJson.selected_pois || []).map(poi => [poi.name, poi])
  );

  const tabHeader = document.getElementById('tab-header');
  tabHeader.innerHTML = '';
  itineraryDays.forEach((day, idx) => {
    const btn = document.createElement('button');
    btn.textContent = `第${day.day_index}天`;
    btn.dataset.idx = idx;
    btn.style.cssText = 'padding:6px 14px; border-radius:16px; border:1px solid #dadce0; background:#fff; cursor:pointer; white-space:nowrap; font-size:13px;';
    btn.onclick = () => selectDay(idx);
    tabHeader.appendChild(btn);
  });

  document.getElementById('itinerary-tabs').style.display = 'block';
  selectDay(0);
}

function selectDay(idx) {
  currentDayIndex = idx;
  const day = itineraryDays[idx];

  document.querySelectorAll('#tab-header button').forEach((btn, i) => {
    btn.style.background = i === idx ? '#1a73e8' : '#fff';
    btn.style.color = i === idx ? '#fff' : '#333';
  });

  const planEl = document.getElementById('tab-day-plan');
  planEl.innerHTML = `<strong>${day.area} · ${day.theme}</strong><br>` +
    day.items.map(item =>
      `<div style="margin:6px 0; padding:6px 8px; background:#f1f3f4; border-radius:6px;">
        <span style="color:#666; font-size:12px;">${slotLabel(item.time_slot)}</span>
        <strong>${item.poi_name}</strong>
        <span style="color:#888; font-size:12px; margin-left:8px;">${item.duration_hours}h · ¥${item.est_cost}</span>
        <div style="color:#555; font-size:12px; margin-top:2px;">${item.transport_hint}</div>
      </div>`
    ).join('');

  companionState = {
    city: itineraryMeta?.city || '北京',
    remaining_plan: day.items.map(item => ({
      ...(poiMetaByName[item.poi_name] || {}),
      poi_name: item.poi_name,
      time_slot: item.time_slot,
      duration_hours: item.duration_hours,
      category: item.category,
      district: item.district,
      indoor_outdoor: (poiMetaByName[item.poi_name] || {}).indoor_outdoor || 'mixed',
      est_cost: item.est_cost,
      transport_hint: item.transport_hint,
    })),
    completed_nodes: [],
    turn_history: [],
  };

  document.getElementById('companion-messages').innerHTML = '';
}

function slotLabel(slot) {
  return { morning: '上午', afternoon: '下午', evening: '晚上' }[slot] || slot;
}

async function sendCompanionMessage() {
  const input = document.getElementById('companion-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  appendCompanionMsg('user', msg);

  try {
    const res = await fetch('/api/companion', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, conversation_state: companionState }),
    });
    const data = await res.json();
    companionState = data.conversation_state || companionState;
    appendCompanionMsg('assistant', data.reply || '（无回复）');
  } catch (e) {
    appendCompanionMsg('assistant', '网络错误，请重试');
  }
}

function appendCompanionMsg(role, text) {
  const el = document.getElementById('companion-messages');
  const div = document.createElement('div');
  div.style.cssText = `margin:6px 0; padding:8px 10px; border-radius:10px; font-size:13px; max-width:90%;
    ${role === 'user'
      ? 'background:#1a73e8; color:#fff; margin-left:auto; text-align:right;'
      : 'background:#f1f3f4; color:#333;'}`;
  div.textContent = text;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

document.getElementById('companion-send').addEventListener('click', sendCompanionMessage);
document.getElementById('companion-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendCompanionMessage();
  }
});
```

- [ ] **Step 3: 在 `/api/chat` 返回 itinerary 后调用**

```javascript
if (data.itinerary_json && data.itinerary_json.days) {
  renderItineraryTabs(data.itinerary_json);
}
```

- [ ] **Step 4: 手动验证**

1. 打开页面，输入旅行请求
2. 等主 agent 返回 itinerary
3. 确认 day tabs 正常渲染
4. 进入某天 companion，输入“下雨了不想去室外了”
5. 确认先问位置，再返回调整方案

---

## Self-Review

### Spec 覆盖

| 需求 | 对应 Task |
|---|---|
| `completed_nodes` / `clarification_pending` | Task 1 |
| deterministic replan tool | Task 2 |
| 共享澄清闸门，覆盖 LLM + fallback | Task 3 |
| `/api/companion` | Task 4 |
| day tabs + companion panel | Task 5 |

### 已修复的原 plan bug

1. 不再让实现者“前面选方案 A，后面又强制 include_router()”。
2. 不再让实现者“前面说共享 gate，后面却只改 `_run_fallback_turn()`”。
3. 不再在 `_handle_replan()` 中提前使用未定义的 `reply`。
4. 不再给出会触发 `ReferenceError` 的前端示例。
5. 不再保留 `assert ... or True` 这类假通过测试。

### Minimal Shipping Path

1. `models.py`
2. `tools/replan.py`
3. `companion_agent.py`
4. `backend/server.py`
5. `chat.html`

---

## Upgrade Plan: Autonomous Companion Agent

This section is the implementation roadmap for moving from the current itinerary-aware MVP to a more autonomous companion agent. The scope is deliberately staged so the project stays learnable and testable.

### Target Capabilities

1. Multi-step task execution
   - Example request: "We only have 4 hours this afternoon. Replan automatically and keep the most important experience."
   - Expected flow: read remaining itinerary, identify constraints, estimate route and visit time, keep core POIs, drop low-priority POIs, reorder the route, check closing-time risk, return a new afternoon itinerary.

2. Strong itinerary-aware replan
   - Read the full day plan.
   - Mark nodes as `completed`, `skipped`, or `deferred`.
   - Reorder only the remaining feasible nodes.
   - Produce a concrete "afternoon version" itinerary, not a generic nearby recommendation.

3. Self-check and second-pass search
   - Validate the first result before replying.
   - If candidates are too far, over budget, closed soon, weather-incompatible, or too demanding for the party, retry with a different strategy.
   - Return the final plan with explicit reasons for removed or changed items.

### Phase 1: Controlled MVP Replanner

Goal: build a deterministic replan core without depending on the LLM or the UI.

Files to modify:
- `7-companion-agent/models.py`
- `7-companion-agent/tools/replan.py`
- `7-companion-agent/tools/replan_validator.py`
- `7-companion-agent/tests/test_replan.py`
- `7-companion-agent/tests/test_replan_validator.py`

Implementation tasks:
- [ ] Extend `CompanionState` with `completed_nodes`, `skipped_nodes`, `deferred_nodes`, `time_budget_hours`, and `current_location`.
- [ ] Implement `replan_itinerary(day_plan, current_location, time_budget_hours, completed_nodes, skipped_nodes, constraints)`.
- [ ] Keep the algorithm deterministic first: filter completed/skipped, estimate total duration, preserve high-priority nodes, remove low-priority nodes until the plan fits the time budget.
- [ ] Implement `validate_replan(result, constraints)` with checks for total time, closing risk, weather mismatch, distance, and mobility risk.
- [ ] Return a structured result:

```python
{
    "status": "ok" | "needs_clarification" | "no_feasible_plan",
    "new_plan": [...],
    "removed_nodes": [...],
    "deferred_nodes": [...],
    "warnings": [...],
    "summary": "...",
}
```

Acceptance tests:
- [ ] "4 hours left" produces a plan whose total estimated time is <= 4 hours.
- [ ] Completed POIs never appear in the new plan.
- [ ] Skipped POIs never appear in the new plan.
- [ ] High-priority or `must_visit` POIs are kept before low-priority POIs.
- [ ] Validator rejects plans that exceed the time budget.

### Phase 2: Agent Task State and Resume Flow

Goal: make companion handle a multi-turn task instead of treating every user message as a new standalone request.

Files to modify:
- `7-companion-agent/models.py`
- `7-companion-agent/companion_agent.py`
- `7-companion-agent/tests/test_companion_task_flow.py`

Implementation tasks:
- [ ] Add task-state fields:

```python
current_task: dict | None
task_stack: list[dict]
subtasks: list[dict]
task_status: str | None
clarification_pending: str | None
clarification_resume_intent: str | None
self_check_results: list[dict]
```

- [ ] Add a shared clarification gate in `run_turn()` before both LLM and fallback paths.
- [ ] When user asks for replan but location/time/progress is missing, save the pending task and ask a targeted clarification.
- [ ] When the user answers only "I am at X" or "we finished Y", resume the original task instead of falling back to search.
- [ ] Add `_create_replan_task()`, `_resume_pending_task()`, and `_execute_task()` helper methods.

Acceptance tests:
- [ ] User says "4 hours left, replan"; agent asks for missing current location if absent.
- [ ] User then says "I am at the Summer Palace gate"; agent resumes the replan task.
- [ ] User says "we finished the Summer Palace"; state records it in `completed_nodes`.
- [ ] The final response includes a new structured itinerary.

### Phase 3: Real Itinerary Injection

Goal: connect the replanner to the real itinerary produced by the main travel planner.

Files to modify:
- `3-travel_planner/travel_planner/models.py`
- `3-travel_planner/travel_planner/ui_backend.py`
- `backend/server.py`
- `6-UI/UI/chat.html`

Implementation tasks:
- [ ] Ensure each day-plan item exposes enough metadata:

```python
poi_name
time_slot
duration_hours
priority
must_visit
indoor_outdoor
lat
lon
opening_hours
category
district
transport_hint
```

- [ ] If `DayPlanItem` does not own a field, fill it from `selected_pois` before sending to the frontend.
- [ ] Add `/api/companion` to the main backend or mount the companion router, but choose one route only.
- [ ] In the UI, inject the selected day's plan into `CompanionState.remaining_plan`.
- [ ] Render the replanned itinerary separately from the original itinerary so the user can compare what changed.

Acceptance tests:
- [ ] A real itinerary from `/api/chat` can be passed into `/api/companion`.
- [ ] Companion receives the selected day only, not the whole trip by accident.
- [ ] Replanned result shows removed, deferred, and kept POIs.

### Phase 4: Self-Check and Second-Pass Search

Goal: make the agent detect weak results and try again before replying.

Files to modify:
- `7-companion-agent/tools/replan_validator.py`
- `7-companion-agent/tools/replan.py`
- `7-companion-agent/tools/ranking.py`
- `7-companion-agent/companion_agent.py`

Implementation tasks:
- [ ] Add validator reasons such as `too_far`, `over_time_budget`, `closing_soon`, `weather_mismatch`, `mobility_risk`, and `no_core_experience`.
- [ ] Add a retry policy:

```python
if too_far:
    search_radius_km = min(search_radius_km, 3)
if over_time_budget:
    reduce optional nodes
if closing_soon:
    remove or move earlier
if weather_mismatch:
    prefer indoor candidates
if no_core_experience:
    restore highest-priority POI and drop lower-value nodes
```

- [ ] Limit retries to 2 passes to avoid unpredictable loops.
- [ ] Store self-check output in `state.self_check_results`.
- [ ] Include a short explanation in the reply: what failed first, what was changed, and why the final plan is feasible.

Acceptance tests:
- [ ] If the first plan is too far, the second pass produces a closer plan.
- [ ] If the first plan exceeds the time budget, the second pass removes optional nodes.
- [ ] If all plans fail, the agent returns `no_feasible_plan` with a clear fallback suggestion.

### Phase 5: LLM Planner Integration

Goal: use the LLM for task interpretation and explanation, while keeping itinerary mutation deterministic.

Files to modify:
- `7-companion-agent/companion_agent.py`
- `7-companion-agent/tools/replan.py`
- `7-companion-agent/tests/test_llm_gate.py`

Implementation tasks:
- [ ] Add `replan_itinerary` to `TOOL_SCHEMAS`.
- [ ] Let the LLM choose when to call `replan_itinerary`, but do not let the LLM directly mutate `remaining_plan`.
- [ ] Keep `replan_itinerary` as the source of truth for the new itinerary.
- [ ] If no LLM credentials exist, fallback should still complete the same replan task.
- [ ] Add tests that verify the shared clarification gate runs before LLM tool-calling.

Acceptance tests:
- [ ] With LLM configured, missing location still triggers clarification before any tool call.
- [ ] Without LLM configured, the same replan flow works through fallback.
- [ ] LLM output cannot invent a final itinerary that differs from `replan_itinerary` result.

### Minimal Learning Path

Do not try to understand the full project first. Learn and implement in this order:

1. `CompanionState` and state round-trip.
2. `replan_itinerary()` as a pure Python function.
3. `CompanionAgent.run_turn()` task flow.
4. `/api/companion` request and response shape.
5. `chat.html` day-plan injection.
6. Main planner metadata only after the companion loop works.

### Minimum Modules to Change First

For the first working version, touch only:

1. `7-companion-agent/models.py`
2. `7-companion-agent/tools/replan.py`
3. `7-companion-agent/tools/replan_validator.py`
4. `7-companion-agent/companion_agent.py`
5. `7-companion-agent/tests/test_replan.py`
6. `7-companion-agent/tests/test_companion_task_flow.py`

Only after these pass should the work move to:

1. `backend/server.py`
2. `6-UI/UI/chat.html`
3. `3-travel_planner/travel_planner/models.py`
4. `3-travel_planner/travel_planner/ui_backend.py`

### Hard Boundaries

- Do not build a fully autonomous open-ended agent in the first version.
- Do not let the LLM directly rewrite itinerary state.
- Do not mix cross-day replanning into the same milestone.
- Do not add second-pass search before the deterministic replan tests are stable.
- Do not make the frontend responsible for deciding itinerary logic; it only passes state and renders results.

### Done Definition

- 有 LLM 和无 LLM 两种模式下，都能先澄清位置。
- `/api/companion` 能从主后端直接访问。
- UI 能按天切换 companion 会话。
- `remaining_plan` 确实来自当天 day plan。
- 用户说“下雨了 / 不想去室外 / 走不动了”时，返回的是基于剩余行程的重排结果，而不是泛泛推荐。
