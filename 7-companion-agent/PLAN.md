# 旅行伴侣 Agent — 产品与实现计划

> 定位：旅行**中**的实时 AI 伴侣，与同事的旅行**前**规划 Agent 形成完整闭环。
> 参考：VitaBench（美团龙猫团队）OTA 场景 Agent 设计。

---

## 零、总而言之

这个 Agent 不是一个“会聊天的地图搜索框”，而是一个**旅行中实时决策系统**。  
它的目标不是一次性产出完整大行程，而是在用户已经出发、已经在路上、情况随时变化时，持续根据**当前位置、当前时间、同行人约束、剩余计划、天气与突发事件**做即时判断。

一句话概括：

> **LLM 负责理解问题、选择工具、组织回复；确定性逻辑负责排序、时间推算和规则约束；外部 API 负责提供实时世界信息。**
>
当前还不能直接算真正商业级 OTA Agent，主要还差稳定性、观测、缓存、fallback、评测、数据增强和安全边界

### 0.1 这个 Agent 的总体框架

```text
┌────────────────────────────────────────────────────────────────────┐
│                           User / Frontend                         │
│   用户输入：我现在在哪、要去哪、同行人情况、突发问题、即时需求        │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ HTTP /api/companion
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Companion Agent Orchestrator                   │
│  1. 读取/更新状态                                                  │
│  2. 理解意图（查询/规划/异常/应急）                               │
│  3. 决定调用哪些工具                                               │
│  4. 多轮 function calling                                          │
│  5. 汇总结果并生成最终回复                                          │
└───────────────┬───────────────────────────────┬────────────────────┘
                │                               │
                │ 调用工具                       │ 读取/写入状态
                ▼                               ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│         Tool Router            │   │       CompanionState          │
│  按 tool name 路由到具体实现    │   │ 位置、时间、同行人、约束、计划  │
│  统一处理参数、异常、返回格式    │   │ 历史对话、天气快照、酒店基点等  │
└───────┬─────────────┬──────────┘   └───────────────────────────────┘
        │             │
        │             ├───────────────────────────────────────┐
        ▼                                                     ▼
┌───────────────────────────────┐      ┌────────────────────────────────┐
│   Deterministic Decision Layer │      │       External Data Layer       │
│  score_candidates              │      │ 高德路线 / POI / 地理编码       │
│  check_time_feasibility        │      │ 当天天气 API                    │
│  resolve_emergency_resources   │      │ 北京景区 mock 数据              │
│  规则、打分、排序、时间反推      │      │ 实时世界信息                    │
└───────────────────────────────┘      └────────────────────────────────┘
```

### 0.2 它能干的事情

这个 Agent 当前应该聚焦在 4 类能力：

1. **时空协调**
   用户给出“我现在在哪里、接下来还要去哪”，Agent 计算路线、时间线、最晚出发时间、是否来得及。

2. **异常重规划**
   旅行中出现下雨、景点关闭、排队过长、老人走不动、孩子累了等情况时，Agent 能把原本计划重排成一个新的可执行方案。

3. **上下文感知推荐**
   它不是只给附近列表，而是结合预算、口味、同行人、后续安排、步行成本，给出**排序后的候选**和理由。

4. **实时应急响应**
   当用户处在慌乱场景中时，Agent 一次性返回多个解决方向，例如医疗、如厕、撤离、补能、回酒店、求助点。

### 0.3 它不能干的事情

为了保证可实现性，这个版本不应该承诺以下能力：

- 不做景区内部精细导航。
- 不做电话外呼与线下确认。
- 不做餐厅/门票交易闭环。
- 不做多日天气驱动的复杂中长期调度。
- 不承诺全国任意景区内部设施都能精准命中。

也就是说，它应该是一个**“当天旅行实时助手”**，不是一个万能 OTA 超级应用。

### 0.4 它的工具分层

这个 Agent 最重要的不是“工具数量多”，而是“工具职责清楚”。建议分成 5 层：

