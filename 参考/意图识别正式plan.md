# 意图识别四项优化 — 实施计划

> 本文件供下一个对话窗口直接接手使用。
> 每项优化都包含：背景 / 当前代码痛点 / Before vs After 对比 / 具体改动位置 / 验收标准。

---

## 背景：当前的"意图识别"是什么

项目里没有独立的"意图识别模块"，识别逻辑分散在 `agent.py` 的三个方法里：

| 方法 | 位置 | 作用 |
|---|---|---|
| `_extract_user_profile()` | agent.py:402 | 首轮：正则 + alias 表 → 槽位提取 |
| `_extract_profile_updates()` | agent.py:514 | 续轮：增量更新指令解析 |
| `_merge_preference_memory()` | agent.py:617 | 把增量更新合并进持久记忆 |

RAG 现在只用来召回**旅行笔记内容**（POI推荐、避坑等），
没有被用于辅助**意图识别本身**。

---

## 优化一：Few-shot 意图样例入库，RAG 动态注入 prompt

### 痛点

`_extract_user_profile()` 是纯正则，对模糊表达失效：
- "不要太赶，主要就是吃吃喝喝" → `travel_type` 识别为 `leisure`，应为 `food`
- "带孩子，预算不高，想轻松点" → `pace` 识别为 `balanced`，应为 `slow`

即使后续 LLM 工具调用能纠错，第一轮的 RAG 检索 query 已经偏了。

### Before（现状）

```
用户输入
  ↓
_extract_user_profile()  ← 纯正则+alias表，无上下文参考
  ↓
profile（可能有误）
  ↓
_build_strategy_queries()
  ↓
search_notes() ← 用错误的 profile 生成的 query 去检索
```

### After（目标）

```
用户输入
  ↓
search_notes(用户原话, category="intent_example", top_k=3)
  ↓ 召回最相似的历史意图样例（含 travel_type / budget / pace 等标注）
  ↓
把样例拼进 LLM prompt（few-shot）
  ↓
LLM 一次调用同时输出：意图分类 + 所有槽位
  ↓
profile（准确率显著提升）
```

### 具体改动

**Step 1：新建意图样例数据文件**

路径：`1-rag_pipeline_delivery/data/intent_examples/intent_examples.md`

每条样例格式（Markdown，YAML frontmatter）：
```markdown
---
title: "亲子慢节奏美食游"
content_type: intent_example
travel_type: food
budget_level: medium
pace: slow
city: 成都
---
历史提问：（无）
最新提问：带娃去成都，主要想吃好的，不要太赶，预算中等
思考过程：用户明确说"带娃"→亲子，"主要吃好的"→food，"不要太赶"→slow
意图：food
槽位：city=成都, travel_type=food, budget_level=medium, pace=slow, interests=[local food, family friendly]
```

建议覆盖场景：至少 20 条，覆盖 4×travel_type × 2×pace 的典型组合，
以及多轮切换、模糊表达、中英混用等 edge case。

**Step 2：修改 `ingest.py` 支持 intent_example 类型入库**

文件：`1-rag_pipeline_delivery/rag/ingest.py`

在 `run_ingest()` 里增加一个 intent 样例目录的入库分支：
```python
# 新增：intent 样例入库
INTENT_DIR = RAW_DATA_DIR.parent / "intent_examples"
if INTENT_DIR.exists():
    intent_chunks = ingest_city(INTENT_DIR, "intent_examples", dry_run=dry_run)
    all_chunks.extend(intent_chunks)
```

metadata 里需保证 `content_type="intent_example"` 字段，
供检索时用 `strategy="filter"` 精确过滤。

**Step 3：修改 `agent.py` 的意图提取流程**

文件：`3-travel_planner/travel_planner/agent.py`

新增方法 `_fetch_intent_examples(user_request, top_k=3)`：
```python
@staticmethod
def _fetch_intent_examples(user_request: str, top_k: int = 3) -> list[dict]:
    # 用用户原话去召回意图样例，category 过滤只取 intent_example
    results = _search_notes_via_rag(city="", query=user_request, top_k=top_k)
    return [r for r in results if r.get("metadata", {}).get("content_type") == "intent_example"]
```

