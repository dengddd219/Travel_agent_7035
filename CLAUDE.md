# CLAUDE.md — Travel_agent_7035 快速参考

> 本文件是给 Claude Code 的项目手册，目的是让新对话无需重读源码即可上手。
> 仅记录"看代码猜不到"的内容；代码本身是最终权威。

---

## 1. 项目一句话

HKU MSBA 7035 课程作业。AI 旅行规划 Agent：用户输入自然语言需求 → 多工具编排 → 结构化多日行程 + Markdown 报告 + 高德地图可视化。含陪伴 Agent（右侧面板）处理实时个性化请求。

---

## 2. 目录结构

```
Travel_agent_7035/
├── 0-data/              原始小红书旅行笔记（MD，按城市子目录）
├── 1-rag_pipeline_delivery/   离线 RAG 入库流水线
├── 2-rag-retrival/      在线 RAG 检索 API（search_notes.py）
├── 3-travel_planner/    核心规划 Agent 包（agent.py 是大脑）
├── 4-cost/              C 组子仓库：天气/酒店/费用 API
├── 5-evaluate/          评估目录（含 companion 测评流水线、RAGAS 评测、eval trace）
├── 6-UI/                前端（chat UI + 高德地图，双面板：左规划 / 右陪伴）
├── 7-companion-agent/   陪伴 Agent（附近搜索、行程重规划、应急处置）
└── backend/             FastAPI 入口（server.py，含 /api/chat + /api/companion）
```

---

## 3. 启动方式

```bash
# 主入口（前端 + API 一体）
cd Travel_agent_7035
uvicorn backend.server:app --app-dir . --host 127.0.0.1 --port 8000
# → http://localhost:8000/
# 注意：必须 --app-dir 指向 Travel_agent_7035 根目录，否则 companion agent import 会失败

# RAG 离线入库（在 1-rag_pipeline_delivery/ 的父目录运行）
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m rag.ingest   # 全城市
python -m rag.ingest --city chengdu                            # 单城市
python -m rag.ingest --reset                                   # 清空重建
python -m rag.evaluate                                         # HR + MRR 指标
# 当前 RAG V7: HR@5=93.5%, MRR=0.98（10城市, 930文档, 5948 chunks）

# 陪伴 Agent 测评（在 Travel_agent_7035/ 下运行）
python 5-evaluate/companion_eval_pipeline.py --num-trials 1 --simulator rule --evaluator rule --no-agent-llm
# 30 任务无 LLM 确定性跑分：strict_success=23.3%, avg_rubric=50.1%
```

---

## 4. 环境变量

**`3-travel_planner/travel_planner/config.py` (Settings dataclass):**
```
FOUNDRY_PROJECT_RESOURCE=...    # Azure 资源名（必填）
FOUNDRY_PROJECT_API_KEY=...
FOUNDRY_PROJECT_DEPLOYMENT=...  # 模型 deployment 名
FOUNDRY_PROJECT_ENDPOINT=...
AMAP_API_KEY=...                # 可选；缺失时降级 Nominatim → seed_pois
TAVILY_API_KEY=...              # 可选；缺失时用启发式 tips
DEFAULT_CITY=Hong Kong
```

**`4-cost/Group_C/Group_C/.env.example`:**
```
AMAP_WEB_SERVICE_KEY=...
USE_PLAYWRIGHT_SCRAPER=true
PLAYWRIGHT_HEADLESS=true
ALLOW_MOCK_DATA=true    # 本地调试时跳过 Playwright 爬虫
```

---

## 5. 调用链（最重要）

