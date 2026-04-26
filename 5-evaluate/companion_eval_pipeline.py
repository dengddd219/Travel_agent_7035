# -*- coding: utf-8 -*-
"""VitaBench-style evaluation pipeline for the CompanionAgent.

This script provides:
- LLM user simulator with deterministic fallback
- trajectory runner
- rubric-based sliding-window evaluator
- all-or-nothing and fine-grained scores
- repeated-trial metrics: Avg@k, Pass@k, Pass^k

Examples:
    python 5-evaluate/companion_eval_pipeline.py --city Chongqing --num-trials 1 --max-tasks 1 --no-agent-llm --simulator rule --evaluator rule
    python 5-evaluate/companion_eval_pipeline.py --num-trials 4 --simulator llm --evaluator hybrid
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "5-evaluate"
COMPANION_DIR = ROOT / "7-companion-agent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(COMPANION_DIR) not in sys.path:
    sys.path.insert(0, str(COMPANION_DIR))

from companion_agent import CompanionAgent  # noqa: E402
from config import Settings  # noqa: E402
from models import AgentTurnResult, CompanionState  # noqa: E402
from token_costing import aggregate_token_usage, token_usage_from_response, with_token_cost, zero_token_usage  # noqa: E402

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore


DEFAULT_TASK_INDEX = EVAL_DIR / "companion_tasks" / "index.json"


@dataclass(slots=True)
class EvalConfig:
    task_path: Path = DEFAULT_TASK_INDEX
    cities: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    max_tasks: int | None = None
    num_trials: int = 1
    max_turns: int = 6
    simulator_mode: str = "auto"
    evaluator_mode: str = "auto"
    no_agent_llm: bool = False
    out_dir: Path | None = None
    window_turns: int = 10
    overlap_turns: int = 2


@dataclass(slots=True)
class RubricStatus:
    key: str
    rubric: str
    dimension: str
    meet: bool = False
    justification: str = ""
    source: str = "unset"


def now_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def compact_json(payload: Any, limit: int = 4000) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...<truncated>"


def extract_json(raw_text: str) -> Any:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("empty LLM output")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    starts = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
    if not starts:
        raise ValueError("no JSON object or array found")
    start = min(starts)
    for end in range(len(text), start, -1):
        snippet = text[start:end].strip()
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue
    raise ValueError("could not parse JSON from LLM output")


class TaskLoader:
    def __init__(self, task_path: Path) -> None:
        self.task_path = task_path

    def load(self) -> list[dict[str, Any]]:
        payload = load_json(self.task_path)
        if "cities" in payload and "tasks" not in payload:
            base = self.task_path.parent
            tasks: list[dict[str, Any]] = []
            for item in payload["cities"]:
                city_file = base / item["path"]
                tasks.extend(load_json(city_file)["tasks"])
            return tasks
        if "tasks" in payload:
            return list(payload["tasks"])
        raise ValueError(f"Unsupported task file shape: {self.task_path}")

    @staticmethod
    def filter_tasks(
        tasks: list[dict[str, Any]],
        cities: list[str] | None = None,
        task_ids: list[str] | None = None,
        max_tasks: int | None = None,
    ) -> list[dict[str, Any]]:
        selected = tasks
        if cities:
            city_set = {city.lower() for city in cities}
            selected = [task for task in selected if str(task.get("city", "")).lower() in city_set]
        if task_ids:
            id_set = set(task_ids)
            selected = [task for task in selected if task.get("id") in id_set]
        if max_tasks is not None:
            selected = selected[: max(0, max_tasks)]
        return selected


class ChatLLM:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None
        self._token_usages: list[dict[str, Any]] = []
        if OpenAI is not None and settings.has_llm_credentials:
            kwargs: dict[str, Any] = {
                "api_key": settings.openai_api_key,
                "timeout": settings.request_timeout_s,
            }
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            self.client = OpenAI(**kwargs)

    @property
    def available(self) -> bool:
        return self.client is not None

    def chat_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> Any:
        if self.client is None:
            raise RuntimeError("LLM client is not available")
        response = self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,
            temperature=temperature,
        )
        self._token_usages.append(token_usage_from_response(response, model=self.settings.openai_model))
        content = response.choices[0].message.content or ""
        return extract_json(content)

    def token_usage_summary(self) -> dict[str, Any]:
        if not self._token_usages:
            return zero_token_usage(model=self.settings.openai_model, source="no_eval_llm_call")
        return aggregate_token_usage(
            self._token_usages,
            model=self.settings.openai_model,
            source="companion_eval_simulator_and_judge",
        )


class LLMUserSimulator:
    """Simulates a user. Uses LLM when available; otherwise deterministic fallback."""

    def __init__(self, task: dict[str, Any], llm: ChatLLM, mode: str = "auto") -> None:
        self.task = task
        self.llm = llm
        self.mode = mode
        self.used_disclosures: set[int] = set()
        self.last_source = "task_seed"

    def first_message(self) -> str:
        return str(self.task["first_user_message"])

    def should_use_llm(self) -> bool:
        return self.mode == "llm" or (self.mode == "auto" and self.llm.available)

    def next_message(
        self,
        trajectory_events: list[dict[str, Any]],
        last_result: AgentTurnResult,
        state: CompanionState,
        turn_index: int,
    ) -> str | None:
        if turn_index >= 1 and self._task_looks_complete(last_result, state):
            return None
        if self.should_use_llm():
            try:
                message = self._next_message_llm(trajectory_events, last_result, state)
                self.last_source = "llm" if message else "llm_stop"
                return message
            except Exception:
                message = self._next_message_rule(last_result, state)
                self.last_source = "rule_fallback"
                return message
        message = self._next_message_rule(last_result, state)
        self.last_source = "rule"
        return message

    def _task_looks_complete(self, last_result: AgentTurnResult, state: CompanionState) -> bool:
        if state.clarification_pending:
            return False
        if last_result.intent == "error":
            return True
        if "###STOP###" in (last_result.reply or ""):
            return True
        expected = self.task.get("expected_trajectory", {})
        required_tools = set(expected.get("tools_must_call") or [])
        called = {log.get("tool") for log in last_result.tool_logs}
        if state.task_status == "completed" and required_tools.issubset(called | self._all_called_tools_from_state_events([])):
            return True
        # Most current companion tasks are one-shot unless clarification is requested.
        if last_result.tool_logs and not state.clarification_pending:
            return True
        return False

    @staticmethod
    def _all_called_tools_from_state_events(events: list[dict[str, Any]]) -> set[str]:
        return {event.get("tool") for event in events if event.get("type") == "tool_call"}

    def _next_message_llm(
        self,
        trajectory_events: list[dict[str, Any]],
        last_result: AgentTurnResult,
        state: CompanionState,
    ) -> str | None:
        scenario = self.task.get("user_scenario", {})
        profile = scenario.get("profile", {})
        system = (
            "You are a user simulator for evaluating a travel companion agent.\n\n"
            "# Role Setting\n"
            "You are playing the role of a user interacting with the agent. "
            "Your character is described in <persona>; your task is to convey <instructions> through dialogue.\n\n"
            "<persona>\n"
            f"{profile.get('persona', '')} "
            f"Age: {profile.get('age', 'unspecified')}. "
            f"Patience level: {profile.get('patience', 'medium')}. "
            f"Dietary restriction: {profile.get('dietary_restriction', 'none')}. "
            f"Speaking style: {profile.get('style', '')}\n"
            "</persona>\n\n"
            "# Conversation Style Rules\n"
            "- Generate only one line each time to simulate a user message.\n"
            "- Use context description + need expression: first describe the background situation, then express the specific need.\n"
            "- When you need the agent to make a decision, provide your conditions and preferences, and ask the agent to recommend.\n"
            "- Reflect the personality traits in <persona> through language style, emotional expression, and word choice.\n\n"
            "# Information Disclosure Rules\n"
            "- Break down information from the instructions into multiple independent points; mention them separately in different rounds.\n"
            "- Directly convey the original content from instructions, but adjust expression to match the persona.\n"
            "- Avoid revealing all needs in the first round; let information unfold gradually according to disclosure_plan.\n\n"
            "# Information Processing Rules\n"
            "- Answer the agent's questions based only on the persona and instructions. If there is no corresponding answer, say you don't remember or don't know.\n"
            "- Do not fabricate information not provided in the instructions.\n"
            "- If the agent repeats the same question you have already answered 3 or more times, show impatience and refuse to answer again.\n\n"
            "# When NOT to End the Conversation\n"
            "- Before you have clearly and completely expressed all needs and constraints.\n"
            "- Before the agent has completed all tasks mentioned in the instructions.\n"
            "- If the agent's result does not match your expectations or is incorrect/incomplete.\n\n"
            "# When You CAN End the Conversation\n"
            "- Only when all the above conditions are met and the task is correctly completed.\n"
            "- Or when you have clearly expressed your needs but the agent explicitly states it cannot complete the task.\n\n"
            "Return only JSON."
        )
        user = {
            "task_id": self.task.get("id"),
            "city": self.task.get("city"),
            "profile": profile,
            "complete_instruction": scenario.get("complete_instruction", ""),
            "hidden_constraints": scenario.get("hidden_constraints", []),
            "disclosure_plan": scenario.get("disclosure_plan", []),
            "conversation_events": trajectory_events[-16:],
            "last_agent_reply": last_result.reply,
            "last_intent": last_result.intent,
            "state": {
                "clarification_pending": state.clarification_pending,
                "task_status": state.task_status,
                "current_location": state.current_location,
            },
            "output_schema": {
                "stop": "boolean, true only when the task is complete or impossible",
                "message": "next one-line user message, empty if stop is true",
                "reason": "short reason",
            },
        }
        parsed = self.llm.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": compact_json(user)},
            ],
            temperature=0.2,
        )
        if isinstance(parsed, dict) and parsed.get("stop"):
            return None
        if isinstance(parsed, dict):
            message = str(parsed.get("message", "")).strip()
            return message or None
        return None

    def _next_message_rule(self, last_result: AgentTurnResult, state: CompanionState) -> str | None:
        scenario = self.task.get("user_scenario", {})
        complete = str(scenario.get("complete_instruction", ""))
        disclosures = list(scenario.get("disclosure_plan") or [])
        reply = last_result.reply or ""

        if state.clarification_pending == "current_location":
            location = self._extract_location_answer(complete)
            return f"I am at {location}."

        if self._looks_like_question(reply):
            for idx, item in enumerate(disclosures):
                if idx not in self.used_disclosures:
                    self.used_disclosures.add(idx)
                    return self._disclosure_to_message(str(item), complete)
            return "I don't know anything beyond what I already said."
        return None

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        lowered = text.lower()
        return "?" in text or "where" in lowered or "confirm" in lowered or "需要" in text or "告诉" in text

    @staticmethod
    def _extract_location_answer(complete_instruction: str) -> str:
        patterns = [
            r"currently at ([^.。]+)",
            r"I am at ([^.。]+)",
            r"We are at ([^.。]+)",
            r"at the ([^.。]+)",
            r"near ([^.。]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, complete_instruction, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return "the current planned stop"

    @staticmethod
    def _disclosure_to_message(disclosure: str, complete_instruction: str) -> str:
        lower = disclosure.lower()
        if "don't know" in lower or "unknown" in lower:
            return "I don't know."
        if "if asked" in lower and "," in disclosure:
            return disclosure.split(",", 1)[1].strip().rstrip(".") + "."
        if "say " in lower:
            return re.split(r"\bsay\b", disclosure, flags=re.IGNORECASE, maxsplit=1)[1].strip().rstrip(".") + "."
        # Fall back to a concise restatement from the complete instruction.
        return complete_instruction.split(".")[0].strip() + "."


class TrajectoryRunner:
    def __init__(self, settings: Settings, config: EvalConfig, llm: ChatLLM) -> None:
        self.settings = settings
        self.config = config
        self.llm = llm

    def _agent_settings(self, task: dict[str, Any]) -> Settings:
        settings = Settings(
            openai_api_key="" if self.config.no_agent_llm else self.settings.openai_api_key,
            openai_base_url=self.settings.openai_base_url,
            openai_model=self.settings.openai_model,
            openai_api_version=self.settings.openai_api_version,
            amap_api_key=self.settings.amap_api_key,
            default_city=str(task.get("city") or self.settings.default_city),
            request_timeout_s=self.settings.request_timeout_s,
        )
        return settings

    def run_task_trial(self, task: dict[str, Any], trial_index: int) -> dict[str, Any]:
        state = CompanionState.from_dict(task.get("initial_state") or {})
        agent = CompanionAgent(settings=self._agent_settings(task))
        simulator = LLMUserSimulator(task, llm=self.llm, mode=self.config.simulator_mode)
        events: list[dict[str, Any]] = []
        token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_call_count": 0}
        turn_token_usages: list[dict[str, Any]] = []
        latencies: list[int] = []

        user_message: str | None = simulator.first_message()
        user_source = "task_seed"
        done_reason = "max_turns"
        for turn in range(1, self.config.max_turns + 1):
            if not user_message:
                done_reason = "simulator_stop"
                break
            events.append({"type": "user_message", "turn": turn, "content": user_message, "source": user_source})
            started = time.monotonic()
            result = agent.run_turn(user_message, state=state)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            latencies.append(elapsed_ms)
            usage = with_token_cost(result.token_usage or {}, model=agent.settings.openai_model)
            turn_token_usages.append(usage)
            for key in token_usage:
                token_usage[key] += int(usage.get(key, 0) or 0)

            for log in result.tool_logs:
                events.append(
                    {
                        "type": "tool_call",
                        "turn": turn,
                        "tool": log.get("tool"),
                        "arguments": log.get("arguments", {}),
                        "preview": log.get("preview", ""),
                    }
                )
            events.append(
                {
                    "type": "assistant_message",
                    "turn": turn,
                    "intent": result.intent,
                    "content": result.reply,
                    "warnings": result.warnings,
                    "latency_ms": elapsed_ms,
                    "token_usage": usage,
                }
            )
            events.append({"type": "state_snapshot", "turn": turn, "state": state.to_dict()})

            user_message = simulator.next_message(events, result, state, turn)
            user_source = simulator.last_source
            if user_message is None:
                done_reason = "task_complete_or_user_stop"
                break

        token_usage = aggregate_token_usage(
            turn_token_usages,
            model=agent.settings.openai_model,
            source="companion_eval_agent_trials",
        )
        return {
            "task_id": task.get("id"),
            "city": task.get("city"),
            "trial_index": trial_index,
            "done_reason": done_reason,
            "events": events,
            "final_state": state.to_dict(),
            "token_usage": token_usage,
            "latency_ms": {
                "turns": latencies,
                "total": sum(latencies),
                "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            },
            "agent_llm_enabled": not self.config.no_agent_llm,
            "simulator_mode": self.config.simulator_mode,
        }


class RuleEvaluator:
    def evaluate(self, task: dict[str, Any], trajectory: dict[str, Any]) -> dict[str, RubricStatus]:
        statuses = {
            item["key"]: RubricStatus(
                key=item["key"],
                rubric=item["rubric"],
                dimension=item["dimension"],
                meet=False,
                source="rule",
            )
            for item in task["evaluation_criteria"]["required_rubrics"]
        }
        events = trajectory["events"]
        tools = [event.get("tool") for event in events if event.get("type") == "tool_call"]
        intents = [event.get("intent") for event in events if event.get("type") == "assistant_message"]
        final_state = trajectory.get("final_state") or {}
        final_reply = self._final_reply(events)
        expected = task.get("expected_trajectory", {})

        for status in statuses.values():
            text = f"{status.key} {status.rubric}".lower()
            status.meet = self._rule_match(text, tools, intents, final_state, final_reply, expected)
            status.justification = "Matched by deterministic trajectory/state heuristic." if status.meet else "No deterministic evidence found."
        return statuses

    @staticmethod
    def _final_reply(events: list[dict[str, Any]]) -> str:
        for event in reversed(events):
            if event.get("type") == "assistant_message":
                return str(event.get("content", ""))
        return ""

    def _rule_match(
        self,
        text: str,
        tools: list[str | None],
        intents: list[str | None],
        final_state: dict[str, Any],
        final_reply: str,
        expected: dict[str, Any],
    ) -> bool:
        tool_set = set(tools)
        expected_intent = expected.get("required_intent")
        if "get_weather" in text or "weather" in text:
            return "get_weather_now" in tool_set
        if "get_route" in text or "route" in text:
            return "get_route" in tool_set
        if "replan_itinerary" in text or "call_replan" in text or "replan" in text and "tool" in text:
            return "replan_itinerary" in tool_set
        if "resolve_emergency_resources" in text or "emergency_resources" in text or "call_resources" in text:
            return "resolve_emergency_resources" in tool_set
        if "resolve_location" in text or "location" in text and "tool" in text:
            return "resolve_location" in tool_set
        if "retrieve" in text:
            return "retrieve_candidates" in tool_set
        if "score" in text or "rank" in text:
            return "score_candidates" in tool_set
        if "poi" in text and ("detail" in text or "duration" in text or "opening" in text):
            return "get_poi_detail" in tool_set
        if "classif" in text or "intent" in text:
            return expected_intent in intents if expected_intent else bool(intents)
        if "deadline" in text:
            return expected_intent == "coordinate" and ("get_route" in tool_set or bool(final_state.get("destination_deadlines")))
        if "time budget" in text or "4-hour" in text or "three_hours" in text or "3-hour" in text:
            return final_state.get("time_budget_hours") is not None
        if "clarification" in text or "ask_location" in text:
            return any(
                (event.get("state") or {}).get("clarification_pending") == "current_location"
                for event in self._state_events_from_final(final_state)
            ) or "replan_itinerary" in tool_set
        if "emergency" in text or "safety" in text or "medical" in text or "toilet" in text or "lost child" in text:
            return expected_intent == "emergency" and "resolve_emergency_resources" in tool_set
        if "does not" in text or "avoid" in text or "skip" in text or "not include" in text:
            return self._negative_condition_heuristic(text, final_state, final_reply)
        if "preserve" in text or "keeps" in text or "core" in text:
            return self._preserve_condition_heuristic(final_state, final_reply)
        # Conservative default: final reply exists and required tools have been called.
        required = set(expected.get("tools_must_call") or [])
        return bool(final_reply.strip()) and required.issubset(tool_set)

    @staticmethod
    def _state_events_from_final(final_state: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"state": final_state}]

    @staticmethod
    def _negative_condition_heuristic(text: str, final_state: dict[str, Any], final_reply: str) -> bool:
        plan_names = " ".join(str(item.get("poi_name") or item.get("name") or "") for item in final_state.get("remaining_plan", []))
        haystack = f"{plan_names} {final_reply}".lower()
        if "sunlight rock" in text:
            return "sunlight rock" not in haystack
        if "city wall" in text and "repeat" in text:
            return "city wall" not in plan_names.lower()
        return True

    @staticmethod
    def _preserve_condition_heuristic(final_state: dict[str, Any], final_reply: str) -> bool:
        plan = final_state.get("remaining_plan") or []
        return bool(plan or final_reply.strip())


class SlidingWindowEvaluator:
    def __init__(self, llm: ChatLLM, mode: str = "auto", window_turns: int = 10, overlap_turns: int = 2) -> None:
        self.llm = llm
        self.mode = mode
        self.window_turns = window_turns
        self.overlap_turns = overlap_turns
        self.rule = RuleEvaluator()

    def should_use_llm(self) -> bool:
        return self.mode in {"llm", "hybrid"} or (self.mode == "auto" and self.llm.available)

    def evaluate(self, task: dict[str, Any], trajectory: dict[str, Any]) -> dict[str, Any]:
        rule_statuses = self.rule.evaluate(task, trajectory)
        statuses = {
            key: RubricStatus(
                key=value.key,
                rubric=value.rubric,
                dimension=value.dimension,
                meet=value.meet,
                justification=value.justification,
                source=value.source,
            )
            for key, value in rule_statuses.items()
        }
        if self.should_use_llm() and self.llm.available:
            try:
                llm_statuses = self._evaluate_with_llm(task, trajectory, statuses)
                statuses = self._merge_statuses(statuses, llm_statuses)
            except Exception as exc:
                for item in statuses.values():
                    if not item.justification:
                        item.justification = f"LLM evaluator failed; rule fallback used: {exc}"

        trajectory_checks = self._trajectory_checks(task, trajectory)
        return self._score(task, statuses, trajectory_checks)

    @staticmethod
    def _merge_statuses(
        base: dict[str, RubricStatus],
        updates: dict[str, RubricStatus],
    ) -> dict[str, RubricStatus]:
        for key, update in updates.items():
            if key not in base:
                continue
            # Once true, keep true unless the LLM explicitly says false with an overturn source.
            if update.meet or not base[key].meet:
                base[key] = update
        return base

    def _evaluate_with_llm(
        self,
        task: dict[str, Any],
        trajectory: dict[str, Any],
        initial_statuses: dict[str, RubricStatus],
    ) -> dict[str, RubricStatus]:
        statuses = {
            key: RubricStatus(
                key=value.key,
                rubric=value.rubric,
                dimension=value.dimension,
                meet=value.meet,
                justification=value.justification,
                source=value.source,
            )
            for key, value in initial_statuses.items()
        }
        windows = self._windows(trajectory["events"])
        total = len(windows)
        for idx, window in enumerate(windows, start=1):
            parsed = self._judge_window(task, window, statuses, idx, total)
            for item in parsed:
                key = str(item.get("rubric_key") or item.get("key") or "")
                if key not in statuses:
                    continue
                meet = bool(item.get("meetExpectation", item.get("meet", False)))
                if meet or not statuses[key].meet:
                    statuses[key].meet = meet
                    statuses[key].justification = str(item.get("justification", "")).strip()
                    statuses[key].source = "llm_window"
        return statuses

    def _windows(self, events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        if not events:
            return []
        step = max(1, self.window_turns - self.overlap_turns)
        return [events[start : start + self.window_turns] for start in range(0, len(events), step)]

    def _judge_window(
        self,
        task: dict[str, Any],
        window: list[dict[str, Any]],
        statuses: dict[str, RubricStatus],
        window_idx: int,
        total_windows: int,
    ) -> list[dict[str, Any]]:
        current = [
            {
                "rubric_key": status.key,
                "rubric": status.rubric,
                "dimension": status.dimension,
                "meetExpectation": status.meet,
                "justification": status.justification,
            }
            for status in statuses.values()
        ]
        system = (
            "You are a strict trajectory evaluator for a travel companion agent. "
            "Use sliding-window rubric evaluation. Update rubric status based only on evidence in the current window, "
            "the task instruction, and current rubric states. Tool results are assistant-visible evidence; successful task "
            "completion must be grounded in assistant actions, tool calls, or final response. Return only JSON array."
        )
        payload = {
            "window_idx": window_idx,
            "total_windows": total_windows,
            "city": task.get("city"),
            "user_complete_instruction": task.get("user_scenario", {}).get("complete_instruction"),
            "hidden_constraints": task.get("user_scenario", {}).get("hidden_constraints", []),
            "expected_trajectory": task.get("expected_trajectory", {}),
            "window_content": window,
            "current_rubrics": current,
            "format": [
                {
                    "rubric_key": "same key",
                    "rubric": "restated rubric",
                    "justification": "brief evidence or reason",
                    "meetExpectation": True,
                }
            ],
        }
        parsed = self.llm.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": compact_json(payload, limit=12000)},
            ],
            temperature=0.0,
        )
        if isinstance(parsed, dict):
            parsed = parsed.get("rubrics") or parsed.get("results") or []
        if not isinstance(parsed, list):
            raise ValueError("window judge did not return a list")
        return [item for item in parsed if isinstance(item, dict)]

    @staticmethod
    def _trajectory_checks(task: dict[str, Any], trajectory: dict[str, Any]) -> dict[str, Any]:
        expected = task.get("expected_trajectory", {})
        events = trajectory.get("events", [])
        tools = [event.get("tool") for event in events if event.get("type") == "tool_call"]
        intents = [event.get("intent") for event in events if event.get("type") == "assistant_message"]
        required_tools = list(expected.get("tools_must_call") or [])
        forbidden_tools = list(expected.get("tools_should_not_call") or [])
        required_intent = expected.get("required_intent")
        checks = {
            "required_intent": (required_intent in intents) if required_intent else True,
            "tools_must_call": {tool: tool in tools for tool in required_tools},
            "tools_should_not_call": {tool: tool not in tools for tool in forbidden_tools},
        }
        checks["passed"] = (
            bool(checks["required_intent"])
            and all(checks["tools_must_call"].values())
            and all(checks["tools_should_not_call"].values())
        )
        return checks

    @staticmethod
    def _score(
        task: dict[str, Any],
        statuses: dict[str, RubricStatus],
        trajectory_checks: dict[str, Any],
    ) -> dict[str, Any]:
        rubric_items = list(statuses.values())
        total = len(rubric_items)
        passed = sum(1 for item in rubric_items if item.meet)
        dim_scores: dict[str, float] = {}
        for dim in sorted({item.dimension for item in rubric_items}):
            items = [item for item in rubric_items if item.dimension == dim]
            dim_scores[dim] = sum(1 for item in items if item.meet) / len(items) if items else 0.0
        failed = [item for item in rubric_items if not item.meet]
        required_tool_checks = trajectory_checks.get("tools_must_call", {})
        tool_success = (
            sum(1 for ok in required_tool_checks.values() if ok) / len(required_tool_checks)
            if required_tool_checks
            else dim_scores.get("tool", 1.0)
        )
        strict = total > 0 and passed == total and bool(trajectory_checks.get("passed", True))
        return {
            "task_id": task.get("id"),
            "city": task.get("city"),
            "strict_success": strict,
            "rubric_score": passed / total if total else 0.0,
            "rubrics_passed": passed,
            "rubrics_total": total,
            "dimension_scores": dim_scores,
            "tool_success": tool_success,
            "interaction_score": dim_scores.get("interaction", 0.0),
            "final_response_score": dim_scores.get("interaction", 0.0),
            "trajectory_checks": trajectory_checks,
            "failed_rubrics": [
                {
                    "key": item.key,
                    "dimension": item.dimension,
                    "rubric": item.rubric,
                    "justification": item.justification,
                }
                for item in failed
            ],
            "rubric_details": [
                {
                    "key": item.key,
                    "dimension": item.dimension,
                    "rubric": item.rubric,
                    "meetExpectation": item.meet,
                    "justification": item.justification,
                    "source": item.source,
                }
                for item in rubric_items
            ],
            "failure_tags": task.get("failure_tags", []) if not strict else [],
        }


class MetricsAggregator:
    @staticmethod
    def summarize(results: list[dict[str, Any]], k: int) -> dict[str, Any]:
        by_task: dict[str, list[dict[str, Any]]] = {}
        by_city: dict[str, list[dict[str, Any]]] = {}
        for result in results:
            by_task.setdefault(result["task_id"], []).append(result)
            by_city.setdefault(result["city"], []).append(result)

        task_metrics = {}
        for task_id, items in by_task.items():
            successes = [1 if item["strict_success"] else 0 for item in items]
            task_token_usage = aggregate_token_usage(
                [item.get("token_usage") for item in items],
                source="companion_eval_task",
            )
            task_metrics[task_id] = {
                "trials": len(items),
                "avg_at_k": sum(successes) / len(successes) if successes else 0.0,
                "pass_at_k": any(successes),
                "pass_all_k": all(successes) if successes else False,
                "avg_rubric_score": mean(item["rubric_score"] for item in items),
                "token_usage": task_token_usage,
                "avg_tokens_per_trial": round(task_token_usage.get("total_tokens", 0) / len(items), 2),
            }

        city_metrics = {}
        for city, items in by_city.items():
            city_metrics[city] = MetricsAggregator._group_summary(items)

        overall = MetricsAggregator._group_summary(results)
        overall["task_count"] = len(by_task)
        overall["trial_count"] = len(results)
        overall["k"] = k
        overall["pass_at_k"] = mean(1.0 if metric["pass_at_k"] else 0.0 for metric in task_metrics.values())
        overall["pass_all_k"] = mean(1.0 if metric["pass_all_k"] else 0.0 for metric in task_metrics.values())
        overall["avg_at_k"] = mean(metric["avg_at_k"] for metric in task_metrics.values())
        overall["avg_rubric_score_by_task"] = mean(metric["avg_rubric_score"] for metric in task_metrics.values())

        return {
            "overall": overall,
            "by_city": city_metrics,
            "by_task": task_metrics,
            "failure_tag_counts": MetricsAggregator._failure_tag_counts(results),
        }

    @staticmethod
    def _group_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {}
        dims = sorted({dim for item in items for dim in item.get("dimension_scores", {})})
        summary = {
            "strict_success_rate": mean(1.0 if item["strict_success"] else 0.0 for item in items),
            "avg_rubric_score": mean(item["rubric_score"] for item in items),
            "avg_tool_success": mean(item.get("tool_success", 0.0) for item in items),
            "avg_interaction_score": mean(item.get("interaction_score", 0.0) for item in items),
            "avg_final_response_score": mean(item.get("final_response_score", 0.0) for item in items),
            "dimension_scores": {
                dim: mean(item.get("dimension_scores", {}).get(dim, 0.0) for item in items)
                for dim in dims
            },
        }
        summary["token_usage"] = aggregate_token_usage(
            [item.get("token_usage") for item in items],
            source="companion_eval_group",
        )
        summary["avg_tokens_per_trial"] = round(
            summary["token_usage"].get("total_tokens", 0) / len(items),
            2,
        )
        return summary

    @staticmethod
    def _failure_tag_counts(results: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in results:
            for tag in result.get("failure_tags", []):
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def mean(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run CompanionAgent VitaBench-style evaluation.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASK_INDEX, help="Task index or city task JSON file.")
    parser.add_argument("--city", action="append", default=[], help="City to run. Can be repeated.")
    parser.add_argument("--task-id", action="append", default=[], help="Specific task id to run. Can be repeated.")
    parser.add_argument("--max-tasks", type=int, default=None, help="Limit number of tasks after filtering.")
    parser.add_argument("--num-trials", type=int, default=1, help="Repeated trials per task.")
    parser.add_argument("--max-turns", type=int, default=6, help="Max simulator-agent turns per trial.")
    parser.add_argument("--simulator", choices=["auto", "llm", "rule"], default="auto", help="User simulator mode.")
    parser.add_argument("--evaluator", choices=["auto", "llm", "hybrid", "rule"], default="auto", help="Evaluator mode.")
    parser.add_argument("--no-agent-llm", action="store_true", help="Force CompanionAgent deterministic fallback.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory.")
    return parser


def run(config: EvalConfig) -> dict[str, Any]:
    settings = Settings.from_env()
    llm = ChatLLM(settings)
    tasks = TaskLoader.filter_tasks(
        TaskLoader(config.task_path).load(),
        cities=config.cities,
        task_ids=config.task_ids,
        max_tasks=config.max_tasks,
    )
    if not tasks:
        raise ValueError("No tasks selected.")

    out_dir = config.out_dir or (EVAL_DIR / "companion_eval_runs" / now_id())
    out_dir.mkdir(parents=True, exist_ok=True)
    runner = TrajectoryRunner(settings=settings, config=config, llm=llm)
    evaluator = SlidingWindowEvaluator(
        llm=llm,
        mode=config.evaluator_mode,
        window_turns=config.window_turns,
        overlap_turns=config.overlap_turns,
    )

    all_scores: list[dict[str, Any]] = []
    for task in tasks:
        for trial in range(1, config.num_trials + 1):
            trajectory = runner.run_task_trial(task, trial)
            score = evaluator.evaluate(task, trajectory)
            score["trial_index"] = trial
            score["done_reason"] = trajectory["done_reason"]
            score["latency_ms"] = trajectory["latency_ms"]
            score["token_usage"] = trajectory["token_usage"]
            all_scores.append(score)
            append_jsonl(out_dir / "trajectories.jsonl", trajectory)
            append_jsonl(out_dir / "trial_results.jsonl", score)

    summary = MetricsAggregator.summarize(all_scores, k=config.num_trials)
    summary["config"] = {
        "task_path": str(config.task_path),
        "cities": config.cities,
        "task_ids": config.task_ids,
        "max_tasks": config.max_tasks,
        "num_trials": config.num_trials,
        "max_turns": config.max_turns,
        "simulator_mode": config.simulator_mode,
        "evaluator_mode": config.evaluator_mode,
        "agent_llm_enabled": not config.no_agent_llm,
        "llm_available": llm.available,
        "output_dir": str(out_dir),
    }
    summary["evaluation_llm_token_usage"] = llm.token_usage_summary()
    summary["total_token_usage"] = aggregate_token_usage(
        [
            summary.get("overall", {}).get("token_usage"),
            summary["evaluation_llm_token_usage"],
        ],
        model=settings.openai_model,
        source="companion_eval_total",
    )
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    config = EvalConfig(
        task_path=args.tasks,
        cities=args.city,
        task_ids=args.task_id,
        max_tasks=args.max_tasks,
        num_trials=max(1, args.num_trials),
        max_turns=max(1, args.max_turns),
        simulator_mode=args.simulator,
        evaluator_mode=args.evaluator,
        no_agent_llm=args.no_agent_llm,
        out_dir=args.out_dir,
    )
    summary = run(config)
    print(json.dumps(summary["overall"], ensure_ascii=False, indent=2))
    print(f"Output: {summary['config']['output_dir']}")


if __name__ == "__main__":
    main()
