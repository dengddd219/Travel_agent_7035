# 意图识别模块 — 实现计划

> 定位：统一聊天入口的意图路由层，将用户输入分发给行前规划 Agent（3-travel_planner）或旅行中伴侣 Agent（7-companion-agent）。
> 参考方案：方案3（前置意图 RAG 召回）+ 方案4部分优化。

---

## 一、问题定义

### 为什么需要意图识别

当前系统有两个独立 Agent：

| Agent | 触发场景 | 核心输入 |
|---|---|---|
| Travel Planner（3-travel_planner） | 出发前，生成完整行程 | "我要去北京3天亲子游" |
| Companion Agent（7-companion-agent） | 旅行中，实时决策支持 | "我现在在故宫，老人走不动了" |

目标：在同一个聊天窗口，根据用户输入**自动路由**到正确的 Agent，用户无需切换界面或声明自己的意图类型。

### 意图边界

```
第一层路由（Agent 级别）
  ├── PLANNING   → Travel Planner
  └── COMPANION  → Companion Agent
       ├── TIME_SPACE    时空协调（"时间够吗"）
       ├── REPLANNING    异常重规划（"下雨了换个地方"）
       ├── NEARBY_SEARCH 周边搜索（"附近找个吃饭的"）
       └── EMERGENCY     应急响应（"老人走不动了"）
```

---

## 二、技术方案

### 总体策略：规则优先 + LLM 兜底（不做 RAG，理由见下）

**为什么不上 RAG 意图识别（方案3/4）：**
- 当前两个 Agent 边界清晰，规则可覆盖 90% 的 case
- Companion Agent 尚未实现，没有足够真实对话样本构建 RAG 知识库
- RAG 意图识别的价值在同一 Agent 内部的细分意图（Companion 的4个能力），而非跨 Agent 路由

**但保留方案3/4的核心思想，用于 Companion Agent 内部的细分意图识别（阶段2）。**

---

## 三、实现阶段

### 阶段1：轻量规则路由（当前优先实现）

#### 文件结构

```
8-intent-recognition/
├── PLAN.md                        ← 本文件
├── intent_router.py               ← 核心路由模块
└── tests/
    └── test_intent_router.py      ← 测试用例
```

同时修改：
```
backend/server.py                  ← 追加 /api/unified-chat 端点
6-UI/UI/chat.html                  ← （可选）统一入口 UI
```

#### `intent_router.py` 核心逻辑

```python
class IntentRouter:
    def route(self, user_input: str, session_context: dict) -> RouterResult:
        """
        Returns:
            RouterResult(
                agent="planning" | "companion",
                sub_intent=None | "time_space" | "replanning" | "nearby_search" | "emergency",
                confidence=0.0~1.0,
                method="rule" | "llm_fallback"
            )
        """
```

**规则信号词（中英文）：**

| 分类 | 触发词 | → 路由 |
|---|---|---|
| 当前位置锚点 | 我现在在/我在/刚到/正在 | companion |
| 时间可行性 | 时间够吗/来得及/几点必须走/多久能到 | companion → time_space |
| 异常重规划 | 下雨了/不想去了/临时换/关闭了/走不动/太累了 | companion → replanning |
| 周边搜索 | 附近/周边/找个/哪里有/推荐个/怎么去 | companion → nearby_search |
| 应急 | 走不动/腿疼/受伤/突发/紧急/最近的医院/最近的药店 | companion → emergency |
| 行前规划 | 计划去/想去/行程/规划/几天/推荐城市 | planning |

**会话上下文规则：**
- session 中已有 `current_location` → 默认 companion
- session 中已有完整 `itinerary_plan` 且用户问"现在" → companion
- 全新会话 + 无位置锚点 → planning

**LLM 兜底（规则无法判断时）：**

```
system: 你是旅行 AI 助手的意图分类器。
        用户可能在问旅行前的规划，也可能是旅行中的实时问题。
        返回 JSON: {"agent": "planning"|"companion", "reason": "..."}

user: [历史最近2轮] + [当前输入]
```

使用最便宜的模型（gpt-4o-mini / haiku），单次调用，不走工具循环。

---

### 阶段2：Companion 内部意图识别（方案3简化版）

**实现时机：Companion Agent 主体功能完成后。**

#### 知识库样例结构（存入 ChromaDB，复用现有 RAG 基础设施）

每条样例格式：

