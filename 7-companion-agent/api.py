from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from pydantic import BaseModel, Field

from companion_agent import CompanionAgent
from models import CompanionState
from token_costing import post_trace_webhook, with_token_cost


app = FastAPI(title="Companion Agent API")
agent = CompanionAgent()

EVAL_TRACE_PATH = Path(__file__).parent.parent / "5-evaluate" / "eval_trace.jsonl"


def _write_companion_trace(record: dict) -> None:
    try:
        EVAL_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVAL_TRACE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        post_trace_webhook(record)
    except Exception:
        pass


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/companion", response_model=CompanionResponse)
def companion(req: CompanionRequest) -> CompanionResponse:
    state = CompanionState.from_dict(req.conversation_state)
    t_start = time.monotonic()
    result = agent.run_turn(req.message, state=state)
    total_ms = int((time.monotonic() - t_start) * 1000)

    conversation_id = req.conversation_id or "local-companion"
    turn = len((result.state or state).turn_history) // 2  # user+assistant pairs

    token_usage = with_token_cost(result.token_usage or {}, model=agent.settings.openai_model)
    alerts = []
    if total_ms > 30_000:
        alerts.append(f"HIGH_LATENCY: {total_ms}ms")
    if token_usage.get("total_tokens", 0) > 8_000:
        alerts.append(f"HIGH_TOKEN: {token_usage['total_tokens']} tokens")

    _write_companion_trace({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "companion",
        "conversation_id": conversation_id,
        "turn": turn,
        "intent": result.intent,
        "city": (result.state or state).city,
        "latency_ms": {"total": total_ms},
        "token_usage": token_usage,
        "tool_call_count": len(result.tool_logs),
        "alerts": alerts,
    })

    return CompanionResponse(
        conversation_id=conversation_id,
        conversation_state=(result.state or state).to_dict(),
        reply=result.reply,
        intent=result.intent,
        cards=result.cards,
        tool_logs=result.tool_logs if req.debug else [],
        warnings=result.warnings,
        error=result.error,
        token_usage=token_usage,
    )
