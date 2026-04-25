# DEBUG_AGENT 调试模式使用说明

## 背景

在开发 RAG+Agent 系统时，Agent 对 RAG 检索结果的处理过程是一个黑盒：不清楚检索了什么、检索结果如何影响规划决策。为提升开发可观测性，项目引入了 `DEBUG_AGENT` 终端调试模式，可实时追踪每一步的输入输出，且与生产环境推理流程完全一致（通过环境变量开关，不影响任何业务逻辑）。

---

## 如何启动

> `uvicorn` 必须在项目根目录（`Travel_agent_7035/`）下运行，因为 `backend/server.py` 的路径计算以自身位置为基准。

### Windows PowerShell（推荐）
```powershell
cd C:\Users\19841\Desktop\github\7035project\Travel_agent_7035
$env:DEBUG_AGENT=1; uvicorn backend.server:app --reload
```

### Windows CMD
```cmd
cd C:\Users\19841\Desktop\github\7035project\Travel_agent_7035
set DEBUG_AGENT=1 && uvicorn backend.server:app --reload
```

启动成功后终端会显示：
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process ...
```

然后打开浏览器访问 `http://localhost:8000`，发送一条对话请求，终端即实时打印完整调试追踪。

---

## 终端输出示例

以下是发送请求「帮我规划3天成都美食之旅」时的预期终端输出：

```
════════════════════════════════════════════════════════════════════════════
  DEBUG_AGENT  |  Turn 1
════════════════════════════════════════════════════════════════════════════
  User request: "帮我规划3天成都美食之旅"

════════════════════════════════════════════════════════════════════════════
①  STEP 1 — Intent Extraction (user profile)
────────────────────────────────────────────────────────────────────────────
  city:         "Chengdu"
  trip_days:    3
  travel_type:  "food"
  budget_level: "medium"
  pace:         "balanced"
  interests:    ["local_food", "street_food"]
  must_visit:   []
  avoid:        []

════════════════════════════════════════════════════════════════════════════
②  STEP 2 — Query Decomposition
────────────────────────────────────────────────────────────────────────────
  strategy_queries: ["成都 美食 推荐", "成都 小吃 街", "成都 火锅 人均"]
  geo_queries:      ["成都 宽窄巷子", "成都 锦里", "成都 春熙路"]
  condition_queries: {"cost": {"user_budget": null}}

════════════════════════════════════════════════════════════════════════════
③  STEP 3 — RAG Retrieval INPUT
────────────────────────────────────────────────────────────────────────────
  city:        "Chengdu"
  travel_type: "food"
  top_k:       5
  queries:     ["成都 美食 推荐", "成都 小吃 街", "成都 火锅 人均"]

  ⏱  RAG retrieval: 0.43s

════════════════════════════════════════════════════════════════════════════
③  STEP 3 — RAG Retrieval OUTPUT
────────────────────────────────────────────────────────────────────────────
  retrieval_mode:  "group_a_search_notes_hybrid"
  source:          "search_notes"
  total_chunks:    5
  recommended_pois: ["宽窄巷子", "锦里", "玉林路小酒馆", "春熙路"]
  theme_suggestions: ["美食探索", "夜生活", "网红打卡"]
  local_pitfalls:  ["避开节假日人流高峰", "锦里夜市价格偏高，建议白天去"]

  Per-query diagnostics:
    • [hybrid] score_count=5
      query: 成都 美食 推荐
      top chunks: ["chunk_cd_001", "chunk_cd_004", "chunk_cd_009"]
    • [hybrid] score_count=4
      query: 成都 小吃 街
      top chunks: ["chunk_cd_003", "chunk_cd_007"]
    • [hybrid] score_count=3
      query: 成都 火锅 人均
      top chunks: ["chunk_cd_012"]

  Top-3 raw chunks:
    [1] score=0.8821  chunk_id=chunk_cd_001
        宽窄巷子是成都最具代表性的历史街区，汇聚了大量本地小吃和茶馆，适合上午游览，人少且光线好…
    [2] score=0.8543  chunk_id=chunk_cd_004
        锦里依托武侯祠，夜晚灯光氛围极佳，串串香和冒菜是必试项目，建议傍晚入场…
    [3] score=0.7912  chunk_id=chunk_cd_009
        玉林路是本地人聚集的生活街区，小龙坎火锅总店在此，人均约80-120元…

════════════════════════════════════════════════════════════════════════════
④  TOOL — get_city_context
────────────────────────────────────────────────────────────────────────────
  arguments:      {"city": "Chengdu", "travel_type": "food"}
  result_summary: {"provider": "city_profiles", "districts": 6, ...}

⑤  TOOL — search_batch_pois
────────────────────────────────────────────────────────────────────────────
  arguments:      {"city": "Chengdu", "queries": [...], "limit_per_query": 3}
  result_summary: {"result_count": 12, "provider": "profile_seed",
                   "sample_names": ["宽窄巷子", "锦里", "春熙路", "武侯祠"]}

⑥  TOOL — get_weather_forecast
────────────────────────────────────────────────────────────────────────────
  arguments:      {"city": "Chengdu", "trip_days": 3}
  result_summary: {"forecast": "多云转小雨", ...}

⑦  TOOL — get_cost_summary
────────────────────────────────────────────────────────────────────────────
  arguments:      {"city": "Chengdu", "days": 3, "budget_level": "medium"}
  result_summary: {"total_cost": "1200-2000", "daily_cost": "400-670", ...}

⑧  TOOL — get_travel_tips
────────────────────────────────────────────────────────────────────────────
  arguments:      {"city": "Chengdu", "poi_names": [...], "travel_type": "food"}
  result_summary: {"tips_count": 8}

════════════════════════════════════════════════════════════════════════════
④  STEP 4 — Planner INPUT (how RAG feeds planning)
────────────────────────────────────────────────────────────────────────────
  rag_recommended_pois (fed to planner): ["宽窄巷子", "锦里", "玉林路小酒馆", "春熙路"]
  neighborhood_notes_count: 3
  total_pois_before_select: 14

════════════════════════════════════════════════════════════════════════════
⑤  STEP 5 — Final Plan OUTPUT
────────────────────────────────────────────────────────────────────────────
  total_days: 3
  Day 1: 锦江区 | 美食探索
    POIs: ["宽窄巷子", "锦里", "春熙路"]
  Day 2: 武侯区 | 市井烟火
    POIs: ["玉林路小酒馆", "小龙坎火锅", "太古里"]
  Day 3: 青羊区 | 茶馆文化
    POIs: ["文殊院", "琴台路", "浣花溪公园"]
  planning_notes: ["按区域聚类减少跨城通勤", "RAG 推荐 POI 命中率 4/4"]

════════════════════════════════════════════════════════════════════════════
```

