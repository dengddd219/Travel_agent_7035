# Travel Agent 7035 — 评测系统设计-美团龙猫

> 参考框架：《Agentic Design Patterns》理论体系 + 美团龙猫 VitaBench 工程实践。
> 从理论到落地，分离线测试和在线追踪两条线，覆盖传统工程指标和 Agent 特有指标。

---

## 零、当前做了什么

### 0.1 梳理现有评测状况

- 确认 `1-rag_pipeline_delivery/rag/evaluate.py` 已有检索层评测：**HR@5 = 84%，MRR = 1.00**
- 确认目前**没有** RAGAS 生成质量评测（Faithfulness、Answer Relevancy、Context Precision）
- 明确了本文档（`eval_plan.md`）中还有哪些评测尚未实现

---

### 0.2 实现在线 Tracing（Travel Planner Agent）

在 `backend/server.py` 和 `3-travel_planner/travel_planner/agent.py` 中实现了结构化日志落盘：

**`agent.py`**：在 `_execute()` 的 6 个工具调用处各加 `time.monotonic()` 计时，将每个工具的耗时存入 `tool_latencies` dict，并以特殊 log entry `_tool_latencies` 注入 `tool_logs`。

**`server.py`**：新增以下函数，在 `/api/chat` 端点记录完整 trace：

- `_estimate_tokens(text)`：字符估算 Token 数（中文字符 /1.5，英文 /4）
- `_write_eval_trace(record)`：非阻塞追加 JSON 行到 `eval_trace.jsonl`
- `_build_trace_record(...)`：组装结构化 trace 记录

端点用 `time.monotonic()` 包裹端到端延迟，从 `tool_logs` 提取 per-tool latencies，生成告警（延迟 >30s / 估算 Token >8000），写入 `5-evaluate/eval_trace.jsonl`。

> **注**：Travel Planner Agent 当前走确定性路径（无真实 LLM 调用），Token 数为字符估算值，trace 记录中 `token_usage.note` 字段注明 `"estimated from character count, not from API usage field"`。

---

### 0.3 实现真实 Token 统计（Companion Agent）

在 `7-companion-agent/` 的三个文件中实现了基于 API `usage` 字段的真实 Token 统计：

**`models.py`**：`AgentTurnResult` 新增 `token_usage: dict` 字段。

**`companion_agent.py`**：
- `_run_llm_turn`：while 循环每次 LLM 调用后累加 `response.usage.prompt_tokens` + `response.usage.completion_tokens`，并记录 `llm_call_count`（每轮对话最多 8 次循环，每次独立累加）
- `_run_fallback_turn`：统一返回全零 `token_usage`，标注 `"source": "fallback_no_llm"`

**`api.py`**：新增 `_write_companion_trace()`，在 `/api/companion` 端点计时、提取 `token_usage`、生成告警，写入同一个 `5-evaluate/eval_trace.jsonl`（通过 `"agent": "companion"` 字段与 Travel Planner 的记录区分）。

Companion Agent trace 记录格式示例：

```json
{
  "timestamp": "2026-04-25T10:00:00Z",
  "agent": "companion",
  "conversation_id": "...",
  "turn": 1,
  "intent": "search",
  "city": "北京",
  "latency_ms": {"total": 2500},
  "token_usage": {
    "input_tokens": 850,
    "output_tokens": 320,
    "total_tokens": 1170,
    "llm_call_count": 3,
    "model": "gpt-4o",
    "source": "api_usage_field"
  },
  "tool_call_count": 4,
  "alerts": []
}
```

---

## 一、评测总体思路

对 Agent 性能的评估，既需要传统工程里本来就有的指标（延迟、成本、A/B 测试），
又由于 Agent 的语义生成、概率性、长流程/工具使用等特性，需要新增或强化 Agent 特有指标
（响应质量、轨迹评估、RAG 系统评测）。

参考美团龙猫 VitaBench 的拆分方式，将评测维度归纳为三个正交维度：

```
推理维度  —— Agent 能否在信息不完备时整合线索并做出正确决策（意图理解、槽位提取）
工具维度  —— Agent 能否正确选择工具、满足前置条件、使用正确参数（工具调用轨迹）
交互维度  —— 多轮对话中能否识别模糊意图、维持上下文一致（多轮记忆合并）
```

落地上分两条线并行：

```
离线测试  —— 构建 JSON 测试集，跑确定性断言 + LLM-as-Judge，评响应质量和轨迹
在线追踪  —— 每次真实运行自动记录延迟、Token 消耗、工具调用顺序，写入结构化日志
```

---

