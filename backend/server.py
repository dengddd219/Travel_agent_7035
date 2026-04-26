"""FastAPI backend — bridges the HTML frontend with TravelPlanningAgent."""
from __future__ import annotations

import sys
import json
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

# Allow importing travel_planner from the sibling directory
sys.path.insert(0, str(Path(__file__).parent.parent))
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
from token_costing import estimated_token_usage, estimate_token_count, post_trace_webhook, with_token_cost

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


@app.on_event("startup")
def _print_trace_startup_banner() -> None:
    print("", flush=True)
    print("=" * 78, flush=True)
    print("Travel backend started", flush=True)
    print("-" * 78, flush=True)
    print(f"TRACE_AGENT={os.getenv('TRACE_AGENT', '')!r}", flush=True)
    print(f"DEBUG_AGENT={os.getenv('DEBUG_AGENT', '')!r}", flush=True)
    print(f"TRACE_FULL={os.getenv('TRACE_FULL', '')!r}", flush=True)
    print(f"TRACE_PREVIEW_CHARS={os.getenv('TRACE_PREVIEW_CHARS', '')!r}", flush=True)
    print(f"TRACE_RAG_CHUNKS={os.getenv('TRACE_RAG_CHUNKS', '')!r}", flush=True)

# ── Eval trace ────────────────────────────────────────────────────────────────

EVAL_TRACE_PATH = Path(__file__).parent.parent / "5-evaluate" / "eval_trace.jsonl"

_ALERT_THRESHOLDS = {
    "total_latency_ms": 30_000,
    "estimated_total_tokens": 8_000,
}

_TRACE_TRUTHY = {"1", "true", "yes", "on"}


def _trace_enabled() -> bool:
    return (
        os.getenv("TRACE_AGENT", "").strip().lower() in _TRACE_TRUTHY
        or os.getenv("DEBUG_AGENT", "").strip().lower() in _TRACE_TRUTHY
    )


def _trace_preview(value: object) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        text = str(value)
    if os.getenv("TRACE_FULL", "").strip().lower() in _TRACE_TRUTHY:
        return text
    try:
        limit = int(os.getenv("TRACE_PREVIEW_CHARS", "3000").strip() or "3000")
    except ValueError:
        limit = 3000
    return text if limit <= 0 or len(text) <= limit else text[:limit].rstrip() + "..."


def _trace_backend_event(title: str, payload: dict) -> None:
    if not _trace_enabled():
        return
    print("", flush=True)
    print("=" * 78, flush=True)
    print(title, flush=True)
    print("-" * 78, flush=True)
    for key, value in payload.items():
        print(f"{key}: {_trace_preview(value)}", flush=True)


def _estimate_tokens(text: str) -> int:
    """Local token estimate used when provider usage is unavailable."""
    token_count, _source = estimate_token_count(text, settings.foundry_deployment)
    return token_count


def _write_eval_trace(record: dict) -> None:
    """Append one JSON record to eval_trace.jsonl (non-blocking best-effort)."""
    try:
        EVAL_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVAL_TRACE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        post_trace_webhook(record)
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
    token_usage = estimated_token_usage(
        user_message,
        report,
        model=settings.foundry_deployment,
    )
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "travel_planner",
        "conversation_id": conversation_id,
        "turn": turn,
        "city": city,
        "trip_days": trip_days,
        "latency_ms": {
            "total": total_ms,
            "per_tool": tool_latencies,
        },
        "token_usage": token_usage,
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
    plan_cost_summary: dict = Field(default_factory=dict)
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
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(index))


@app.get("/chat")
def serve_chat():
    chat = FRONTEND_DIR / "chat.html"
    if not chat.exists():
        raise HTTPException(status_code=404, detail="chat.html not found")
    return FileResponse(str(chat))


