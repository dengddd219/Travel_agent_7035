# Companion Task Set Schema

`companion_tasks/` is the project-specific task set for evaluating the in-trip companion agent. It borrows the VitaBench idea of `environment + user simulator + trajectory + rubrics`, but keeps the schema aligned with this repository's `CompanionState` and companion tools.

The older `companion_tasks_10_cities.json` file is a single-file v0.1 seed set with 10 tasks. The recommended v0.2 layout is one file per city:

- `companion_tasks/index.json`
- `companion_tasks/beijing.json`
- `companion_tasks/shanghai.json`
- `companion_tasks/chengdu.json`
- `companion_tasks/chongqing.json`
- `companion_tasks/guangzhou.json`
- `companion_tasks/shenzhen.json`
- `companion_tasks/hangzhou.json`
- `companion_tasks/xian.json`
- `companion_tasks/xiamen.json`
- `companion_tasks/nanjing.json`

Current v0.2 coverage: 10 cities x 3 tasks = 30 tasks.

## Top-Level Fields

- `version`: task-set version.
- `benchmark`: stable benchmark name.
- `agent`: target agent name, currently `companion`.
- `evaluator`: recommended evaluation settings.
  - `window_turns`: number of dialogue/tool turns per evaluator window.
  - `overlap_turns`: overlapping turns between adjacent windows.
  - `success_policy`: current default is all required rubrics must pass.
  - `recommended_trials`: number of repeated runs per task.
  - `metrics`: metrics to report.
- `cities`: in `index.json`, a list of city files and task ids.
- `tasks`: in each city file, evaluation cases for that city.

## Task Fields

- `id`: unique task id.
- `city` / `city_zh`: city context.
- `task_type`: scenario category.
- `complexity`: VitaBench-style complexity tags.
  - `reasoning`: constraint reasoning points.
  - `tool`: expected tool-use difficulty.
  - `interaction`: user interaction difficulty.
- `initial_state`: initial `CompanionState` subset. The evaluator or runner should pass this into `CompanionState.from_dict()`.
- `user_scenario`: complete hidden task definition for the simulated user.
  - `profile`: persona and speaking style.
  - `complete_instruction`: full task known to the simulator.
  - `hidden_constraints`: constraints the agent should infer or elicit.
  - `disclosure_plan`: how the simulator should reveal information over turns.
- `first_user_message`: first message sent to the agent.
- `expected_trajectory`: deterministic trajectory checks.
  - `required_intent`: expected companion intent.
  - `tools_must_call`: tools required for success.
  - `tools_should_call`: useful but not always mandatory tools.
  - `tools_should_not_call`: calls that indicate unsafe ordering.
  - `state_assertions`: state-level expectations for a rule or LLM judge.
- `evaluation_criteria.required_rubrics`: atomic checklist items.
  - `key`: stable rubric id.
  - `dimension`: `reasoning`, `tool`, or `interaction`.
  - `rubric`: natural-language criterion for sliding-window evaluation.
- `failure_tags`: labels for failure analysis.

## Intended Evaluation Flow

1. Load one task and build `CompanionState` from `initial_state`.
2. Send `first_user_message` to the companion agent.
3. If the agent asks clarification, answer according to `user_scenario.disclosure_plan`.
4. Record every user message, agent reply, tool call, tool result, and state snapshot.
5. Run sliding-window evaluation over the trajectory using `required_rubrics`.
6. Mark the task successful only when every required rubric is satisfied.
7. Repeat each task 4 times and report `Avg@4`, `Pass@4`, `Pass^4`, and rubric completion rate.

## Coverage

The current set covers 10 cities:

- Beijing
- Shanghai
- Chengdu
- Chongqing
- Guangzhou
- Shenzhen
- Hangzhou
- Xian
- Xiamen
- Nanjing

The cases intentionally cover replan, coordinate, search, emergency, weather disruption, mobility constraints, current-location clarification, completed/skipped node memory, and deadline reasoning.

## Build Script

`build_companion_task_files.py` rebuilds the per-city v0.2 files from the v0.1 seed file plus additional generated task definitions:

```bash
python 5-evaluate/build_companion_task_files.py
```

Use this after editing the generator or the seed file. The script rewrites `companion_tasks/*.json`.