修改 `_extract_user_profile()` 在有 LLM 的情况下，把召回样例拼进 prompt：
```python
examples_text = "\n\n".join(ex["chunk_text"] for ex in self._fetch_intent_examples(user_request))
# 拼到 system prompt 或第一轮 user message 里
```

### 验收标准

- "不要太赶，主要就是吃吃喝喝" → `travel_type=food, pace=slow` ✓
- 20条模糊表达测试集，意图准确率 ≥ 85%（当前基线约 60%）
- 未新增独立 LLM 调用（样例在现有工具调用循环内使用）

---

## 优化二：多轮对话 query 拼接后再做 RAG 检索

### 痛点

`continue_conversation()` 做 RAG 检索时，只用最新一轮的 `user_request`。
但 `search_notes()` 的 query 是从 `_build_strategy_queries(profile)` 重新构造的，
丢失了用户**历史原话**里的上下文信号。

示例：
- 第1轮："我想去香港"
- 第2轮："我喜欢吃东西"

第2轮单独去检索 → query 是 "Hong Kong local food"（从 profile 构造）。
但如果把两轮原话拼接 → query 变成 "我想去香港 + 我喜欢吃东西" → 能命中"香港美食攻略"类型的样例。

### Before（现状）

```python
# agent.py: continue_conversation()
# RAG query 来源：_build_strategy_queries(merged_profile)
# merged_profile 只含槽位值（city, travel_type...），不含用户原话
strategy_queries = self._build_strategy_queries(user_profile, city_context)
# → ["Hong Kong local food", "Hong Kong 3-day itinerary", ...]
```

历史原话存在 `turn_history`，但没有被传入 RAG。

### After（目标）

```python
# continue_conversation() 里增加：
context_query = self._build_context_query(state.turn_history, user_request, max_turns=3)
# → "我想去香港 我喜欢吃东西"（最近3轮用户原话拼接）

# 把 context_query 作为额外 query 插入检索列表
strategy_queries.insert(0, context_query)
```

### 具体改动

**文件：`3-travel_planner/travel_planner/agent.py`**

新增方法（约 10 行）：
```python
@staticmethod
def _build_context_query(turn_history: list[dict], current_request: str, max_turns: int = 3) -> str:
    """把最近 N 轮用户原话 + 当前 query 拼接，供多轮场景的 RAG 检索使用。"""
    recent_user_msgs = [
        turn["content"] for turn in turn_history[-max_turns:]
        if turn.get("role") == "user"
    ]
    recent_user_msgs.append(current_request)
    return " ".join(recent_user_msgs)
```

修改 `continue_conversation()` 里的 RAG 调用路径（约 5 行改动）：
```python
# 在 _build_strategy_queries() 之后，插入多轮 context query
if len(state.turn_history) > 0:
    context_query = self._build_context_query(state.turn_history, user_request)
    strategy_queries = [context_query] + strategy_queries  # 优先级最高
```

**注意**：`turn_history` 的每条格式是 `{"role": "user"/"assistant", "content": str}`，
在 `ConversationState`（agent.py:85）中已存在，不需要新字段。

### 验收标准

- 第1轮"去香港"，第2轮"吃东西" → RAG 能召回香港美食相关内容（不只是通用"local food"）
- 拼接后 query 长度不超过 200 字（`max_turns=3` 控制）
- 单轮对话场景（`turn_history` 为空）行为不变

---

## 优化三：知识库增加 `response_type` tag，命中后直接返回

### 痛点

所有请求都走完整 LLM 工具调用循环（≤8轮 × 每轮约 1-2s），
包括"香港需要签证吗"这类纯 FAQ，也要等 3-5 秒才能回答。

### Before（现状）

```
任意用户输入
  ↓
TravelPlanningAgent（LLM 工具调用循环，≤8轮）
  ↓ 约 3-5 秒
ChatResponse
```

### After（目标）

```
用户输入
  ↓
快速 RAG 检索（<200ms，无 LLM）
  ├─ 命中 response_type=direct_answer 且 score ≥ 0.85
  │     ↓
  │   直接返回知识库内容（跳过 LLM 循环）<500ms 总响应
  └─ 未命中 / 分数不够
        ↓
      TravelPlanningAgent（正常流程）
```