@app.get("/api/trace-test")
def trace_test():
    print("", flush=True)
    print("=" * 78, flush=True)
    print("TRACE TEST HIT", flush=True)
    print("-" * 78, flush=True)
    print("If you can see this line in the terminal, browser traffic reaches this uvicorn process.", flush=True)
    return {
        "ok": True,
        "message": "trace test printed to uvicorn terminal",
        "trace_agent": os.getenv("TRACE_AGENT", ""),
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    import traceback
    agent = get_agent()

    t_start = time.monotonic()
    _trace_backend_event(
        "Backend request | /api/chat",
        {
            "message": req.message,
            "conversation_id": req.conversation_id,
            "has_conversation_state": req.conversation_state is not None,
        },
    )
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

        _trace_backend_event(
            "Backend response | /api/chat",
            {
                "conversation_id": payload["conversation_id"],
                "turn": turn,
                "total_ms": total_ms,
                "needs_clarification": payload.get("needs_clarification", False),
                "missing_profile_slots": payload.get("missing_profile_slots", []),
                "tool_log_count": len(payload["tool_logs"]),
                "tool_logs": payload["tool_logs"],
                "report_preview": payload.get("report", ""),
            },
        )
        return ChatResponse(
            conversation_id=payload["conversation_id"],
            conversation_state=payload["conversation_state"],
            report=payload["report"],
            itinerary_json=payload["itinerary_json"],
            map_payload=payload["map_payload"],
            hotel_recommendations=payload["hotel_recommendations"],
            cost_summary=payload.get("cost_summary", {}),
            plan_cost_summary=payload.get("plan_cost_summary", {}),
            needs_clarification=payload.get("needs_clarification", False),
            missing_profile_slots=payload.get("missing_profile_slots", []),
            pending_profile_slots=payload.get("pending_profile_slots", []),
            tool_logs=payload["tool_logs"],
        )
    except Exception as e:
        tb = traceback.format_exc()
        _trace_backend_event(
            "Backend error | /api/chat",
            {"error": str(e), "traceback": tb},
        )
        raise HTTPException(status_code=500, detail={"error": str(e), "traceback": tb})


@app.post("/api/companion", response_model=CompanionResponse)
def companion(req: CompanionRequest):
    _trace_backend_event(
        "Backend request | /api/companion",
        {
            "message": req.message,
            "conversation_id": req.conversation_id,
            "has_conversation_state": req.conversation_state is not None,
        },
    )
    try:
        agent = get_companion_agent()
        state = CompanionState.from_dict(req.conversation_state)
        t_start = time.monotonic()
        result = agent.run_turn(req.message, state=state)
        total_ms = int((time.monotonic() - t_start) * 1000)
        next_state = result.state or state
        token_usage = with_token_cost(result.token_usage or {}, model=agent.settings.openai_model)
        alerts = []
        if total_ms > _ALERT_THRESHOLDS["total_latency_ms"]:
            alerts.append(f"HIGH_LATENCY: {total_ms}ms > {_ALERT_THRESHOLDS['total_latency_ms']}ms")
        if token_usage.get("total_tokens", 0) > _ALERT_THRESHOLDS["estimated_total_tokens"]:
            alerts.append(f"HIGH_TOKEN: {token_usage['total_tokens']} tokens")
        _write_eval_trace(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": "companion",
                "conversation_id": req.conversation_id or "local-companion",
                "turn": len(next_state.turn_history) // 2,
                "intent": result.intent,
                "city": next_state.city,
                "latency_ms": {"total": total_ms},
                "token_usage": token_usage,
                "tool_call_count": len(result.tool_logs),
                "alerts": alerts,
            }
        )
        _trace_backend_event(
            "Backend response | /api/companion",
            {
                "conversation_id": req.conversation_id or "local-companion",
                "intent": result.intent,
                "tool_log_count": len(result.tool_logs),
                "tool_logs": result.tool_logs,
                "warnings": result.warnings,
                "reply": result.reply,
            },
        )
        return CompanionResponse(
            conversation_id=req.conversation_id or "local-companion",
            conversation_state=next_state.to_dict(),
            reply=result.reply,
            intent=result.intent,
            cards=result.cards,
            tool_logs=result.tool_logs if req.debug else [],
            warnings=result.warnings,
            error=result.error,
            token_usage=token_usage,
        )
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        _trace_backend_event(
            "Backend error | /api/companion",
            {"error": str(e), "traceback": tb},
        )
        raise HTTPException(status_code=500, detail={"error": str(e), "traceback": tb})


@app.get("/health")
def health():
    return {"status": "ok"}