| 层级 | 工具/模块 | 负责什么 | 谁来调用 |
|---|---|---|---|
| 入口层 | `/api/companion` | 接收用户请求，恢复会话状态，返回结果 | Frontend / Backend |
| 编排层 | `companion_agent.py` | 意图识别、工具选择、多轮 function calling、生成答复 | Agent Orchestrator |
| 路由层 | `tool_impls` / `_run_tool_call` | 把工具名映射到 Python 函数 | Agent Orchestrator |
| 决策层 | `score_candidates`、`check_time_feasibility`、`resolve_emergency_resources` | 做排序、打分、时间线、规则判断 | Tool Router 调用 |
| 数据层 | 高德 API / 天气 API / mock 数据 | 提供实时路线、POI、天气、景区属性 | 各具体工具函数 |

### 0.5 每个工具是谁负责调用、谁负责执行

这个链路建议明确分工：

| 环节 | 负责人 | 作用 |
|---|---|---|
| 发起请求 | Frontend / 用户 | 提供自然语言问题 |
| 进入系统 | Backend API | 把请求交给 Agent，并加载会话状态 |
| 决定调什么工具 | LLM Orchestrator | 判断当前是查询、规划、异常还是应急 |
| 真正执行工具 | Python Tool Functions | 发起高德/天气请求，或做本地打分和计算 |
| 做规则计算 | Deterministic Layer | 排序、时间反推、路线校正、兜底 |
| 组织最后输出 | LLM Orchestrator | 把工具结果整理成对用户可读的话 |

换句话说：

- **谁负责调用工具？** Agent Orchestrator（LLM 主循环）
- **谁负责执行工具？** Python 工具函数
- **谁负责“判断哪个更好”？** 确定性打分逻辑，不应该交给 LLM 主观决定
- **谁负责最终回复的自然语言表达？** LLM

### 0.6 工具调用逻辑

建议这个 Agent 的标准调用链如下：

```text
用户输入
  → 读取当前状态
  → LLM 判断意图类型
  → 选择工具
  → Tool Router 执行工具
  → 得到候选结果
  → 确定性逻辑做排序/时间推算/路线校正
  → 如有必要继续补调用下一轮工具
  → LLM 组织最终回复
  → 写回新状态
```

再细一点，可以拆成这几步：

1. 用户说一句自然语言。
2. Agent 先判断这是“普通查找”“时间协调”“异常重排”还是“应急”。
3. 如果涉及地点，先 `resolve_location`。
4. 如果涉及找地方，先 `retrieve_candidates` 做文本召回。
5. 对召回结果做 `score_candidates`。
6. 对前几名候选补 `get_route`，完成路线校正。
7. 如果涉及景区开放时间、无障碍、门票等，再补 `get_poi_detail`。
8. 如果涉及天气变化，再调 `get_weather_now`。
9. 如果是应急场景，优先走 `resolve_emergency_resources` 聚合逻辑。
10. 最后由 LLM 用用户能看懂的话输出结果。

### 0.7 一个更接近工程实现的运行框架

```text
User
  ↓
Frontend companion.html
  ↓
Backend /api/companion
  ↓
load_state(conversation_id)
  ↓
CompanionAgent.run_turn()
  ├─ classify_intent()
  ├─ decide_tool_plan()
  ├─ loop:
  │    ├─ LLM emits function_call(s)
  │    ├─ Tool Router dispatches
  │    ├─ tool function executes
  │    └─ outputs returned to LLM
  ├─ deterministic post-process
  │    ├─ scoring
  │    ├─ route validation
  │    └─ time feasibility
  ├─ finalize_answer()
  └─ update_state()
  ↓
return response + updated state
```

### 0.8 要做到“近似商业级别”，还差哪些东西

**结论先说：**

- 作为**北京场景、旅行当天、有限范围的演示型 Agent**，这套架构可以做到接近商业 Demo。
- 作为**真正可上线、稳定服务大量用户的商业级 Agent**，当前 plan 还不够。

更准确地说，这套方案有机会达到：