```
用户 POST /api/chat
  └─ backend/server.py
       ├─ 新会话 → agent.start_conversation(user_request)
       └─ 续会话 → agent.continue_conversation(state, user_request)

TravelPlanningAgent (agent.py)
  ├─ _extract_user_profile()        正则+别名表 → {city,trip_days,travel_type,budget_level,pace,interests,must_visit,avoid}
  ├─ _decompose_request()           生成 strategy_queries / geo_queries / condition_queries
  ├─ OpenAI Responses API 工具调用循环（≤8轮）
  │    ├─ get_city_context()        读 data/city_profiles/{city}.json
  │    ├─ get_strategy_context()    → search_notes.py (ChromaDB+BM25 hybrid)
  │    ├─ search_batch_pois()       高德 → Nominatim → seed_pois 三级降级
  │    ├─ get_weather_forecast()    → C组 get_weather_api() → 高德天气 REST
  │    ├─ get_cost_summary()        → C组 estimate_cost_api() → 静态费用表
  │    └─ get_travel_tips()         → Tavily → 启发式 fallback
  ├─ plan_itinerary()               纯 Python 确定性规划（无 LLM）
  │    ├─ _select_pois()            评分+去重+must_visit 保证
  │    ├─ _allocate_days()          按区域聚类 → TSP 暴力（≤4站）
  │    └─ review_itinerary()        must_visit/pace/budget/weather 审查
  ├─ get_hotel_candidates()         → C组 search_hotels_api() → Playwright/携程
  ├─ render_markdown_report()
  └─ build_frontend_response() → build_map_payload()

ChatResponse → {report, itinerary_json, map_payload, hotel_recommendations, tool_logs}
```

---

## 6. 多轮对话机制

| 字段 | 位置 | 说明 |
|---|---|---|
| `ConversationState` | agent.py:77 | 跨轮持久状态：`preference_memory`, `latest_user_profile`, `latest_plan`, `latest_report`, `turn_history` |
| `_extract_profile_updates()` | agent.py:514 | 解析"加上/去掉/换成"等增量指令，返回 `{replace, add, remove, append}` |
| `_merge_preference_memory()` | agent.py:617 | 把 updates 合并到 memory；**avoid 列表优先级高于 must_visit** |
| `InMemoryConversationStore` | ui_backend.py | `threading.Lock` 保护的 dict，重启即清空 |
| `serialize/deserialize_conversation_state` | ui_backend.py | 让前端可以 stateless 方式传递 state |

**注意**：`continue_conversation()` 只用最新的 `user_request` 做增量更新，不会重新读取全部历史原话。历史原话存在 `turn_history` 但当前未用于 RAG 查询。

---

## 7. RAG 层细节

### 离线入库（`1-rag_pipeline_delivery/`）
- 数据：`0-data/{city}/*.md`，YAML frontmatter + 正文
- 清洗 → 按 `📍` 切块（再 recursive char split，`CHUNK_SIZE=300`）
- 向量：OpenAI `text-embedding-3-small` 或本地 `BAAI/bge-small-zh-v1.5`
- 存储：ChromaDB（余弦距离）+ BM25Okapi pickle（jieba 分词）

### 在线检索（`2-rag-retrival/search_notes.py`）

```python
search_notes(query, city="", category="", strategy="hybrid", top_k=5)
# 返回 list[dict]，每条含 chunk_id / score / chunk_text / metadata
```

- `"hybrid"`（默认）：ChromaDB dense + BM25 → RRF 融合（dense_weight=0.6, bm25_weight=0.4）
- `"dense"`：纯向量
- `"filter"`：先 metadata 过滤再向量检索
- ChromaDB 不可用时自动退化为纯 BM25

### Agent 侧适配器（`3-travel_planner/.../strategy_rag_adapter.py`）
- 调用 `search_notes()` 后提取 `recommended_pois / theme_suggestions / local_pitfalls / neighborhood_notes`
- V7 新增：Evidence Layer（`_build_strategy_evidence()`）提取结构化证据：
  - `evidence_chunks` / `strategy_evidence_by_poi` / `strategy_evidence_by_district`
  - `poi_roles`（anchor/nearby_walk/food/optional_shop 等）
  - `route_pair_hints`（攻略明确连线的 POI 对）
  - `pitfall_evidence`（避坑证据）