```json
{
  "chunk_id": "intent_example_time_space_001",
  "category": "intent_example",
  "intent": "time_space",
  "tag": "intent_classify",
  "history": "我在王府井吃完饭",
  "query": "下午还要去天安门和颐和园，时间够吗",
  "thought": "用户有明确的后续计划，需要路线时间推算",
  "slots": {"current_location": "王府井", "remaining_stops": ["天安门", "颐和园"]},
  "chunk_text": "[历史] 我在王府井吃完饭 [最新] 下午还要去天安门和颐和园，时间够吗"
}
```

`tag` 字段取值：
- `intent_classify` → 走意图识别逻辑
- `direct_answer` → 直接返回知识库内容，跳过 LLM 调用（用于 FAQ）

#### RAG 检索逻辑（方案4第2点）

```python
# 多轮拼接检索
recent_history = " ".join([t["content"] for t in turn_history[-2:]])
search_query = f"{recent_history} {current_input}"
hits = search_notes(search_query, category="intent_example", top_k=3)

# tag=direct_answer：直接返回
if hits and hits[0]["metadata"]["tag"] == "direct_answer":
    return DirectAnswerResult(content=hits[0]["chunk_text"])

# 其他：注入 Few-Shot prompt
few_shot_examples = format_examples(hits)
intent = llm_classify_with_few_shot(few_shot_examples, current_input)
```

#### 意图切换清空（方案4第4点）

```python
def detect_intent_switch(prev_intent: str, new_intent: str, session: CompanionState) -> bool:
    """检测是否发生了根本性意图切换"""
    switch_pairs = {
        ("time_space", "emergency"),
        ("nearby_search", "emergency"),
        ("replanning", "nearby_search"),
    }
    # city 切换 → 必然清空
    if session.city != new_city:
        return True
    return (prev_intent, new_intent) in switch_pairs

# 检测到切换时清空历史
if detect_intent_switch(prev, new, session):
    session.turn_history = []
    session.constraints = []
```

---

## 四、API 设计

### `POST /api/unified-chat`

**Request：**
```json
{
  "message": "我现在在故宫，老人走不动了",
  "conversation_id": "uuid",
  "conversation_state": {...},
  "session_context": {
    "current_location": "故宫",
    "city": "北京"
  }
}
```

**Response：**
```json
{
  "conversation_id": "uuid",
  "routed_to": "companion",
  "sub_intent": "emergency",
  "routing_method": "rule",
  "response": {...}
}
```

### 路由流程图

```
用户输入
    │
    ├─ 规则匹配（位置锚点/信号词/会话上下文）
    │      ├─ 匹配 confidence ≥ 0.8 → 直接路由
    │      └─ 匹配 confidence < 0.8 → LLM 兜底
    │
    ├─ 路由到 Planning → agent.start/continue_conversation()
    │
    └─ 路由到 Companion
           ├─ 细分意图识别（阶段2 RAG）
           └─ companion_agent.chat()
```

---

## 五、测试用例清单

| 输入 | 预期路由 | 预期子意图 |
|---|---|---|
| "帮我规划3天北京行程" | planning | — |
| "我要去上海，有什么推荐" | planning | — |
| "我现在在故宫，老人走不动了" | companion | emergency |
| "我在王府井，附近有什么好吃的" | companion | nearby_search |
| "下午还要去天安门，时间够吗" | companion | time_space |
| "下雨了，不想去天坛了" | companion | replanning |
| "北京有什么好玩的"（无位置锚点） | planning | — |
| "刚到颐和园，现在去长廊来得及吗" | companion | time_space |

---

## 六、实现优先级

| 优先级 | 任务 | 依赖 |
|---|---|---|
| P0 | `intent_router.py` 规则匹配核心 | 无 |
| P0 | `test_intent_router.py` 8个 case 全绿 | intent_router.py |
| P1 | `backend/server.py` 追加 `/api/unified-chat` | intent_router.py + companion_agent |
| P2 | Companion 内部意图识别（RAG Few-Shot） | Companion Agent 主体完成 |
| P3 | 意图切换清空逻辑 | P2 |

---

## 七、不做的边界

| 功能 | 原因 |
|---|---|
| 独立的意图识别 RAG 知识库（开发阶段） | 没有真实对话样本，现在构建收益低 |
| 用户显式声明模式切换按钮 | 破坏自然对话体验 |
| 跨 Agent 状态共享（行程传给 Companion） | 可选优化，不是 P0 |
| 意图置信度暴露给用户 | 内部实现细节，不需要展示 |