| 水平 | 评价 |
|---|---|
| Demo 级 | 可以达到 |
| 校内项目 / 课程项目优秀水平 | 可以达到 |
| 小范围灰度试运行 | 需要补工程能力 |
| 真正商业级 OTA 实时 Agent | 目前还差不少 |

### 0.9 离商业级还差的核心能力

如果要接近商业级，不只是“功能写出来”，还要补这些：

1. **稳定性**
   所有外部工具都要有 timeout、retry、fallback，不然高德一超时整条链路就断。

2. **可观测性**
   要记录每次 tool call、耗时、失败率、命中率、推荐采纳率。

3. **缓存与成本控制**
   高频地点、热门景区、常用路线要缓存，避免每轮都打外部 API。

4. **安全与边界控制**
   医疗、紧急、儿童、老人场景要有更保守的回复模板，不能乱给危险建议。

5. **Prompt 与工具治理**
   需要 prompt 版本管理、工具 schema 管理、回归测试，而不是手改 system prompt。

6. **评测体系**
   要构建旅行中场景集，评估路线准确率、推荐合理性、应急响应命中率。

7. **数据层增强**
   仅靠高德通用 POI 不够，景区内设施、营业时间、无障碍信息最好要有专项数据。

8. **用户状态建模**
   商业级系统不会只存字符串 history，而会存结构化 profile、动态偏好和上下文快照。

### 0.10 因此，这个 Agent 应该如何定义自己

最合理的产品定义不是：

> “一个万能旅行 Agent，什么都能做。”

而应该是：

> **一个面向旅行当天的、可多轮对话的、具备实时路线判断、约束排序、异常重排和应急响应能力的 Companion Agent。**

这个定义是收敛的、可做的，而且比“万能助手”更接近商业产品真实形态。

---

## 一、产品定位

### 和现有规划 Agent 的区别

| | 同事的规划 Agent | 本 Agent |
|---|---|---|
| 触发时机 | 出发前，一次性生成 | 旅行中，随时对话 |
| 核心输入 | "我要去北京3天亲子游" | "我现在在故宫，老人走不动了" |
| 核心输出 | 完整行程 + 地图 | 即时决策 + 重规划 |
| 工具类型 | RAG + 批量POI + 静态费用 | 实时高德 API + 动态推算 |

### 和用户自己用大众点评/高德的区别

大众点评能推荐餐厅，高德能查路线，但两者都做不到：

- 知道你有老人+小孩+不吃辣+2点要赶路，综合所有约束给出优先级最高的5个候选
- 知道你3点要到颐和园，反推你现在最晚几点必须离开餐厅
- 下雨了主动帮你把室外景点换成室内，重新排好顺序

**Agent 的核心价值：跨步骤的约束协调，不是单点信息查询。**

---

## 二、核心能力（4个）

### 能力1：时空协调

用户给出当前位置 + 后续计划，Agent 实时推算时间可行性，给出最优路径。

**典型对话：**
> 用户："我在王府井吃完饭，下午还要去天安门和颐和园，来得及吗？"
>
> Agent：查路线（王府井→天安门12分钟，天安门→颐和园38分钟）
> → 推算时间线：13:30出发，14:42到天安门，15:20到颐和园
> → 颐和园17:00关门，时间紧但可行
> → 给出警告："颐和园只有1小时40分钟，建议直奔昆明湖+长廊"

**技术实现：**
- 高德路线规划 API（真实行驶时间）
- 纯 Python 时间推算（不走 LLM）
- Mock 景区关门时间数据库

---

### 能力2：计划异常处理

突发状况（下雨/景点关闭/排队太长/体力不支）→ Agent 根据当前状态重新安排剩余行程。

**典型对话：**
> 用户："下雨了，我们不想去天坛了，还有什么可以去？"
>
> Agent：知道当前位置 + 剩余时间 + 天气
> → 过滤掉室外景点
> → 推荐附近室内替代（国家博物馆/首都博物馆/商场）
> → 重新推算时间是否够用