---

## 各步骤说明

| 步骤 | 对应代码位置 | 展示内容 |
|------|-------------|---------|
| ① Intent Extraction | `agent.py` → `_resolve_user_profile()` | 从自然语言提取的结构化用户画像 |
| ② Query Decomposition | `agent.py` → `_decompose_request()` | RAG 检索查询 + 地理查询 + 条件查询 |
| ③ RAG Input/Output | `strategy_rag_adapter.py` → `get_strategy_context()` | 检索模式、每条 query 命中数、Top-3 原始 chunk 文本 |
| ④–⑧ Tool Calls | `agent.py` → `_execute()` 确定性调用段 | 每个工具的入参与结果摘要 |
| ④ Planner Input | `agent.py` → `_auto_finish()` | RAG 推荐 POI 如何传入规划器 |
| ⑤ Plan Output | `agent.py` → `_auto_finish()` | 最终每日行程与规划注记 |

---

## 与生产环境的一致性保证

所有 trace 函数在 `DEBUG_AGENT` 未设置时为**纯 no-op**，实现在 `3-travel_planner/travel_planner/debug_tracer.py` 第一行：

```python
_ENABLED = os.getenv("DEBUG_AGENT", "").strip() in ("1", "true", "yes")
```

- 不添加任何条件分支
- 不修改任何返回值
- 不影响工具调用顺序
- 生产环境无性能损耗

---

## 实现文件

| 文件 | 说明 |
|------|------|
| `3-travel_planner/travel_planner/debug_tracer.py` | 新增：所有 trace 函数实现 |
| `3-travel_planner/travel_planner/agent.py` | 修改：新增 import + 各步骤 trace 调用 |