- `_apply_content_type_quota()`：确保 route_plan 类≥2条、pitfall 类≥1条排在前列
- ChromaDB 不可用时回退本地 BM25

---

## 8. 关键数据模型（`models.py`）

```python
UserPreferences:  city, start_date, trip_days(1-14), travel_type, budget_level, pace, interests, must_visit, avoid
POI:              name, category, district, lat, lon, duration_hours, ticket_price, price_level, indoor_outdoor, tags, source
DayPlanItem:      time_slot, poi_name, category, district, est_cost, transport_hint, arrival_mode, distance_m, duration_min
DayPlan:          day_index, area, theme, estimated_cost, weather_summary, items, notes
ItineraryPlan:    selected_pois, days, planning_notes, local_tips, review_summary, review_findings
```

---

## 9. 城市支持

12 座城市（`data/city_profiles/` 各有 JSON）：
Beijing / Chengdu / Chongqing / Guangzhou / Hangzhou / Hong Kong / Nanjing / Shanghai / Shenzhen / Tokyo / Xiamen / Xian

中英文别名表在 `agent.py:CITY_ALIASES`（共 24 条映射）。

---

## 10. C 组接口（`4-cost/`）

| 函数 | 来源 | 说明 |
|---|---|---|
| `get_weather_api(city, dates)` | 高德天气 REST | |
| `estimate_cost_api(city, days, budget_level, user_budget)` | 静态 city×budget 费用表 | |
| `search_hotels_api(city, check_in, check_out, keyword, star_rate)` | Playwright 携程爬虫 | `ALLOW_MOCK_DATA=true` 可跳过 |

Agent 通过 `backend/WeatherCost/weather_cost_api.py` shim 调用，该 shim 只做 `sys.path` 注入，不修改 C 组代码。

---

## 11. 前端（`6-UI/`）

- `UI/chat.html`：主聊天界面，渲染 Markdown 报告 + 高德地图 + cost 卡片
- `map_UI/map.js`：高德 JS SDK，按天着色路线/POI 标记/折线
- `backend/server.py` 把 `6-UI/UI/` 挂载为 `/static`，`6-UI/map_UI/` 挂载为 `/static/map_UI`

---

## 12. 关键设计决策（不看代码猜不到）

| 决策 | 原因 |
|---|---|
| 不用 LangChain | 直接用 OpenAI Responses API function-calling，减少依赖 |
| 规划器是纯 Python 确定性代码 | 可复现、可审计，不依赖 LLM |
| 对话 state 只存内存 | 简化部署，重启清零是可接受的 trade-off |
| avoid 列表优先级高于 must_visit | 防止生成不安全/用户明确排斥的行程 |
| C 组代码用 shim 隔离 | 不改 C 组文件，靠 sys.path 注入集成 |
| 每个外部 API 都有本地 fallback | 支持完全离线运行（Amap/Nominatim/Tavily/ChromaDB/Playwright 全有降级） |
| `turn_history` 有但当前未用于 RAG | 历史原话的 RAG 拼接是待优化点（见下方待办） |

---

## 13. 评测体系现状

### 已完成
| 项目 | 状态 | 位置 |
|---|---|---|
| RAG 检索层 HR/MRR（V7） | ✅ HR=93.5%, MRR=0.98 | `rag/evaluate.py` |
| 在线 Tracing（Travel Planner） | ✅ eval_trace.jsonl | `backend/server.py` |
| 在线 Tracing（Companion Agent） | ✅ 真实 Token 统计 | `7-companion-agent/api.py` |
| Companion 测评流水线 | ✅ 30任务×rule模式已跑 | `5-evaluate/companion_eval_pipeline.py` |
| Companion 无 LLM 跑分结果 | ✅ strict=23.3%, rubric=50.1% | `5-evaluate/companion_eval_runs/` |
| RAGAS 评测代码 | ✅ 代码就绪 | `5-evaluate/ragas_evaluator.py` |
| 路线质量指标 | ✅ route_quality 字段 | `5-evaluate/ragas_evaluator.py` |