**技术实现：**
- 天气 API（复用 C 组，只用于旅行当天/近实时判断）
- 高德周边搜索（关键词"室内+博物馆"）
- 重新调用时空推算逻辑

---

### 能力3：上下文感知的周边搜索

不是简单的"附近餐厅列表"，而是在知道用户全部约束后给出排序后的5个优先候选。

**典型对话：**
> 用户："我在王府井，逛了一上午累死了，找个吃饭的，小孩不吃辣，我们不喜欢北京菜，预算高一点"
>
> Agent：
> - 当前位置 → 坐标
> - 周边搜索 → 过滤川菜/湘菜/北京菜，筛选¥¥¥
> - 结合时间约束（下午还要去哪）→ 排序后推荐5家
> - 给出：名字 + 步行距离 + 菜系 + 人均 + 联系电话 + 为什么排第一

**技术实现：**
- 高德地理编码（地址→坐标）
- 文本召回 + 约束打分 + 路线校正，而不是单次 nearby 黑盒搜索
- LLM 推断隐含约束（"不喜欢北京菜" → 排除哪些菜系）

---

### 能力4：实时应急响应

突发情况用户最慌，需要多条信息同时返回，而不是让用户一个个搜。

**典型对话：**
> 用户："老人突然腿疼走不动了，我们在颐和园里面"
>
> Agent 同时返回：
> - 最近的景区内休息区在哪（步行X分钟）
> - 附近最近的药店（出景区后XX米）
> - 打车回酒店：预计XX分钟，约XX元
> - 剩余家人可以继续逛的路线建议

**技术实现：**
- 不直接依赖单个关键词，而是先识别应急场景，再映射到一组场所类型和搜索词
- 高德路线规划（回酒店时间+费用估算）
- 并行工具调用（多个信息同时获取）

**应急场景 → 解决场所示例：**

| 应急场景 | 优先解决场所 | 可尝试搜索词 |
|---|---|---|
| 受伤/摔倒/腿疼 | 医务室、医院、药店、休息点、最近出口 | "医务室"、"医院"、"药店"、"休息区"、"出口" |
| 尿急/小孩急需厕所 | 卫生间、母婴室、游客中心、商场 | "卫生间"、"厕所"、"母婴室"、"游客中心" |
| 手机没电/需要联系同伴 | 共享充电宝点、便利店、咖啡店、商场服务台 | "充电宝"、"便利店"、"咖啡店"、"服务台" |
| 急需稳定网络/临时上网 | 网吧、咖啡店、商场、营业厅 | "网吧"、"上网"、"咖啡店"、"营业厅" |
| 走散/迷路/需要求助 | 游客中心、保安亭、派出所、地铁站、车站 | "游客中心"、"保安亭"、"派出所"、"地铁站"、"车站" |
| 赶时间撤离 | 最近出口、地铁站、出租车上车点、车站 | "出口"、"地铁站"、"打车点"、"车站" |

**应急检索策略：**
1. 先把用户描述归类为场景：医疗、如厕、补能、网络、求助、撤离。
2. 针对场景展开多组搜索词，而不是只搜一个词。
3. 先做文本召回，再按距离/可达性/是否出景区打分。
4. 对排名靠前的候选再补路线校正，给出真实步行或打车时间。
5. 如果地图数据缺失，就降级为"最近出口 + 景区外通用资源 + 安全建议"的保守回复。

---

## 三、技术架构

### 文件结构

```
7-companion-agent/
├── PLAN.md                    ← 本文件
├── companion_agent.py         ← 主 Agent（工具循环 + 时间推算）
├── models.py                  ← CompanionState 数据结构
└── tools/
    ├── __init__.py
    ├── amap.py                ← 高德 API（geocode / 周边 / 路线）
    ├── weather.py             ← 复用 C 组天气，薄包装
    └── mock_data.py           ← 北京景区数据库（开放时间/门票/无障碍）

backend/server.py              ← 追加 /api/companion 端点
6-UI/UI/companion.html         ← 新聊天界面（复用 chat.html 样式）
```

