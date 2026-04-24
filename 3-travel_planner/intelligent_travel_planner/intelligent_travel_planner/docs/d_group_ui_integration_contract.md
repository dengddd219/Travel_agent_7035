# B 组 Agent -> D 组 UI 联调文档

## 1. 文档目的

这份文档用于帮助 D 组前端 / 展示层与 B 组 Agent 对接。

目标不是只把一段文字显示出来，而是实现一个**可多轮修改、可展示真实路线图、可展示 review 结果**的旅行规划界面。

一句话定义：

`D 组负责用户交互与地图展示，B 组 Agent 负责输出结构化 itinerary JSON 和会话状态。`

---

## 2. 推荐整体架构

真实版建议采用：

- `B 组 backend`：Python + FastAPI
- `D 组 frontend`：React / Next.js
- `地图`：Amap JavaScript API

推荐链路：

```text
Frontend UI
-> FastAPI backend
-> TravelPlanningAgent
-> A组 / 高德 / C组
-> itinerary JSON + conversation state
-> Frontend render
```

其中：

- B 组维护：Agent、路线规划、review、会话偏好记忆
- D 组维护：输入面板、对话区、日程卡片、地图、状态切换

---

## 3. B 组当前已具备的能力

当前项目中，B 组 Agent 已经具备以下能力：

1. 解析用户输入为 `user_profile`
2. 支持多轮对话中的 `preference_memory`
3. 将复杂请求拆成 `strategy / geo / conditions` 子任务
4. 调用地图、天气、tips 等工具
5. 生成最终 `itinerary JSON`
6. 在规划后运行 `review`

当前后端核心可直接复用的方法：

- `TravelPlanningAgent.run()`
- `TravelPlanningAgent.run_orchestrated()`
- `TravelPlanningAgent.start_conversation()`
- `TravelPlanningAgent.continue_conversation()`

当前推荐 API 入口文件：

- `travel_planner/api.py`

因此，D 组不需要直接接触 planner 细节，而应通过 backend API 获取：

- `conversation_state`
- `user_profile`
- `itinerary_json`
- `report`
- `review_summary / review_findings`

---

## 4. D 组最需要知道的接口边界

### 4.1 D 组负责什么

- 收集用户输入
- 展示当前 preference
- 发起首次规划请求
- 发起 follow-up refine 请求
- 展示 day-by-day itinerary
- 在地图上展示 POI 与路线
- 展示 review warning / info

### 4.2 D 组不需要负责什么

- 不需要自己解析用户自然语言
- 不需要自己计算路线顺序
- 不需要自己做天气预算推理
- 不需要自己做 review 判断
- 不需要自己决定 POI 取舍

这些都应由 B 组 Agent 在 backend 完成。

---

## 5. 推荐 API 设计

真实版建议 D 组只调用 2 个核心接口。

### 5.1 首次生成：`POST /api/plan`

用户第一次输入旅行需求时调用。

#### 请求体

```json
{
  "user_message": "Plan a 3-day Hong Kong trip with Peak Tram, local food, and reasonable transfers."
}
```

#### 返回体

```json
{
  "conversation_id": "conv_001",
  "conversation_state": {
    "preference_memory": {},
    "latest_user_profile": {},
    "turn_history": []
  },
  "user_profile": {},
  "itinerary_json": {},
  "report": "markdown report here",
  "tool_logs": [],
  "review_summary": "Review passed without major routing, weather, or budget issues.",
  "review_findings": [],
  "map_payload": {}
}
```

---

### 5.2 多轮修改：`POST /api/refine`

用户在已有计划基础上继续修改时调用。

#### 请求体

推荐真实版使用 `conversation_id`，由 backend 管理内存状态：

```json
{
  "conversation_id": "conv_001",
  "user_message": "改成低预算，不要太赶，加上 Hong Kong Disneyland。"
}
```

如果第一版还没有 server-side session，也可以临时直接传 `conversation_state`：

```json
{
  "conversation_state": {
    "preference_memory": {},
    "latest_user_profile": {},
    "turn_history": []
  },
  "user_message": "改成低预算，不要太赶，加上 Hong Kong Disneyland。"
}
```

#### 返回体

结构与 `/api/plan` 一致，只是内容更新为最新版本。

---

## 6. 推荐会话状态管理方式

### 推荐方案：server-side session

真实版更建议：

- frontend 只保存 `conversation_id`
- backend 用内存字典 / Redis / database 存 `ConversationState`

好处：

- D 组不用关心 Python dataclass 的细节
- 请求体更短
- 更适合多轮对话
- 前后端职责更清晰

推荐 backend 内部结构：

```python
conversation_store = {
    "conv_001": ConversationState(...)
}
```

### 第一版可接受方案：前端回传状态

如果来不及做服务端状态存储，前端可以把 `conversation_state` 原样缓存并回传。

但真实版不建议长期这么做。

---

## 7. UI 页面推荐布局

建议采用三栏布局。

### 左栏：Conversation / Preferences

展示：

- 当前用户输入框
- 当前偏好摘要
- city
- trip_days
- budget_level
- pace
- interests
- must_visit
- avoid

作用：

- 用户知道系统“记住了什么”
- 多轮修改时可以看到状态是否已更新

### 中栏：Map / Route View

展示：

- day-by-day route
- POI markers
- 每日颜色区分
- stop sequence 编号
- marker popup

### 右栏：Itinerary / Review

展示：

- day cards
- 每个 stop 的理由、天气适配、交通信息
- `review_summary`
- `review_findings`

---

