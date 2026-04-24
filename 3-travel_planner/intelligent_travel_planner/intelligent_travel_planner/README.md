## author:SUN Bin

# Intelligent Travel Planner

This project is a travel-planning backend for the group project. It keeps only the parts that are still used in the current demo and integration flow:

- a single orchestration agent
- local RAG-backed strategy retrieval
- Amap POI search and route optimization
- Group C weather / cost / hotel adapters
- review + auto replan
- FastAPI endpoints for UI integration
- a lightweight demo page

## What The System Does

The current end-to-end flow is:

1. Parse a user request into a normalized travel profile.
2. Decompose the request into:
   - strategy queries
   - geo / POI queries
   - condition queries
3. Read city profile context.
4. Retrieve strategy signals from the local RAG corpus.
5. Search POIs and optimize intra-day route order with Amap.
6. Pull weather, budget, and first-stage hotel suggestions.
7. Plan a multi-day itinerary.
8. Run review and, if needed, one automatic replan pass.
9. Return:
   - structured itinerary JSON
   - map payload
   - user-friendly Chinese report
   - guide signals
   - weather outlook
   - hotel suggestions

## Current Folder Structure

```text
intelligent_travel_planner/
  README.md
  requirements.txt
  .env.example
  web_demo.html
  amap_ui_bridge.js
  docs/
    a_group_rag_api_contract.md
    agent_orchestration_playbook.md
    c_group_weather_cost_api_contract.md
    d_group_ui_integration_contract.md
  WeatherCost/
    README.md
    weather_cost_api.py
  amap_ui_delivery/
    amap-env.js
    map.css
    map.js
  rag_pipeline_delivery/
    data/
      raw/
        Chengdu/
        Shanghai/
        Nanjing/
        ...
    rag/
      chunking/
      cleaning/
      utils/
  tests/
    test_agent_orchestration.py
    test_city_profiles.py
    test_hotel_adapter.py
    test_planner.py
    test_poi_city_filter.py
    test_routing.py
    test_strategy_rag_adapter.py
    test_ui_backend.py
    test_weather_cost_adapters.py
  travel_planner/
    __init__.py
    agent.py
    api.py
    city_names.py
    config.py
    data_store.py
    llm.py
    models.py
    planner.py
    ui_backend.py
    data/
      city_profiles/
    tools/
      __init__.py
      city_context.py
      cost_adapter.py
      hotel_adapter.py
      poi.py
      routing.py
      strategy_rag_adapter.py
      tips.py
      weather_adapter.py
```

## Main Code Files

### Core orchestration

- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/agent.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/planner.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/models.py`

### API and UI bridge

- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/api.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/ui_backend.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/web_demo.html`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/amap_ui_bridge.js`

### Tool layer

- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/tools/strategy_rag_adapter.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/tools/poi.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/tools/routing.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/tools/weather_adapter.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/tools/cost_adapter.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/tools/hotel_adapter.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/tools/tips.py`

## RAG Usage

The current strategy layer reads the local RAG delivery folder directly:

- raw guide data from `rag_pipeline_delivery/data/raw`
- markdown parsing from `rag_pipeline_delivery/rag/utils`
- cleaning from `rag_pipeline_delivery/rag/cleaning`
- chunking from `rag_pipeline_delivery/rag/chunking`

At runtime, the project does **not** rely on a separate hosted vector DB service. It builds a lightweight local retrieval view from the kept corpus and uses it to produce:

- `recommended_pois`
- `theme_suggestions`
- `guide_references`
- `neighborhood_notes`

## API Endpoints

Start the API from the project root:

```bash
uvicorn travel_planner.api:app --reload
```

Available endpoints:

- `GET /api/health`
- `POST /api/plan`
- `POST /api/refine`
- `GET /demo`

## Demo

Local demo page:

- [http://127.0.0.1:8000/demo](http://127.0.0.1:8000/demo)

If you run the demo on another port, use the same `/demo` route on that port.

The demo currently shows:

- map route view
- user-friendly report
- guide signals
- weather outlook
- review & replan
- hotel suggestions

The raw internal markdown report is no longer shown to the user-facing UI.

## Multi-turn Use

Two common ways to use the backend:

- `POST /api/plan`
  creates a new conversation and returns a fresh plan
- `POST /api/refine`
  continues from the previous state and updates the existing plan

The refine flow keeps remembered preferences, but resets conflicting city-specific memory when the destination city changes.

## Environment Variables

Copy `.env.example` to `.env`.

Recommended minimum:

```bash
FOUNDRY_PROJECT_RESOURCE=...
FOUNDRY_PROJECT_API_KEY=...
FOUNDRY_PROJECT_DEPLOYMENT=...
AMAP_API_KEY=...
AMAP_WEB_SERVICE_KEY=...
```

Optional but useful:

```bash
TAVILY_API_KEY=...
DEFAULT_CITY=Nanjing
USE_PLAYWRIGHT_SCRAPER=true
PLAYWRIGHT_HEADLESS=false
USE_PERSISTENT_LOGIN_CONTEXT=true
CTRIP_MANUAL_LOGIN_ON_START=false
PLAYWRIGHT_USER_DATA_DIR=.playwright/ctrip-user-data
CTRIP_HOTEL_ENTRY_URL=https://hotels.ctrip.com/?allianceid=4899&sid=963772
ALLOW_MOCK_DATA=true
```

## Installation

```bash
python3 -m pip install -r requirements.txt
```

## Tests

Run from the project root:

```bash
python3 -m unittest discover -s tests
```

## D Group Integration

If you are sending files to D group for frontend integration, the most important ones are:

- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/api.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/travel_planner/ui_backend.py`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/amap_ui_bridge.js`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/amap_ui_delivery/map.js`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/amap_ui_delivery/map.css`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/amap_ui_delivery/amap-env.js`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/docs/d_group_ui_integration_contract.md`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/web_demo.html`

## Coordination Docs

The current collaboration docs are:

- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/docs/agent_orchestration_playbook.md`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/docs/a_group_rag_api_contract.md`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/docs/c_group_weather_cost_api_contract.md`
- `/Users/sunbinsmacbookpro/Desktop/MSBA7035/group_project/intelligent_travel_planner/docs/d_group_ui_integration_contract.md`