### 工具清单（Agent-facing）

| 工具 | 职责 | 实现细节 | 真实/Mock |
|---|---|---|
| `resolve_location(query)` | 把地点名/地址解析成结构化位置 | 高德 geocode / place text，补充别名归一化 | 真实 |
| `retrieve_candidates(query, city, current_location)` | 文本召回候选 POI | 组合搜索词，不直接等同于 nearby | 真实 |
| `score_candidates(candidates, context)` | 按约束排序候选 | 距离、预算、菜系、剩余时间、老人/儿童约束做确定性打分 | 纯逻辑 |
| `get_route(origin, dest, mode)` | 获取步行/打车时间与距离 | 高德路线规划 API | 真实 |
| `get_poi_detail(name)` | 获取开放时间/门票/无障碍等静态属性 | 北京景区 mock 数据库 | Mock |
| `get_weather_now(city)` | 获取旅行当天近实时天气 | 复用 C 组天气，只覆盖当天决策 | 真实 |
| `check_time_feasibility(current_time, stops)` | 做时间线推算与最晚出发时间反推 | 纯 Python 计算 | 纯逻辑 |
| `resolve_emergency_resources(scene, location, base_location)` | 聚合应急结果 | 场景识别 → 文本召回 → 打分 → 路线校正 → 安全兜底 | 混合 |

### `retrieve_candidates` 的内部三层

`retrieve_candidates` 不是一个黑盒 nearby，而是拆成三层：

1. **文本召回**：用"当前位置/景区名/城区 + 需求词"展开多组 query，例如 `"王府井 餐厅"`、`"颐和园 药店"`、`"故宫 卫生间"`。
2. **坐标打分**：对召回结果按直线距离、行政区一致性、类型匹配、预算/菜系/室内外标签做初筛。
3. **路线校正**：只对前几名候选补查真实路线，避免把"看起来近、实际绕很远"的点排前面。

这样做的原因是：很多旅行中问题不是"附近有什么"，而是"什么最适合当前约束，且真的来得及去"。

### 多轮对话状态

```python
CompanionState:
    city: str                  # "北京"
    current_location: str      # "王府井大街"
    current_coords: tuple      # (39.914, 116.407)
    current_time: str          # "2026-04-25T14:10:00+08:00"
    location_updated_at: str   # 当前位置更新时间，避免用过期定位
    base_location: str         # 酒店/民宿/集合点，便于应急回撤
    party: dict                # {"adults":2, "elderly":1, "children":1}
    confirmed_constraints: list[str]   # 用户明确说过的硬约束
    inferred_constraints: list[str]    # Agent 推断出的软约束，需和 confirmed 区分
    mobility_state: dict       # {"elderly_needs_rest": True, "wheelchair_needed": False}
    remaining_plan: list[dict] # [{"name":"颐和园","must_arrive_by":"15:00"}]
    destination_deadlines: list[dict]  # [{"name":"颐和园","latest_arrival":"15:00"}]
    weather_snapshot: dict     # 当天最近一次天气结果
    active_orders: list[dict]  # 已确认的安排
    turn_history: list[dict]   # 多轮对话记录
```

### 状态设计注意点

- 不要把"用户确认"和"模型推断"混在一个 `constraints` 里，否则后面会出现误判。
- `current_location` 必须带更新时间，否则旅行中多走几百米就可能导致推荐失真。
- `remaining_plan` 不应只是字符串列表，最好带 `must_visit`、`latest_arrival`、`priority`。
- 应急能力依赖 `base_location`，否则"回酒店/回集合点"无法稳定计算。
- `mobility_state` 是动态变量，不应只靠最初用户画像一次性写死。

### Agent 主循环

```
用户输入
  → 意图分类（查询/规划/异常/应急）
  → 决定并行调用哪些工具
  → 执行工具（最多6轮）
  → 对候选做确定性打分与时间推算
  → 组织回复
```

---

## 四、和论文（VitaBench）的对应关系