### 未完成
| 项目 | 说明 |
|---|---|
| RAGAS 生成质量评测 | 代码就绪但未实际运行（需 LLM Judge） |
| Golden Test Set | `golden_test_set.json` 未建 |
| 主 Agent 离线测试集 | `test_intent.py` / `test_e2e_structure.py` 等未建 |
| Companion LLM 全量跑分 | 30任务×4trials 未跑 |
| 主 Agent 综合评测 | 未做 |

### 主 Agent 迭代历史（6步优化）
| 步骤 | 内容 | 状态 |
|---|---|---|
| 1. RAG Evidence Layer | 结构化证据提取 | ✅ 已完成 |
| 2. POI 角色识别 | anchor/food/optional 分类 | ✅ 已完成 |
| 3. 路线聚类+跨区硬约束 | MAX_DISTRICTS_PER_DAY=3 | ✅ 已完成 |
| 4. 报告 evidence 输出 | guide_evidence/pitfall_note | ✅ 已完成 |
| 5. 多意图 Query + content_type 配额 | 避坑/本地人 query + 配额 | ✅ 已完成 |
| 6. ragas_evaluator 路线质量指标 | route_quality 字段 | ✅ 已完成 |

---

## 14. 待实现优化

1. **Companion Agent /api/companion 路由 404**：后端 server.py 有路由定义但实际未注册，疑似 import 时 companion_agent 依赖问题导致静默跳过。需排查。
2. **RAGAS 生成质量评测落地**：需构建 Golden Test Set 并实际运行 `ragas_evaluator.py`。
3. **主 Agent 离线测试集**：`test_intent.py` / `test_tool_access.py` / `test_e2e_structure.py` / `test_e2e_judge.py`。
4. **多轮 query 拼接**：`continue_conversation()` 里把 `turn_history` 拼接后再做 RAG 检索。
5. **意图切换检测**：检测城市/travel_type 根本性变化时清空 `preference_memory`。

---

## 15. 文件速查

| 要改什么 | 去哪个文件 |
|---|---|
| 意图提取/槽位识别逻辑 | `3-travel_planner/travel_planner/agent.py` → `_extract_user_profile()` / `_extract_profile_updates()` |
| 多轮对话合并逻辑 | `agent.py` → `_merge_preference_memory()` / `continue_conversation()` |
| RAG 检索策略 | `2-rag-retrival/search_notes.py` |
| RAG 结果→Agent 适配 | `3-travel_planner/travel_planner/tools/strategy_rag_adapter.py` |
| 行程规划算法 | `3-travel_planner/travel_planner/planner.py` |
| API 路由 | `backend/server.py` |
| 前端聊天界面 | `6-UI/UI/chat.html` |
| 地图渲染 | `6-UI/map_UI/map.js` |
| RAG 离线入库配置 | `1-rag_pipeline_delivery/rag/config.py` |
| 城市数据 | `3-travel_planner/travel_planner/data/city_profiles/{city}.json` |
| C组天气/费用/酒店 | `4-cost/Group_C/Group_C/c_group_weather_cost_api.py` |
| 陪伴 Agent 核心 | `7-companion-agent/companion_agent.py` |
| 陪伴 Agent 测评 | `5-evaluate/companion_eval_pipeline.py` |
| RAGAS 生成质量评测 | `5-evaluate/ragas_evaluator.py` |
| 评测设计文档 | `5-evaluate/eval_plan.md` |
| 主 Agent 迭代日记 | `5-evaluate/主agent迭代日记.md` |
| 步骤3/5/6实现规格 | `docs/superpowers/specs/2026-04-26-steps-3-5-6-design.md` |