### 具体改动

**Step 1：新建 FAQ 数据文件**

路径：`1-rag_pipeline_delivery/data/faq/hongkong_faq.md`（按城市拆分）

样例格式：
```markdown
---
title: "香港签证FAQ"
content_type: faq
response_type: direct_answer
city: 香港
tags: [签证, 入境, 手续]
---
Q: 去香港需要签证吗？
A: 中国大陆居民前往香港需要持有效的港澳通行证（回乡证），无需额外签证。
通常可在口岸办理或提前预约，停留上限为7天/次（个人游签注）或30天（家庭团聚等）。
```

覆盖内容：签证/货币/天气/交通/习俗 等高频 FAQ，每城市约 15-20 条。

**Step 2：修改 `ingest.py` 支持 faq 类型入库**

与优化一的 intent_example 入库逻辑类似，增加 FAQ 目录扫描。

**Step 3：在 `backend/server.py` 的 `/api/chat` 入口增加快速检索分支**

```python
# backend/server.py: chat() 函数开头新增

from travel_planner.intent_router import try_direct_answer  # 新建模块

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # 优化三：FAQ 快速路径（新增，约 8 行）
    direct = try_direct_answer(req.message)
    if direct:
        return ChatResponse(
            conversation_id=store.create_empty(),
            conversation_state={},
            report=direct["answer"],
            itinerary_json={}, map_payload={},
            hotel_recommendations={}, tool_logs=[{"tool": "direct_answer", "source": direct["source"]}],
        )

    # 原有逻辑不变 ...
    agent = TravelPlanningAgent(settings=settings)
    ...
```

**Step 4：新建 `intent_router.py`**

路径：`3-travel_planner/travel_planner/intent_router.py`

```python
def try_direct_answer(user_message: str, score_threshold: float = 0.85) -> dict | None:
    """
    快速检索 FAQ 库。命中且分数 ≥ threshold 时返回 {answer, source}，否则返回 None。
    """
    results = _search_notes_via_rag(city="", query=user_message, top_k=1)
    if not results:
        return None
    top = results[0]
    if top["score"] >= score_threshold and top["metadata"].get("response_type") == "direct_answer":
        return {"answer": top["chunk_text"], "source": top["chunk_id"]}
    return None
```

### 验收标准

- "香港需要签证吗" → <500ms 响应，不进入 LLM 循环
- "帮我规划3天香港行程" → 分数不够，正常走 LLM 流程
- `tool_logs` 里有 `"tool": "direct_answer"` 标记，前端可区分展示

---

## 优化四：意图切换检测，自动清空历史 context

### 痛点

`ConversationState.preference_memory` 和 `turn_history` 只会累积，不会重置。
用户从"规划香港行程（city=Hong Kong, travel_type=leisure）"
切换到"推荐上海火锅（city=Shanghai, travel_type=food）"时：

- `preference_memory` 里残留 `must_visit=[Peak Tram, Star Ferry]`
- 这些会被带入新的 RAG query 和 planner，产生错误行程

### Before（现状）

```python
# agent.py: continue_conversation()
merged_profile = cls._merge_preference_memory(state.preference_memory, user_request)
# 不管用户是否切换了城市/旅行类型，永远都在旧 memory 上叠加
```

### After（目标）

```python
# 先检测是否发生意图切换
if cls._detect_intent_switch(state.preference_memory, user_request):
    # 清空旧 memory 和历史对话，以新开始的方式处理本轮
    state.preference_memory = {}
    state.turn_history = []
    # 走 start_conversation 路径
    return cls.start_conversation(user_request)

# 未切换：正常续轮
merged_profile = cls._merge_preference_memory(state.preference_memory, user_request)
```

### 具体改动

**文件：`3-travel_planner/travel_planner/agent.py`**

新增方法 `_detect_intent_switch()`（约 20 行）：