| VitaBench 设计 | 本 Agent 对应实现 |
|---|---|
| 隐含约束推断（"三代同堂"→无障碍+亲子） | LLM 推断，但与 confirmed constraints 分开存储 |
| 并行工具调用 | OpenAI function calling 原生支持 |
| 时间/空间精确推算 | 纯 Python + 高德真实路线结果 |
| 跨域协调（一句话触发多个工具链） | 能力1+2+4 均体现 |
| 主动补充用户未问的信息 | 能力4（应急时一次返回全部） |

---

## 五、演示场景（验收标准）

**场景：北京，家庭游（2大人+1老人+1小孩），上午**

```
Turn 1: "我在王府井，逛了一上午，找个午饭，小孩不吃辣，不喜欢北京菜，预算高"
  → 能力3：文本召回 + 约束打分 + 路线校正 → 推荐2家 + 排序理由 + 电话

Turn 2: "下午还要去天安门和颐和园，时间够吗"
  → 能力1：路线推算 + 时间线 + 风险提示

Turn 3: "下午突然下雨了，天安门广场不想淋雨，能换吗"
  → 能力2：异常处理 → 推荐附近室内替代 + 重新推算时间

Turn 4: "老人在颐和园走不动了"
  → 能力4：应急响应 → 休息点/出口 + 药店 + 打车回酒店，并行返回
```

---

## 六、参考代码复用指南

> 路径：`参考/3.chatbot/`、`参考/5.agents/`、`参考/8.multi-agent/`

---

### 复用1：多轮对话状态管理

**来源：** `参考/3.chatbot/chatbot_simple.py` 的 `Chatbot` 类

这是最干净的多轮对话骨架，直接告诉你怎么维护 `conversation_history`：

```python
# 每次对话的消息拼装方式
messages = [{"role": "system", "content": self.system_message}]
messages.extend(self.conversation_history)        # 历史消息
messages.append({"role": "user", "content": user_input})  # 新消息

# 收到回复后，把这一轮追加到历史
self.conversation_history.append({"role": "user", "content": user_input})
self.conversation_history.append({"role": "assistant", "content": reply})
```

**怎么用进你的框架：**
`CompanionState.turn_history` 就是这里的 `conversation_history`，每轮对话追加进去，下次对话时拼在 messages 前面传给 LLM。

---

### 复用2：工具调用循环（最重要）

**来源：** `参考/5.agents/agent_function_calling_v2.py` 的 while 循环

这是你的 Agent 工具调用的核心结构，必须用循环，不能只处理一次：

```python
# 标准工具调用循环，每轮直到没有 function_call 为止
while True:
    pending_calls = [item for item in response.output if item.type == "function_call"]
    if not pending_calls:
        break
    tool_outputs = []
    for item in pending_calls:
        result = _run_tool_call(item)   # 路由到对应工具函数
        tool_outputs.append({
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": result
        })
    # 把所有工具结果一起发回给 LLM，继续下一轮
    response = openai_client.responses.create(input=tool_outputs, ...)
```

**怎么用进你的框架：**
`companion_agent.py` 的主循环直接照这个写，把 `_run_tool_call` 替换成你的工具路由函数（resolve_location / retrieve_candidates / score_candidates / get_route / get_weather_now / get_poi_detail / resolve_emergency_resources）。

---

### 复用3：工具路由字典

**来源：** `参考/5.agents/agent_function_call_db.py` 的 `tool_impls` 字典

避免写一堆 `if tool_name == "xxx"` 的判断链，改用字典映射：

```python
# 定义所有工具的实现函数
tool_impls = {
    "resolve_location":    resolve_location,
    "retrieve_candidates": retrieve_candidates,
    "score_candidates":    score_candidates,
    "get_route":           get_route,
    "get_poi_detail":      get_poi_detail,
    "get_weather_now":     get_weather_now,
    "resolve_emergency_resources": resolve_emergency_resources,
}

# 路由时直接查字典
def _run_tool_call(item):
    fn = tool_impls[item.name]
    args = json.loads(item.arguments)
    return json.dumps(fn(**args), ensure_ascii=False)
```