## 二、离线测试

### 2.1 测试集设计（Golden Test Set）

文件：`golden_test_set.json`

每条 case 结构：

```json
{
  "id": "tc_001",
  "type": "standard_zh",
  "input": "我想去成都玩5天，喜欢美食，预算中等",
  "expected_profile": {
    "city": "Chengdu",
    "trip_days": 5,
    "budget_level": "medium",
    "travel_type": "leisure"
  },
  "expected_trajectory": {
    "tools_must_call": ["get_city_context", "get_strategy_context", "search_batch_pois", "get_weather_forecast", "get_cost_summary", "get_travel_tips"],
    "tool_order_constraints": [["get_city_context", "search_batch_pois"]],
    "tool_args_spot_check": {
      "get_cost_summary": {"budget_level": "medium", "days": 5},
      "get_weather_forecast": {"trip_days": 5}
    }
  },
  "expected_output": {
    "itinerary_day_count": 5,
    "must_visit_covered": [],
    "avoid_not_present": [],
    "report_keywords": ["成都", "川菜"],
    "min_report_length": 200
  }
}
```

覆盖场景（共 15 条）：

| 类型 | 条数 | 示例 |
|---|---|---|
| 标准中文短句 | 3 | "我想去成都玩5天，喜欢美食" |
| 英文结构化输入 | 2 | "City: Tokyo. Trip_days: 4. Budget: low" |
| 含 must_visit / avoid | 3 | "去香港3天，必去太平山，不去迪士尼" |
| 多轮修改（2 轮） | 3 | 第1轮正常规划，第2轮"把故宫换成颐和园" |
| 边缘情况 | 2 | 只说城市不说天数；城市名拼写变体 |
| 小众城市 | 2 | 厦门、南京 |

---

### 2.2 推理维度 — 意图理解与槽位提取

**对应 VitaBench：推理维度**（Agent 能否在信息不完备时整合线索并做出正确决策）

**测什么：**

当前 `_extract_user_profile()` 是正则+关键词实现，行为完全确定，用硬断言逐字段验证：

| 字段 | 测试场景 |
|---|---|
| `city` | 中文城市名（成都）、英文（Tokyo）、别名（港 → Hong Kong）、未提及（fallback HK）|
| `trip_days` | "5天"、"5-day"、"5 days"、未提及（default 3）|
| `budget_level` | "穷游/低预算" → budget、"奢华" → luxury、未提及 → medium |
| `travel_type` | "美食之旅" → leisure、"亲子游" → family、未提及 → leisure |
| `must_visit` | 结构化 clause "Must visit: 宽窄巷子"；内联提及"必去太平山" |
| `avoid` | "Avoid: 迪士尼"；"不去人多的地方" |

**多轮推理（`_merge_preference_memory`）：**

| 场景 | 预期行为 |
|---|---|
| 第1轮加景点，第2轮再加景点 | must_visit 合并去重 |
| 第1轮加景点，第2轮"去掉故宫" | must_visit 移除故宫 |
| must_visit 和 avoid 冲突 | avoid 优先，景点不出现在行程 |
| 第2轮换城市 | city 更新，旧城市 must_visit 不继承 |

**实现：** pytest，纯 Python，无 LLM，< 5s。

**通过标准：** 所有 case 硬断言 100% 通过。

---

### 2.3 工具维度 — 工具调用轨迹评估

**对应 VitaBench：工具维度**（正确选择工具 + 满足前置条件 + 使用正确参数）

参考美团龙猫的滑动窗评分思路：把每次 Agent 运行拆成若干工具调用步骤，按步骤核查，汇总命中率与失败归因。

#### 2.3.1 工具可访问性（Tool Access）

验证 Agent 在完整 query 下是否调用了所有必要工具，且每个工具都成功返回：

| 检查项 | 通过标准 |
|---|---|
| `tool_logs` 工具名集合 | 包含全部 6 个 LLM 工具（`get_city_context` / `get_strategy_context` / `search_batch_pois` / `get_weather_forecast` / `get_cost_summary` / `get_travel_tips`）|
| 每个工具返回 | 无 `"error"` key，返回 dict 非空 |
| `hotel_recommendations` | 非空（`get_hotel_candidates` 是确定性调用，不经 LLM，单独验证）|
| 调用轮次 | ≤ 8 轮，不触发上限 |
| 调用顺序 | `get_city_context` 出现在 `search_batch_pois` 之前 |

**工具命中率（Tool Hit Rate）：**

```
Tool Hit Rate = 实际调用工具数 / 预期必须调用工具数
目标：≥ 100%（6/6）
```

