# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

MSBA 7035 "AI Engineering Practice" course project at HKU. The repo has two parts:
- `参考/` — Completed reference implementations of LLM techniques (prompt engineering, chatbots, function calling, agents, fine-tuning)
- `docs/` — Planning documents for the active group project: an AI Travel Planning Agent (deadline: April 25, 2026)

## Environment Setup

All modules use Azure OpenAI. Copy `参考/2.prompt engineering homework/.env.example` to `.env` and fill in:

```
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2025-01-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4.1-mini
FOUNDRY_PROJECT_ENDPOINT=...
FOUNDRY_PROJECT_API_KEY=...
FOUNDRY_PROJECT_DEPLOYMENT=...
```

## Running Reference Code

No top-level build system. Each sub-module is run directly:

```bash
# Prompt engineering
python "参考/2.prompt engineering homework/resume_editor.py"

# Chatbot (console)
python 参考/3.chatbot/chatbot.py

# Chatbot (Streamlit UI)
streamlit run 参考/3.chatbot/chatbot2_streamlit.py

# Function calling
python "参考/4.function calling/function_call.py"

# Agents
python 参考/5.agents/agent_function_calling.py

# Fine-tuning
python 参考/7.fine-tuning/ft.py
```

## Architecture: Active Group Project (Travel Agent)

The travel agent (`docs/superpowers/specs/2026-04-20-travel-agent-prd.md`) is a 6-module Streamlit app:

```
User Input (Streamlit)
      ↓
ReAct Agent (LangChain or OpenAI Function Calling)
  ├── M1: RAG — ChromaDB + text-embedding-3-small, ~700 Xiaohongshu travel notes, 10 Chinese cities
  ├── M2: Gaode Maps API — POI search, route planning, polyline geometry
  ├── M4: Weather API (Hefeng/OpenWeatherMap) + static cost estimator
  └── M6: LLM-as-Judge evaluation (5-dimension scoring, radar chart)
      ↓
Pydantic TripPlan (structured JSON via OpenAI response_format)
      ↓
Streamlit UI
  ├── Tab 1: Chat + Folium map (per-day colored routes + POI popups) + cost table
  └── Tab 2: Evaluation radar chart + 5 test cases (TC-01 to TC-05)
```

**Key constraints:** Single destination only, 2–5 day trips, 10 supported Chinese cities, no persistence beyond session.

**Pydantic data model:**
```python
class POI(BaseModel): name, category, lat, lng, description, duration_min, cost_cny
class DayItinerary(BaseModel): day, date, theme, pois: list[POI], route_polyline, daily_cost_cny
class TripPlan(BaseModel): destination, start_date, days, total_budget_cny, itinerary: list[DayItinerary], rag_sources: list[str]
```

## Architecture: Reference Code

The shared Azure OpenAI client is `参考/2.prompt engineering homework/azure_openai_client.py` — it wraps chat completions, vision, embeddings, token counting, and cost calculation. All other reference modules import or replicate this pattern.

Reference modules demonstrate the full course curriculum: prompt engineering → chatbot memory/summarization → function calling with DB/MCP → Azure AI Foundry agents (file search, code interpreter, web search) → fine-tuning with JSONL datasets.

## Key Technical Choices

- **LLM calls**: Use `AzureOpenAI` client (`openai` package) or `azure.ai.projects` (AI Foundry) with `DefaultAzureCredential`
- **Structured output**: `client.beta.chat.completions.parse()` with Pydantic models for guaranteed schema compliance
- **RAG**: ChromaDB vector store, `text-embedding-3-small` embeddings
- **UI**: Streamlit + Folium maps via `st.components.v1.html()`
- **Evaluation**: Separate GPT-4o call with JSON scoring rubric — never mix judge and planner in the same call