**怎么用进你的框架：**
`companion_agent.py` 里照这个写，新增工具只需要在字典里加一行，不用改主循环；其中 `resolve_emergency_resources` 可以作为能力4的聚合工具，避免让 LLM 亲自拼太多细碎查询。

---

### 复用4：并发查询多数据源

**来源：** `参考/8.multi-agent/concurrent_custom_aggregator.py`

应急响应（能力4）需要同时查多个信息——出口/休息点、药店、打车路线。LLM 的 function calling 本身支持并行调用，但 multi-agent 里还有更明确的并发模式：

```python
# 三个查询同时触发（LLM 一次返回多个 tool_call）
# Agent 会在一次 response.output 里返回：
[
    {"type": "function_call", "name": "retrieve_candidates", "arguments": {"query": "颐和园 休息区"}},
    {"type": "function_call", "name": "retrieve_candidates", "arguments": {"query": "颐和园 药店"}},
    {"type": "function_call", "name": "get_route",     "arguments": {"dest": "酒店"}},
]
# 你的代码同时执行这三个，统一收集结果再发回
```

**怎么用进你的框架：**
System prompt 里明确告诉 LLM "应急情况时，同时调用多组候选召回与路线工具"，LLM 会自动并行发出。复用2的 while 循环会把这些并行结果统一处理；如果实现了 `resolve_emergency_resources`，则可以优先调聚合工具，减少 LLM 规划负担。

---

### 复用5：Handoff 路由模式（可选，进阶）

**来源：** `参考/8.multi-agent/handoff_simple.py`

如果4个能力之间的切换逻辑变得复杂，可以升级为 Handoff 架构：

```
Triage Agent（判断用户意图）
    ├── 能力1：时空协调 Agent
    ├── 能力2：异常处理 Agent
    ├── 能力3：周边搜索 Agent
    └── 能力4：应急响应 Agent
```

```python
workflow = (
    HandoffBuilder(
        participants=[triage, spatial_agent, replanning_agent, search_agent, emergency_agent],
        termination_condition=lambda conv: conv[-1].role == "assistant",
    )
    .with_start_agent(triage)
    .build()
)
```

**怎么用进你的框架：**
先不用，先用单 Agent + 工具路由实现。如果发现单 Agent 的 system prompt 太复杂、意图识别不准，再升级成 Handoff 多 Agent。

---

### 复用6：长对话摘要压缩（可选）

**来源：** `参考/3.chatbot/chatbot3_summarization.py` 的 `summarize_old_messages`

旅行全天对话可能很长，超出 token 限制时，不要直接删消息，而是先做摘要：

```python
# 保留 system message + 最近4条，其余压缩成摘要
summary_prompt = [
    {"role": "system", "content": "你是对话摘要助手"},
    {"role": "user", "content": f"把以下对话压缩成摘要：\n{old_history}"}
]
summary = llm.call(summary_prompt)
# 摘要注入为新的 system message
new_messages = [system_msg, {"role": "system", "content": f"之前的对话摘要：{summary}"}]
new_messages.extend(recent_4_messages)
```

**怎么用进你的框架：**
`CompanionState.turn_history` 超过 20 条时触发，把前面的历史压缩成摘要，这样全天旅游对话都不会断。

---

### 复用优先级总结