#### 2.3.2 工具参数正确性（Tool Arg Accuracy）

验证 LLM 传入工具的参数与用户意图是否一致。用 mock 拦截实际执行，只捕获 function_call arguments：

| 用户输入 | 被测工具 | 预期参数 | 匹配方式 |
|---|---|---|---|
| "去成都玩5天" | `get_weather_forecast` | `trip_days=5`, `city="Chengdu"` | 硬等于 |
| "预算低" | `get_cost_summary` | `budget_level="budget"` | 硬等于 |
| "必去宽窄巷子" | `search_batch_pois` | queries 含"宽窄巷子"语义 | 软匹配（in）|
| "亲子游" | `get_strategy_context` | `travel_type` 含 family 语义 | 软匹配 |
| "高端预算，上海" | `get_cost_summary` | `city="Shanghai"`, `budget_level="luxury"` | 硬等于 |

**参数准确率：**

```
Arg Accuracy = 正确参数字段数 / 总检查字段数
硬字段（city, days, budget_level）目标：100%
软字段（travel_type, queries）目标：≥ 80%
```

**失败归因：** 参数错误时，记录是 city 错、days 错还是 budget_level 错，便于定位是意图提取问题还是 LLM prompt 问题。

**实现：** `unittest.mock.patch` 替换 `tool_impls`，返回固定 stub，不调外部 API。

---

### 2.4 交互维度 — 响应质量评估

**对应 VitaBench：交互维度**（多轮上下文一致 + 识别模糊意图）

#### 2.4.1 结构检查（规则，无 LLM）

对每条 golden query 的 `ChatResponse` 做确定性断言：

| 检查项 | 验证方式 |
|---|---|
| `days` 数量 == `trip_days` | `len(days) == expected.trip_days` |
| must_visit 全覆盖 | 每个 must_visit POI 出现在某天 items |
| avoid 不出现 | avoid 列表里的 POI 不出现在任何 items |
| report 非空且达标长度 | `len(report) >= 200` |
| report 包含关键词 | expected_keywords 每项 in report |
| map_payload 有坐标 | pois 列表非空，lat/lon 非零 |
| hotel_recommendations 非空 | 至少 1 条酒店 |

#### 2.4.2 LLM-as-Judge 质量打分

参考《Agentic Design Patterns》的 LLM-as-Judge + Rubric 方法，对响应质量做细粒度结构化评分。

**评分维度（各 1-5 分）：**

| 维度 | 含义 | 对应 Agent 特性 |
|---|---|---|
| **相关性** | 行程是否符合用户意图（城市、天数、偏好全匹配）| 响应质量 |
| **完整性** | 报告是否覆盖景点/餐厅/交通/费用/天气 | 响应质量 |
| **地理连贯性** | 同一天路线是否合理，不跨区乱跳 | 推理质量 |
| **忠实性** | 内容是否有明显幻觉（不存在地名、错误信息）| RAG 忠实度 |

**Judge Prompt 输出格式（JSON）：**

```json
{
  "relevance": 4,
  "completeness": 3,
  "geo_coherence": 5,
  "faithfulness": 4,
  "hallucination_example": "无"
}
```

**通过标准：**

| 指标 | 阈值 |
|---|---|
| 4 维平均分 | ≥ 3.5 / 5 |
| 相关性 | ≥ 4.0 / 5 |
| 幻觉 case 占比 | ≤ 20% |

---

### 2.5 RAG 系统评测（已有，维护）

**对应：RAG 系统评测维度**（忠实度 + 相关性 + 可追溯性）

现有实现：`1-rag_pipeline_delivery/rag/evaluate.py`，40 条测试，Hit Rate@5 = 93.5%，MRR = 0.98。

维护策略：RAG 参数变动后回归跑一次，结果追加到 `evaluation_report.md`。

**回归基线：**

| 指标 | 基线 |
|---|---|
| Hit Rate@5 | ≥ 90% |
| MRR | ≥ 0.95 |

---

## 三、在线追踪

**对应传统工程指标：延迟 + 成本**

每次 Agent 运行（`start_conversation` / `continue_conversation`）自动采集以下数据，写入结构化日志文件 `eval_trace.jsonl`：

```json
{
  "timestamp": "2026-04-24T22:00:00Z",
  "conversation_id": "...",
  "turn": 1,
  "latency_ms": {
    "total": 8200,
    "per_tool": {
      "get_city_context": 120,
      "get_strategy_context": 1800,
      "search_batch_pois": 2100,
      "get_weather_forecast": 300,
      "get_cost_summary": 80,
      "get_travel_tips": 950
    }
  },
  "token_usage": {
    "input_tokens": 3200,
    "output_tokens": 1100,
    "total_tokens": 4300
  },
  "tool_call_count": 6,
  "tool_call_rounds": 4,
  "city": "Chengdu",
  "trip_days": 5
}
```

