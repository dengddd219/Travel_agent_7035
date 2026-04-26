"""FastAPI backend — bridges the HTML frontend with TravelPlanningAgent."""
from __future__ import annotations

import sys
import json
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

# Allow importing travel_planner from the sibling directory
sys.path.insert(0, str(Path(__file__).parent.parent / "3-travel_planner"))
# Allow importing the companion agent module from its sibling directory
sys.path.insert(0, str(Path(__file__).parent.parent / "7-companion-agent"))
# Allow importing WeatherCost shim package from backend/
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from travel_planner.agent import TravelPlanningAgent
from travel_planner.ui_backend import (
    InMemoryConversationStore,
    build_frontend_response,
    deserialize_conversation_state,
)
from travel_planner.config import Settings
from companion_agent import CompanionAgent
from models import CompanionState

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="Travel AI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the HTML frontend at /static (index, chat, assets)
FRONTEND_DIR = Path(__file__).parent.parent / "6-UI" / "UI"
MAP_UI_DIR   = Path(__file__).parent.parent / "6-UI" / "map_UI"
# More-specific mount must come first; /static/map_UI before /static
app.mount("/static/map_UI", StaticFiles(directory=str(MAP_UI_DIR)), name="map_ui")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

settings = Settings.from_env()
store = InMemoryConversationStore()

# ── Eval trace ────────────────────────────────────────────────────────────────

EVAL_TRACE_PATH = Path(__file__).parent.parent / "5-evaluate" / "eval_trace.jsonl"

_ALERT_THRESHOLDS = {
    "total_latency_ms": 30_000,
    "estimated_total_tokens": 8_000,
}


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: Chinese chars ~1.5 char/token, others ~4 char/token."""
    chinese = sum(1 for ch in text if "一" <= ch <= "鿿")
    others = len(text) - chinese
    return int(chinese / 1.5 + others / 4)


def _write_eval_trace(record: dict) -> None:
    """Append one JSON record to eval_trace.jsonl (non-blocking best-effort)."""
    try:
        EVAL_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVAL_TRACE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # never let tracing crash the main request


def _build_trace_record(
    *,
    conversation_id: str,
    turn: int,
    user_message: str,
    total_ms: int,
    tool_latencies: dict,
    report: str,
    city: str,
    trip_days: int,
    alerts: list[str],
) -> dict:
    input_tokens = _estimate_tokens(user_message)
    output_tokens = _estimate_tokens(report)
    total_tokens = input_tokens + output_tokens
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "turn": turn,
        "city": city,
        "trip_days": trip_days,
        "latency_ms": {
            "total": total_ms,
            "per_tool": tool_latencies,
        },
        "token_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "note": "estimated from character count, not from API usage field",
        },
        "tool_call_count": len(tool_latencies),
        "alerts": alerts,
    }


@lru_cache(maxsize=1)
def get_agent() -> TravelPlanningAgent:
    return TravelPlanningAgent(settings=settings)


@lru_cache(maxsize=1)
def get_companion_agent() -> CompanionAgent:
    return CompanionAgent()


# ── Request / response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None  # None = start new conversation
    conversation_state: dict | None = None  # serialized state from previous turn


class ChatResponse(BaseModel):
    conversation_id: str
    conversation_state: dict
    report: str                    # markdown text for chat bubble
    itinerary_json: dict
    map_payload: dict
    hotel_recommendations: dict
    cost_summary: dict = Field(default_factory=dict)
    needs_clarification: bool = False
    missing_profile_slots: list[str] = Field(default_factory=list)
    pending_profile_slots: list[str] = Field(default_factory=list)
    tool_logs: list[dict]


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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def serve_index():
    chat = FRONTEND_DIR / "chat.html"
    if not chat.exists():
        raise HTTPException(status_code=404, detail="chat.html not found")
    return FileResponse(str(chat))


@app.get("/chat")
def serve_chat():
    chat = FRONTEND_DIR / "chat.html"
    if not chat.exists():
        raise HTTPException(status_code=404, detail="chat.html not found")
    return FileResponse(str(chat))


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    import traceback
    agent = get_agent()

    t_start = time.monotonic()
    try:
        if req.conversation_id and req.conversation_state:
            state = deserialize_conversation_state(req.conversation_state)
            run_result = agent.continue_conversation(state=state, user_request=req.message)
            conversation_id = req.conversation_id
            turn = len(run_result.state.turn_history)
        else:
            run_result = agent.start_conversation(user_request=req.message)
            conversation_id = store.create(run_result.state)
            turn = 1

        store.set(conversation_id, run_result.state)

        payload = build_frontend_response(
            conversation_id=conversation_id,
            run_result=run_result,
        )

        total_ms = int((time.monotonic() - t_start) * 1000)

        # Pull per-tool latencies that agent embedded in tool_logs
        _latency_log = next(
            (log for log in run_result.tool_logs if log.get("tool_name") == "_tool_latencies"),
            None,
        )
        tool_latencies = json.loads(_latency_log["result_preview"]) if _latency_log else {}

        user_profile = run_result.state.latest_user_profile or {}
        alerts = []
        if total_ms > _ALERT_THRESHOLDS["total_latency_ms"]:
            alerts.append(f"HIGH_LATENCY: {total_ms}ms > {_ALERT_THRESHOLDS['total_latency_ms']}ms")
        est_tokens = _estimate_tokens(req.message) + _estimate_tokens(payload.get("report", ""))
        if est_tokens > _ALERT_THRESHOLDS["estimated_total_tokens"]:
            alerts.append(f"HIGH_TOKEN_ESTIMATE: ~{est_tokens} tokens")

        trace = _build_trace_record(
            conversation_id=conversation_id,
            turn=turn,
            user_message=req.message,
            total_ms=total_ms,
            tool_latencies=tool_latencies,
            report=payload.get("report", ""),
            city=user_profile.get("city", ""),
            trip_days=user_profile.get("trip_days", 0),
            alerts=alerts,
        )
        _write_eval_trace(trace)

        return ChatResponse(
            conversation_id=payload["conversation_id"],
            conversation_state=payload["conversation_state"],
            report=payload["report"],
            itinerary_json=payload["itinerary_json"],
            map_payload=payload["map_payload"],
            hotel_recommendations=payload["hotel_recommendations"],
            cost_summary=payload.get("cost_summary", {}),
            needs_clarification=payload.get("needs_clarification", False),
            missing_profile_slots=payload.get("missing_profile_slots", []),
            pending_profile_slots=payload.get("pending_profile_slots", []),
            tool_logs=payload["tool_logs"],
        )
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail={"error": str(e), "traceback": tb})


@app.post("/api/companion", response_model=CompanionResponse)
def companion(req: CompanionRequest):
    try:
        agent = get_companion_agent()
        state = CompanionState.from_dict(req.conversation_state)
        result = agent.run_turn(req.message, state=state)
        next_state = result.state or state
        return CompanionResponse(
            conversation_id=req.conversation_id or "local-companion",
            conversation_state=next_state.to_dict(),
            reply=result.reply,
            intent=result.intent,
            cards=result.cards,
            tool_logs=result.tool_logs if req.debug else [],
            warnings=result.warnings,
            error=result.error,
            token_usage=result.token_usage or {},
        )
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail={"error": str(e), "traceback": tb})


@app.get("/health")
def health():
    return {"status": "ok"}
