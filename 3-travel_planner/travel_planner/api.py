## author:SUN Bin
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .agent import TravelPlanningAgent
from .config import Settings
from .ui_backend import (
    InMemoryConversationStore,
    build_frontend_response,
    deserialize_conversation_state,
)

"""FastAPI entrypoint for frontend integration and local demo usage."""


class PlanRequest(BaseModel):
    """Request payload for creating a fresh plan."""
    user_message: str = Field(min_length=1)
    max_rounds: int = Field(default=8, ge=1, le=12)


class RefineRequest(BaseModel):
    """Request payload for updating an existing conversation / plan."""
    user_message: str = Field(min_length=1)
    conversation_id: str | None = None
    conversation_state: dict | None = None
    max_rounds: int = Field(default=8, ge=1, le=12)

    @model_validator(mode="after")
    def validate_state_source(self) -> "RefineRequest":
        """Require either a stored conversation id or an inline conversation state."""
        if not self.conversation_id and not self.conversation_state:
            raise ValueError("Either conversation_id or conversation_state must be provided.")
        return self


app = FastAPI(
    title="Intelligent Travel Planner Agent API",
    version="1.0.0",
    description="Backend endpoints for the B-group travel planning orchestrator.",
)
conversation_store = InMemoryConversationStore()
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "6-UI" / "UI"
MAP_UI_DIR = REPO_ROOT / "6-UI" / "map_UI"
DEMO_PAGE = REPO_ROOT / "6-UI" / "travel_chat.html"
DEMO_BRIDGE = MAP_UI_DIR / "amap-env.js"

if MAP_UI_DIR.exists():
    app.mount("/demo/amap", StaticFiles(directory=MAP_UI_DIR), name="demo_amap")
    app.mount("/static/map_UI", StaticFiles(directory=MAP_UI_DIR), name="map_ui")
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/demo", response_class=FileResponse)
def demo_page() -> FileResponse:
    target = DEMO_PAGE if DEMO_PAGE.exists() else FRONTEND_DIR / "index.html"
    if not target.exists():
        raise HTTPException(status_code=404, detail="Demo page not found.")
    return FileResponse(target)


@app.get("/demo/bridge.js", response_class=FileResponse)
def demo_bridge() -> FileResponse:
    if not DEMO_BRIDGE.exists():
        raise HTTPException(status_code=404, detail="Demo bridge not found.")
    return FileResponse(DEMO_BRIDGE)


@lru_cache(maxsize=1)
def get_agent() -> TravelPlanningAgent:
    """Reuse one agent instance across API calls."""
    return TravelPlanningAgent()


@app.get("/api/health")
def health_check() -> dict:
    """Small endpoint used by frontend or local checks to verify runtime readiness."""
    settings = Settings.from_env()
    return {
        "status": "ok",
        "llm_credentials_detected": settings.has_llm_credentials,
        "amap_key_detected": settings.has_amap_key,
        "default_city": settings.default_city,
    }


@app.post("/api/plan")
def create_plan(request: PlanRequest) -> dict:
    """Start a new conversation and return a frontend-ready response."""
    try:
        run_result = get_agent().start_conversation(
            request.user_message,
            max_rounds=request.max_rounds,
        )
    except Exception as exc:  # pragma: no cover - runtime path
        raise HTTPException(status_code=500, detail=f"Planning failed: {type(exc).__name__}: {exc}") from exc

    conversation_id = conversation_store.create(run_result.state)
    return build_frontend_response(
        conversation_id=conversation_id,
        run_result=run_result,
        polish_user_report=True,
    )


@app.post("/api/refine")
def refine_plan(request: RefineRequest) -> dict:
    """Continue an existing conversation and return the updated plan payload."""
    conversation_id = request.conversation_id
    state = conversation_store.get(conversation_id) if conversation_id else None

    if state is None and request.conversation_state:
        state = deserialize_conversation_state(request.conversation_state)
        if not conversation_id:
            conversation_id = conversation_store.create(state)

    if state is None or conversation_id is None:
        raise HTTPException(status_code=404, detail="Conversation state not found.")

    try:
        run_result = get_agent().continue_conversation(
            state,
            request.user_message,
            max_rounds=request.max_rounds,
        )
    except Exception as exc:  # pragma: no cover - runtime path
        raise HTTPException(status_code=500, detail=f"Refine failed: {type(exc).__name__}: {exc}") from exc

    conversation_store.set(conversation_id, run_result.state)
    return build_frontend_response(
        conversation_id=conversation_id,
        run_result=run_result,
        polish_user_report=True,
    )
