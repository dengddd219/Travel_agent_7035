"""FastAPI backend — bridges the HTML frontend with TravelPlanningAgent."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing travel_planner from the sibling directory
sys.path.insert(0, str(Path(__file__).parent.parent / "3-travel_planner"))
# Allow importing WeatherCost shim package from backend/
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from travel_planner.agent import TravelPlanningAgent, ConversationState
from travel_planner.ui_backend import (
    InMemoryConversationStore,
    build_frontend_response,
    deserialize_conversation_state,
    serialize_conversation_state,
)
from travel_planner.config import Settings

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
    needs_clarification: bool = False
    missing_profile_slots: list[str] = Field(default_factory=list)
    pending_profile_slots: list[str] = Field(default_factory=list)
    tool_logs: list[dict]


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


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    import traceback
    agent = TravelPlanningAgent(settings=settings)

    try:
        if req.conversation_id and req.conversation_state:
            state = deserialize_conversation_state(req.conversation_state)
            run_result = agent.continue_conversation(state=state, user_request=req.message)
            conversation_id = req.conversation_id
        else:
            run_result = agent.start_conversation(user_request=req.message)
            conversation_id = store.create(run_result.state)

        store.set(conversation_id, run_result.state)

        payload = build_frontend_response(
            conversation_id=conversation_id,
            run_result=run_result,
        )

        return ChatResponse(
            conversation_id=payload["conversation_id"],
            conversation_state=payload["conversation_state"],
            report=payload["report"],
            itinerary_json=payload["itinerary_json"],
            map_payload=payload["map_payload"],
            hotel_recommendations=payload["hotel_recommendations"],
            needs_clarification=payload.get("needs_clarification", False),
            missing_profile_slots=payload.get("missing_profile_slots", []),
            pending_profile_slots=payload.get("pending_profile_slots", []),
            tool_logs=payload["tool_logs"],
        )
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail={"error": str(e), "traceback": tb})


@app.get("/health")
def health():
    return {"status": "ok"}