```python
@classmethod
def _detect_intent_switch(cls, preference_memory: dict, user_request: str) -> bool:
    """
    检测用户是否发生了根本性的意图切换。
    触发条件（满足任意一条）：
    1. 城市变了（旧 memory 有城市，新 request 提到不同城市）
    2. travel_type 发生跨类切换（如 leisure → food，family → theme）
    """
    if not preference_memory:
        return False

    # 条件1：城市切换
    old_city = preference_memory.get("city", "")
    new_city = cls._extract_explicit_city(user_request)
    if old_city and new_city and new_city.lower() != old_city.lower():
        return True

    # 条件2：travel_type 根本性切换
    old_type = preference_memory.get("travel_type", "")
    new_type = cls._find_alias_group(user_request.lower() + user_request, cls.TRAVEL_TYPE_ALIASES)
    INCOMPATIBLE_PAIRS = {
        ("leisure", "food"), ("food", "leisure"),
        ("family", "theme"), ("theme", "family"),
        ("food", "family"), ("family", "food"),
    }
    if old_type and new_type and (old_type, new_type) in INCOMPATIBLE_PAIRS:
        return True

    return False
```

修改 `continue_conversation()` 开头（约 8 行改动）：

```python
def continue_conversation(self, state: ConversationState, user_request: str) -> ConversationRunResult:
    # 优化四：意图切换检测（新增）
    if self._detect_intent_switch(state.preference_memory, user_request):
        # 清空旧状态，以全新对话处理本轮
        return self.start_conversation(user_request)

    # 原有逻辑不变 ...
    merged_profile = self._merge_preference_memory(state.preference_memory, user_request)
    ...
```

**可选增强**：在清空时记录切换日志，便于后续分析：
```python
state.intent_switch_log = state.intent_switch_log or []
state.intent_switch_log.append({
    "from": {"city": old_city, "type": old_type},
    "to": user_request[:100],
    "cleared_at_turn": len(state.turn_history),
})
```

### 验收标准

- 香港行程（leisure）→ "推荐上海火锅" → `preference_memory` 清空，全新规划上海
- 同一城市内的意图细化（"加上购物" / "去掉博物馆"）→ 不触发清空，正常累积
- 意图切换后的回复里，不包含上一轮城市的任何 POI 或建议

---

## 实施顺序建议

| 优先级 | 优化 | 原因 |
|---|---|---|
| 1 | **优化四**（意图切换检测） | 改动最小（仅 ~28 行），收益直接，无需新数据 |
| 2 | **优化二**（多轮 query 拼接） | 改动约 15 行，数据已在 `turn_history`，无需新文件 |
| 3 | **优化一**（Few-shot 样例入库） | 需要手工标注 20+ 样例，有数据准备成本 |
| 4 | **优化三**（FAQ 直接返回） | 需要手工整理 FAQ + 新增模块，改动面最广 |

优化一和四可以**并行进行**（数据准备和代码改动互不阻塞）。

---

## 文件改动总览

| 文件 | 优化一 | 优化二 | 优化三 | 优化四 |
|---|---|---|---|---|
| `agent.py` | ✎ 新增 `_fetch_intent_examples()` | ✎ 新增 `_build_context_query()`，修改续轮路径 | — | ✎ 新增 `_detect_intent_switch()`，修改 `continue_conversation()` |
| `backend/server.py` | — | — | ✎ 新增快速路径 8 行 | — |
| `1-rag_pipeline_delivery/rag/ingest.py` | ✎ 增加 intent_example 目录扫描 | — | ✎ 增加 faq 目录扫描 | — |
| `data/intent_examples/*.md` | ✚ 新建（20+ 条样例） | — | — | — |
| `data/faq/*.md` | — | — | ✚ 新建（每城市 15-20 条） | — |
| `travel_planner/intent_router.py` | — | — | ✚ 新建 | — |
| `ConversationState`（agent.py:77） | — | — | — | ✎ 可选加 `intent_switch_log` 字段 |

---

## 效果对比预期

| 场景 | 优化前 | 优化后 |
|---|---|---|
| "不要太赶，主要就是吃吃喝喝" | `travel_type=leisure`（误） | `travel_type=food, pace=slow`（正） |
| 第2轮"加上吃的" 的 RAG 命中 | 通用 food 内容 | 精准命中该城市美食笔记 |
| "香港需要签证吗" 响应时间 | 3-5秒（LLM循环） | <500ms（直接返回FAQ） |
| 从香港行程切换问上海火锅 | 行程混入 Peak Tram 等香港POI | 干净的上海规划 |