| 优先级 | 来源文件 | 复用内容 | 用在哪里 |
|---|---|---|---|
| **必须** | `chatbot_simple.py` | 多轮对话状态管理 | `companion_agent.py` 主循环 |
| **必须** | `agent_function_calling_v2.py` | while 工具调用循环 | `companion_agent.py` 主循环 |
| **必须** | `agent_function_call_db.py` | `tool_impls` 路由字典 | `companion_agent.py` 工具路由 |
| **必须** | 现有 `3-travel_planner/tools/routing.py` | 高德路线与回退逻辑 | `tools/amap.py` / 时间推算 |
| **必须** | 现有 `3-travel_planner/tools/poi.py` | 文本召回与 POI 结构化 | `retrieve_candidates` |
| **必须** | 现有 `3-travel_planner/tools/weather_adapter.py` | 当天天气适配 | `get_weather_now` |
| **推荐** | `concurrent_custom_aggregator.py` | 并行工具调用思路 | 能力4 应急响应 |
| **可选** | `handoff_simple.py` | Triage → 专业 Agent | 单 Agent 不够用时升级 |
| **可选** | `chatbot3_summarization.py` | 长对话摘要压缩 | 全天对话 token 管理 |

---

## 七、不做的边界

| 功能 | 不做的原因 |
|---|---|
| 餐厅在线预订 | 中国餐厅预订文化不成立，意义不大 |
| 打电话确认座位 | 机器人电话会被挂断，不可靠 |
| 消费记账 | Agent 不知道实际消费，只能估算，价值低 |
| 景区内部导航 | 高德景区内部数据不完整，覆盖不了 |
| 拍照推荐机位 | 和核心能力无关 |
| 多日天气驱动的动态重规划 | 当前版本只覆盖旅行当天/近实时决策 |


## 八、什么时候用多agent
在你这个项目里，不是功能一多就要上多 Agent。只有当“单 Agent 已经很难稳定控制”时，才值得拆。

最常见的触发条件有这几类：

1. 意图分流开始频繁出错
例如同一句话里既有“找饭店”又有“下午路线能不能赶上”又有“老人腿疼”，单 Agent 经常选错工具、漏掉关键步骤。这时适合先加一个 Triage Agent 专门做路由。

2. 不同任务的决策逻辑差异太大
你的 4 类能力里，普通推荐、时间协调、异常重排、应急响应，其实风格完全不同。

    推荐更像检索+排序
    时间协调更像规则计算
    异常处理更像局部重规划
    应急响应更像安全优先的保守决策
    如果它们全塞进一个 system prompt，提示会越来越乱，这时适合拆成多个专职 Agent。
    工具集合差异太大
    如果某个子任务只需要路线和时间工具，另一个子任务要用应急场景词库、求助点、医疗兜底逻辑，那么拆开后每个 Agent 只暴露自己需要的工具，会更稳。

4. 需要并行处理独立子任务
    比如应急场景里，你想同时做：

    医疗资源查找
    回酒店路线计算
    剩余家人继续游览建议
    如果这些任务已经相对独立，而且单 Agent 编排太慢，可以考虑多 Agent 并行。


5. 不同任务需要不同安全策略
    应急类回复应该更保守，普通推荐可以更灵活。如果你发现一个 prompt 很难同时兼顾“灵活推荐”和“安全兜底”，就适合拆。

6. 评测发现单 Agent 波动太大
    如果同类输入今天答得对、明天答偏，原因往往是一个 Agent 承担了太多职责。这时拆 Agent 的价值比继续堆 prompt 更高。

但有几种情况，不建议上多 Agent：

只是想“显得高级”
当前功能还少，单 Agent 明显能控住
还没把工具和状态设计清楚
只是 prompt 不够精炼，却误以为要靠多 Agent 解决
结合你现在这个 plan，我的判断还是：

当前阶段不需要多 Agent，单 Agent 足够。

因为你现在的目标还是一个“旅行当天 Companion MVP”，能力边界已经收窄了，而且核心难点主要在：

工具设计是否清楚
状态是否够完整
排序和时间推算是否确定性
这些问题，多 Agent 解决不了，先把单 Agent 架构打稳更重要。

你真正该考虑多 Agent 的时机，大概是下面这个信号出现时：

你已经有了稳定的单 Agent 版本，但发现 推荐 / 时间协调 / 异常处理 / 应急响应 互相干扰，prompt 变得很长，工具误调率开始明显上升。

那时再升级成：

Triage Agent
Search Agent
Coordination Agent
Replanning Agent
Emergency Agent
才是合理的。