**监控阈值（告警触发条件）：**

| 指标 | 告警阈值 |
|---|---|
| 端到端延迟 | > 30s |
| 单次 Token 总消耗 | > 8000 tokens |
| 工具调用轮次 | = 8（触及上限，说明 LLM 可能陷入循环）|
| 工具调用失败 | 任意工具返回 `"error"` key |

---

## 四、A/B 测试（扩展）

**对应传统工程指标：A/B 测试**

对比两套配置的整体表现，使用 golden_test_set 中相同 query，并行跑两个版本，对比：

| 对比维度 | 指标 |
|---|---|
| 响应质量 | LLM-as-Judge 4 维平均分 |
| 延迟 | 端到端 P50 / P90 |
| 成本 | 平均 Token 消耗 |

计划对比的策略组合（举例）：

| Strategy | 配置 |
|---|---|
| A（Baseline） | RAG: hybrid（Dense + BM25）|
| B（优化版） | RAG: hybrid + Rerank，意图提取升级为 LLM 版 |

综合得分（参考现有 RAG 评测的加权思路）：

```
综合分 = 质量 × 40% + 延迟 × 30% + 成本 × 30%
（Min-Max 归一化后加权）
```

---

## 五、汇总矩阵

| 维度 | 对应理论框架 | 测试文件 | 依赖 LLM | 运行时间 | 触发时机 |
|---|---|---|---|---|---|
| 推理：意图提取 | Agentic DP：响应质量 | `test_intent.py` | 否 | < 5s | 改 agent.py |
| 推理：多轮合并 | VitaBench：交互维度 | `test_multiturn.py` | 否 | < 5s | 改 agent.py |
| 工具：可访问性 | VitaBench：工具维度 | `test_tool_access.py` | 是（mock tool）| ~30s | 改 build_tools / prompt |
| 工具：参数正确性 | VitaBench：工具维度 | `test_tool_args.py` | 是（mock tool）| ~60s | 改 prompt / schema |
| 交互：结构检查 | Agentic DP：响应质量 | `test_e2e_structure.py` | 是（全链路）| ~10min | 发布前 |
| 交互：LLM-as-Judge | Agentic DP：LLM-as-Judge | `test_e2e_judge.py` | 是（两次 LLM）| ~15min | 发布前 |
| RAG 检索 | Agentic DP：RAG 评测 | `rag/evaluate.py`（已有）| 否 | ~2min | 改 RAG 参数 |
| 在线追踪：延迟/Token | 传统工程：延迟/成本 | `eval_trace.jsonl`（运行时写入）| — | 实时 | 每次运行 |
| A/B 测试 | 传统工程：A/B | `test_ab.py` | 是 | ~30min | 策略变更后 |

---

## 六、文件结构

```
5-evaluate/
├── eval_plan.md                ← 本文件
├── golden_test_set.json        ← 15 条标准 query，含 expected_trajectory
├── test_intent.py              ← 推理维度：意图提取 + 多轮合并单测
├── test_tool_access.py         ← 工具维度：工具可访问性（mock）
├── test_tool_args.py           ← 工具维度：参数正确性（mock）
├── test_e2e_structure.py       ← 交互维度：端到端结构检查
├── test_e2e_judge.py           ← 交互维度：LLM-as-Judge 质量打分
├── test_ab.py                  ← A/B 策略对比
├── eval_trace.jsonl            ← 在线追踪日志（运行时自动追加）
└── eval_report.md              ← 每次离线测试结果汇总
```

---

## 七、注意事项

- **工具维度 mock 策略**：用 `unittest.mock.patch` 替换 `self.tool_impls` 里的函数，返回固定 stub，不调外部 API。只捕获 LLM 发出的 `function_call.arguments` 做断言。
- **LLM-as-Judge 模型**：与被评测 Agent 使用同一个 Azure OpenAI deployment，避免引入模型差异。
- **多轮测试**：需连续调用 `start_conversation` + `continue_conversation`，共享同一个 `ConversationState` 对象。
- **在线追踪**：`eval_trace.jsonl` 每条追加，不覆盖，便于历史趋势分析。
- **`expected_chunk_ids`** 在 golden_test_set 中暂时留空，RAG 层 hit_rate/MRR 回归依赖已有的 `rag/evaluate.py`，不重复。
