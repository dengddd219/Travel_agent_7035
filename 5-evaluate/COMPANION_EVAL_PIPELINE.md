# Companion Eval Pipeline

This pipeline implements the VitaBench-style evaluation loop for `7-companion-agent`:

1. Load task files from `companion_tasks/index.json`.
2. Initialize `CompanionState` from each task's `initial_state`.
3. Use a user simulator to drive multi-turn interaction.
4. Save full trajectories: user messages, assistant replies, tool calls, and state snapshots.
5. Evaluate trajectories with rubric-based sliding windows.
6. Produce all-or-nothing and fine-grained scores.
7. Aggregate repeated-trial metrics: `Avg@k`, `Pass@k`, and `Pass^k`.

## Quick Smoke Test

Run one deterministic task without using the agent LLM:

```bash
python 5-evaluate/companion_eval_pipeline.py ^
  --city Beijing ^
  --max-tasks 1 ^
  --num-trials 1 ^
  --max-turns 3 ^
  --no-agent-llm ^
  --simulator rule ^
  --evaluator rule
```

Run one task with LLM user simulator and hybrid evaluator:

```bash
python 5-evaluate/companion_eval_pipeline.py ^
  --city Beijing ^
  --max-tasks 1 ^
  --num-trials 1 ^
  --max-turns 3 ^
  --no-agent-llm ^
  --simulator llm ^
  --evaluator hybrid
```

Run the full current benchmark seed set:

```bash
python 5-evaluate/companion_eval_pipeline.py ^
  --num-trials 4 ^
  --max-turns 6 ^
  --simulator llm ^
  --evaluator hybrid
```

The current v0.2 task set has 30 tasks, so `--num-trials 4` produces 120 trajectories.

## Modes

- `--simulator llm`: use LLM user simulator. Falls back to rule response if a call fails.
- `--simulator rule`: deterministic simulator for CI and debugging.
- `--simulator auto`: use LLM if credentials exist; otherwise rule mode.
- `--evaluator llm`: sliding-window LLM judge.
- `--evaluator hybrid`: deterministic checks plus sliding-window LLM judge.
- `--evaluator rule`: deterministic evaluator only.
- `--evaluator auto`: use LLM if credentials exist; otherwise rule mode.
- `--no-agent-llm`: force the companion agent to use deterministic fallback while still allowing LLM simulator/evaluator.

## Outputs

Each run writes a timestamped directory under `5-evaluate/companion_eval_runs/` unless `--out-dir` is provided.

- `trajectories.jsonl`: full interaction trajectories.
- `trial_results.jsonl`: per-task-per-trial scores.
- `summary.json`: aggregate metrics.

Each trial result includes:

- `strict_success`: all required rubrics and trajectory checks pass.
- `rubric_score`: passed rubrics / total rubrics.
- `dimension_scores`: `reasoning`, `tool`, and `interaction` averages.
- `tool_success`: required tool-call coverage.
- `interaction_score`: interaction rubric score.
- `final_response_score`: currently mapped to interaction rubric score.
- `failed_rubrics`: failed atomic rubric details.
- `trajectory_checks`: required intent, required tools, and forbidden tools.

## Metrics

For repeated trials per task:

- `Avg@k`: average success rate across k trials.
- `Pass@k`: whether at least one of k trials succeeded.
- `Pass^k`: reported as `pass_all_k`, whether all k trials succeeded.

The summary reports these overall, by city, and by task.