## 8. 前端如何使用 itinerary JSON

### 8.1 itinerary JSON 中最重要的字段

D 组最常用的字段包括：

```json
{
  "city": "Hong Kong",
  "trip_days": 3,
  "overview": "...",
  "total_estimated_cost": 188.0,
  "selected_pois": [],
  "days": [],
  "planning_notes": [],
  "local_tips": [],
  "review_summary": "...",
  "review_findings": []
}
```

其中：

- `selected_pois`：可用于查每个点的经纬度、地址、营业时间
- `days[]`：用于渲染 day cards
- `days[].items[]`：用于渲染 stop list
- `review_summary`：用于顶部状态条
- `review_findings`：用于 warning panel

---

## 9. 地图展示所需字段

如果 D 组要做“真实版路线图”，地图渲染至少需要下面这些数据。

### 9.1 目前 itinerary 中已经有的可用字段

在当前后端输出中，D 组已经可以直接拿到：

- `selected_pois[].name`
- `selected_pois[].lat`
- `selected_pois[].lon`
- `selected_pois[].district`
- `selected_pois[].address`
- `days[].items[].poi_name`
- `days[].items[].arrival_mode`
- `days[].items[].arrival_distance_m`
- `days[].items[].arrival_duration_min`
- `days[].inter_stop_distance_m`
- `days[].inter_stop_duration_min`

因此第一版地图可以这样画：

1. 根据 `days[].items[].poi_name`
2. 去 `selected_pois[]` 中匹配同名 POI
3. 取出坐标
4. 画 marker
5. 依据顺序画 polyline

### 9.2 真实版建议 B 组额外补一个 `map_payload`

为了让 D 组更容易做真实地图，推荐 backend 在 API 返回中额外附带：

```json
{
  "map_payload": {
    "days": [
      {
        "day_index": 1,
        "color": "#0EA5E9",
        "stops": [
          {
            "sequence": 1,
            "poi_name": "Peak Tram",
            "lat": 22.27,
            "lon": 114.15,
            "district": "Central",
            "time_slot": "morning"
          },
          {
            "sequence": 2,
            "poi_name": "Central Market",
            "lat": 22.28,
            "lon": 114.15,
            "district": "Central",
            "time_slot": "afternoon"
          }
        ],
        "legs": [
          {
            "from_poi": "Peak Tram",
            "to_poi": "Central Market",
            "mode": "walking",
            "distance_m": 1679,
            "duration_min": 22
          }
        ]
      }
    ]
  }
}
```

这样 D 组就不需要自己做 POI name join。

---

## 10. 推荐前端交互流程

### 10.1 首次规划

1. 用户输入自然语言需求
2. 前端调用 `POST /api/plan`
3. backend 返回：
   - `conversation_id`
   - `user_profile`
   - `itinerary_json`
   - `report`
   - `review_summary`
   - `review_findings`
   - `map_payload`
4. 前端更新：
   - 左栏 preference summary
   - 中栏地图
   - 右栏 itinerary 和 review

### 10.2 多轮 refine

1. 用户在聊天输入框输入 follow-up
2. 前端调用 `POST /api/refine`
3. backend 用上一轮 `conversation_state` 合并偏好
4. backend 返回新 itinerary
5. 前端整体刷新：
   - preference summary
   - itinerary cards
   - map route
   - review panel

---

## 11. 前端应该如何展示 review

建议 D 组把 review 做成明显但不打断体验的区域。

### 推荐展示方式

- 顶部状态条：
  - 绿色：`Review passed`
  - 橙色：`Warnings found`

- 右栏独立 panel：
  - `must_visit_coverage`
  - `pace_balance`
  - `route_efficiency`
  - `budget_pressure`
  - `weather_fit`

### 推荐交互

如果某条 warning 指向某一天：

- 点击 warning
- 自动滚动到对应 day card
- 同时高亮地图上该 day 的路线

---

## 12. 建议前端技术实现

### React 侧推荐组件拆分

```text
TripPlannerPage
  PreferencePanel
  ChatPanel
  RouteMap
  ItineraryPanel
  ReviewPanel
```

### Amap JS 地图建议

推荐使用：

- marker + infoWindow
- polyline
- 不同 day 使用不同颜色

真实版如果要更像产品：

- 点击 day card 时只显示当天 route
- 默认显示全部天数概览
- 支持切换 `Day 1 / Day 2 / All`

---

## 13. D 组需要和 B 组确认的字段清单

在正式联调前，建议 D 组和 B 组确认下面这些字段是否固定：

1. `conversation_id` 是否由 backend 维护
2. `user_profile` 返回格式是否固定
3. `itinerary_json.days[].items[]` 字段是否固定
4. `selected_pois[]` 是否始终包含坐标
5. 是否提供 `map_payload`
6. `review_findings[].rule` 的枚举值是否固定
7. 当 A 组 / C 组返回不完整时，backend 是否仍然保证返回 itinerary

---

## 14. 推荐最小联调版本

如果时间紧，建议先完成下面这个 MVP 联调版本：

- 一个输入框
- 一个生成按钮
- 一个 refine 输入框
- 一个 itinerary panel
- 一个地图 panel
- 一个 review panel

MVP 阶段不一定要做：

- 登录
- 历史对话列表
- 多用户共享
- 真正的数据库会话持久化

---

## 15. 对 D 组最重要的一句话

`D 组不需要自己“理解旅行逻辑”，只需要把 B 组 Agent 返回的 conversation state、itinerary JSON、review results 和 map payload 清晰展示出来。`
