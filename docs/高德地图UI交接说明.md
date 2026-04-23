# 地图 UI 对接文档

**文件用途：** UI 同学与 地图同学 之间的分工协议，基于 Agent 同学已实现的后端代码。  
**日期：** 2026-04-23  
**相关代码：** `3-travel_planner/travel_planner/ui_backend.py` / `api.py`

---

## 零、总UI同学和地图同学的协同
地图同学的工作本质上就是写一个可以独立运行的地图组件，他自己必须能看到效果，不可能等总UI同学的 UI 做完才测试。

地图同学需要自己做什么
地图同学的交付物是一个独立可运行的 HTML 文件，里面包含：

高德地图初始化
接收 map_payload 数据，打节点、画路线
点击节点的弹窗
地图同学自己开发阶段就用第四节的 JSON 样例硬编码进去跑，不需要等总UI同学的 UI，不需要等 Agent 同学的后端。

你们协同的方式
阶段一（各自开发）：


总UI同学：做整体页面框架，留一个 <div id="map-container"> 空位
地图同学：用静态 JSON 数据跑通地图组件，自己看效果
阶段二（联调）：


总UI同学把地图同学的 map.js 引入总UI同学的 index.html
总UI同学调 API 拿到真实数据，调 window.renderTravelMap(data.map_payload)
地图显示在总UI同学预留的 <div> 里

高德同学的工作完全由 map_payload 驱动：


map_payload.center          → 地图初始中心点
map_payload.days[].color    → 每天路线的颜色
map_payload.days[].stops[]  → 每个节点打标记（编号、名称、弹窗）
map_payload.days[].legs[]   → 每段路线调高德 direction API 画折线
高德同学不需要理解 Agent 是怎么规划的，不需要调后端 API，不需要知道UI的页面长什么样。给高德同学一份 map_payload 的 JSON，高德同学就能独立开发和测试。

我现在把文档第四节的 JSON 样例发给你就够了，你可以立刻开始。


总UI同学给地图同学的最重要的两样东西
1. 第四节的 JSON 样例（直接复制给地图同学）
让地图同学用这个硬编码开发，不依赖任何人。

2. 约定好这两件事：

约定项	总UI同学决定	告诉地图同学
地图容器的 DOM id	总UI同学定，比如 "map-container"	地图同学初始化高德地图时 new AMap.Map("map-container")
renderTravelMap 函数名	固定用这个名字	地图同学暴露这个全局函数
地图同学不需要设计整体 UI
地图同学只管地图这一块的视觉效果：节点颜色、编号气泡、弹窗样式、路线颜色。整体页面的布局、Tab、行程文字，都是总UI同学的事。地图同学的产出就是一个 map.js 文件 + 一个用于自测的 map_demo.html。

## 一、整体数据流（三方都要看）

```
Agent 同学（后端）
  └─ FastAPI: POST /api/plan
        ↓ 返回 JSON，里面包含 map_payload 字段
UI同学（UI 整体）
  └─ 负责调 API、展示行程文字、Tab 布局
        ↓ 把 map_payload 传给地图组件
地图UI同学
  └─ 接收 map_payload，用高德 JS SDK 渲染地图
```

Agent 同学的代码已经把地图所需的所有坐标和路段数据计算好放进 `map_payload`，**地图同学不需要自己调 Agent，也不需要理解 Agent 内部逻辑。**

---

## 二、后端 API（Agent 同学已实现）

### 新建规划

```
POST /api/plan
Content-Type: application/json

{
  "user_message": "我想去上海玩3天，喜欢美食和历史，预算中等"
}
```

### 修改规划（多轮对话）

```
POST /api/refine
Content-Type: application/json

{
  "user_message": "第二天能不能换一个景点",
  "conversation_id": "conv_abc123"
}
```

两个接口返回格式相同，见下节。

---

## 三、API 返回的完整 JSON 结构

```json
{
  "conversation_id": "conv_abc123",
  "report": "# 上海3日智能行程\n...",
  "map_payload": { ... },
  "itinerary_json": { ... },
  "hotel_recommendations": { ... },
  "review_findings": [ ... ]
}
```

**（UI同学）需要的字段：**

| 字段 | 用途 |
|------|------|
| `conversation_id` | 存起来，下次 refine 时带上 |
| `report` | Markdown 字符串，行程的文字描述，渲染在侧边栏 |
| `map_payload` | 直接透传给地图同学的组件函数 |
| `itinerary_json.total_estimated_cost` | 总预算，显示在 UI |
| `itinerary_json.days[].estimated_cost` | 每天费用 |
| `hotel_recommendations` | 酒店推荐，展示在 UI |

**地图同学需要的字段：** 只有 `map_payload`，见下节。

---

## 四、map_payload 详细结构（地图同学的输入）

这是地图同学收到的完整数据，**由 Agent 后端的 `ui_backend.py: build_map_payload()` 自动生成，字段名已固定。UI 同学不需要自己构造这个对象，只需从 API 响应里取出 `map_payload` 字段，原样传给地图同学。**

hi，你直接用这个数据作为示例数据，产出就是：三条颜色不同的路线（蓝/橙/绿），每条线上有编号气泡标记每个景点，点击弹出名称和交通信息

```json
{
  "center": { "lat": 31.2179, "lon": 121.4664 },
  "days": [
    {
      "day_index": 1, "area": "Huangpu", "theme": "经典地标日",
      "color": "#0EA5E9", "inter_stop_distance_m": 5450, "inter_stop_duration_min": 38,
      "stops": [
        {
          "sequence": 1, "poi_name": "The Bund", "time_slot": "morning",
          "category": "attraction", "district": "Huangpu",
          "lat": 31.2384, "lon": 121.4903,
          "address": "Zhongshan East 1st Road, Huangpu", "open_hours": "Open 24 hours",
          "ticket_price": 0, "arrival_mode": "start",
          "arrival_distance_m": 0, "arrival_duration_min": 0,
          "transport_hint": "Start the day in Huangpu."
        },
        {
          "sequence": 2, "poi_name": "Yu Garden", "time_slot": "morning",
          "category": "attraction", "district": "Huangpu",
          "lat": 31.2285, "lon": 121.4907,
          "address": "279 Yuyuan Old Street, Huangpu", "open_hours": "09:00-16:30",
          "ticket_price": 40, "arrival_mode": "walking",
          "arrival_distance_m": 1850, "arrival_duration_min": 24,
          "transport_hint": "Walking about 24 min (1.9 km) south along the riverside."
        },
        {
          "sequence": 3, "poi_name": "Shanghai Museum East", "time_slot": "afternoon",
          "category": "attraction", "district": "Huangpu",
          "lat": 31.2310, "lon": 121.4750,
          "address": "People's Square, Huangpu", "open_hours": "09:00-17:00",
          "ticket_price": 0, "arrival_mode": "driving",
          "arrival_distance_m": 3600, "arrival_duration_min": 14,
          "transport_hint": "Take a taxi about 14 min (3.6 km) west to People's Square."
        }
      ],
      "legs": [
        {
          "from_poi": "The Bund", "to_poi": "Yu Garden", "mode": "walking",
          "distance_m": 1850, "duration_min": 24,
          "from_lat": 31.2384, "from_lon": 121.4903,
          "to_lat": 31.2285, "to_lon": 121.4907,
          "transport_hint": "Walking about 24 min (1.9 km)."
        },
        {
          "from_poi": "Yu Garden", "to_poi": "Shanghai Museum East", "mode": "driving",
          "distance_m": 3600, "duration_min": 14,
          "from_lat": 31.2285, "from_lon": 121.4907,
          "to_lat": 31.2310, "to_lon": 121.4750,
          "transport_hint": "Take a taxi about 14 min (3.6 km)."
        }
      ]
    },
    {
      "day_index": 2, "area": "Jing'an", "theme": "博物馆与商业日",
      "color": "#F97316", "inter_stop_distance_m": 5300, "inter_stop_duration_min": 40,
      "stops": [
        {
          "sequence": 1, "poi_name": "Shanghai Natural History Museum", "time_slot": "morning",
          "category": "attraction", "district": "Jing'an",
          "lat": 31.2380, "lon": 121.4626,
          "address": "510 Beijing West Road, Jing'an", "open_hours": "09:00-17:00",
          "ticket_price": 30, "arrival_mode": "start",
          "arrival_distance_m": 0, "arrival_duration_min": 0,
          "transport_hint": "Start the day in Jing'an."
        },
        {
          "sequence": 2, "poi_name": "Jing'an Temple", "time_slot": "afternoon",
          "category": "attraction", "district": "Jing'an",
          "lat": 31.2294, "lon": 121.4447,
          "address": "1686 Nanjing West Road, Jing'an", "open_hours": "07:30-17:00",
          "ticket_price": 50, "arrival_mode": "walking",
          "arrival_distance_m": 2100, "arrival_duration_min": 26,
          "transport_hint": "Walking about 26 min (2.1 km) southwest."
        },
        {
          "sequence": 3, "poi_name": "Xintiandi", "time_slot": "evening",
          "category": "food", "district": "Huangpu",
          "lat": 31.2193, "lon": 121.4730,
          "address": "Taicang Road, Huangpu", "open_hours": "10:00-22:00",
          "ticket_price": 0, "arrival_mode": "driving",
          "arrival_distance_m": 3200, "arrival_duration_min": 14,
          "transport_hint": "Take a taxi about 14 min (3.2 km) to Xintiandi for dinner."
        }
      ],
      "legs": [
        {
          "from_poi": "Shanghai Natural History Museum", "to_poi": "Jing'an Temple", "mode": "walking",
          "distance_m": 2100, "duration_min": 26,
          "from_lat": 31.2380, "from_lon": 121.4626,
          "to_lat": 31.2294, "to_lon": 121.4447,
          "transport_hint": "Walking about 26 min (2.1 km)."
        },
        {
          "from_poi": "Jing'an Temple", "to_poi": "Xintiandi", "mode": "driving",
          "distance_m": 3200, "duration_min": 14,
          "from_lat": 31.2294, "from_lon": 121.4447,
          "to_lat": 31.2193, "to_lon": 121.4730,
          "transport_hint": "Take a taxi about 14 min (3.2 km)."
        }
      ]
    },
    {
      "day_index": 3, "area": "Xuhui", "theme": "法租界漫步日",
      "color": "#10B981", "inter_stop_distance_m": 4220, "inter_stop_duration_min": 22,
      "stops": [
        {
          "sequence": 1, "poi_name": "Wukang Road", "time_slot": "morning",
          "category": "attraction", "district": "Xuhui",
          "lat": 31.2046, "lon": 121.4373,
          "address": "Wukang Road, Xuhui", "open_hours": "Open 24 hours",
          "ticket_price": 0, "arrival_mode": "start",
          "arrival_distance_m": 0, "arrival_duration_min": 0,
          "transport_hint": "Start the day in Xuhui."
        },
        {
          "sequence": 2, "poi_name": "West Bund Museum", "time_slot": "afternoon",
          "category": "attraction", "district": "Xuhui",
          "lat": 31.1684, "lon": 121.4655,
          "address": "2555 Longteng Ave, Xuhui", "open_hours": "10:00-18:00",
          "ticket_price": 0, "arrival_mode": "driving",
          "arrival_distance_m": 3800, "arrival_duration_min": 16,
          "transport_hint": "Take a taxi about 16 min (3.8 km) to West Bund."
        },
        {
          "sequence": 3, "poi_name": "Long Museum West Bund", "time_slot": "afternoon",
          "category": "attraction", "district": "Xuhui",
          "lat": 31.1670, "lon": 121.4638,
          "address": "3398 Longteng Ave, Xuhui", "open_hours": "10:00-18:00",
          "ticket_price": 50, "arrival_mode": "walking",
          "arrival_distance_m": 420, "arrival_duration_min": 6,
          "transport_hint": "Walking about 6 min (0.4 km) along the riverfront."
        }
      ],
      "legs": [
        {
          "from_poi": "Wukang Road", "to_poi": "West Bund Museum", "mode": "driving",
          "distance_m": 3800, "duration_min": 16,
          "from_lat": 31.2046, "from_lon": 121.4373,
          "to_lat": 31.1684, "to_lon": 121.4655,
          "transport_hint": "Take a taxi about 16 min (3.8 km)."
        },
        {
          "from_poi": "West Bund Museum", "to_poi": "Long Museum West Bund", "mode": "walking",
          "distance_m": 420, "duration_min": 6,
          "from_lat": 31.1684, "from_lon": 121.4655,
          "to_lat": 31.1670, "to_lon": 121.4638,
          "transport_hint": "Walking about 6 min (0.4 km)."
        }
      ]
    }
  ],
  "all_stops": [
    { "day_index": 1, "color": "#0EA5E9", "sequence": 1, "poi_name": "The Bund",                     "lat": 31.2384, "lon": 121.4903 },
    { "day_index": 1, "color": "#0EA5E9", "sequence": 2, "poi_name": "Yu Garden",                    "lat": 31.2285, "lon": 121.4907 },
    { "day_index": 1, "color": "#0EA5E9", "sequence": 3, "poi_name": "Shanghai Museum East",          "lat": 31.2310, "lon": 121.4750 },
    { "day_index": 2, "color": "#F97316", "sequence": 1, "poi_name": "Shanghai Natural History Museum","lat": 31.2380, "lon": 121.4626 },
    { "day_index": 2, "color": "#F97316", "sequence": 2, "poi_name": "Jing'an Temple",               "lat": 31.2294, "lon": 121.4447 },
    { "day_index": 2, "color": "#F97316", "sequence": 3, "poi_name": "Xintiandi",                    "lat": 31.2193, "lon": 121.4730 },
    { "day_index": 3, "color": "#10B981", "sequence": 1, "poi_name": "Wukang Road",                  "lat": 31.2046, "lon": 121.4373 },
    { "day_index": 3, "color": "#10B981", "sequence": 2, "poi_name": "West Bund Museum",             "lat": 31.1684, "lon": 121.4655 },
    { "day_index": 3, "color": "#10B981", "sequence": 3, "poi_name": "Long Museum West Bund",        "lat": 31.1670, "lon": 121.4638 }
  ]
}
```

### 字段说明

**`center`**
- 所有 POI 坐标的平均值，用于设置地图初始视野中心

**`days[]`**
- `day_index`：第几天，从 1 开始
- `color`：该天的主题颜色（十六进制），5 天循环：`#0EA5E9` / `#F97316` / `#10B981` / `#E11D48` / `#8B5CF6`
- `theme`：该天主题文字，可显示在地图图层标题或图例
- `inter_stop_distance_m` / `inter_stop_duration_min`：当天总行程距离和时间（汇总值）

**`stops[]`**（每天的 POI 节点列表，按顺序排列）
- `sequence`：当天第几站，从 1 开始，用于在地图上显示编号
- `poi_name`：地点名称
- `category`：`"attraction"` 景点 / `"food"` 餐厅 / `"hotel"` 酒店
- `lat` / `lon`：坐标（GCJ-02，高德原生坐标系，**不需要转换**）
- `arrival_mode`：`"start"` 当天起点 / `"walking"` 步行到达 / `"driving"` 打车/驾车到达
- `arrival_distance_m` / `arrival_duration_min`：从上一站到本站的距离和时间
- `transport_hint`：人可读的交通说明，可显示在弹窗里

**`legs[]`**（相邻两站之间的路段，用于画导航线）
- `from_lat` / `from_lon`：起点坐标
- `to_lat` / `to_lon`：终点坐标
- `mode`：`"walking"` 或 `"driving"`，对应高德 `AMap.Walking` / `AMap.Driving`

**`all_stops[]`**（所有天的节点平铺列表，每条记录多了 `day_index` 和 `color`，方便地图同学做全览视图）

---

## 五、注意事项（地图同学必读）

**1. 坐标系**  
坐标系取决于 Agent 后端用哪个数据源获取 POI：
- `source: ["amap"]`（有 AMAP_API_KEY 时）→ **GCJ-02**，高德 JS SDK 直接渲染，不需要转换
- `source: ["nominatim"]` 或 `["profile_seed"]`（降级时）→ **WGS84**，在高德地图上会有轻微偏移

**正常情况下 Agent 同学配好 AMAP_API_KEY 后坐标全部是 GCJ-02，不需要转换。** 如果发现标记点系统性偏移，让 Agent 同学确认 Key 是否生效。

**2. 无效坐标过滤**  
`lat` 或 `lon` 为 `null` 或等于 `0` 的 stop 表示地理编码失败，**跳过不渲染**，否则标记会飞到非洲。

```javascript
const validStops = stops.filter(s => s.lat && s.lon && !(s.lat === 0 && s.lon === 0));
```

**3. 没有预存折线**  
`legs` 里只有起终点坐标，**没有中间路径的 polyline 数据**。  
要画真实导航折线，需要在前端用 `legs` 的坐标实时调用高德方向 API：

```javascript
// 步行路线示例
const walking = new AMap.Walking({ map: map, hideMarkers: true });
walking.search(
  [leg.from_lon, leg.from_lat],
  [leg.to_lon, leg.to_lat],
  (status, result) => { /* 高德自动画线 */ }
);

// 驾车路线示例
const driving = new AMap.Driving({ map: map, hideMarkers: true });
driving.search(
  new AMap.LngLat(leg.from_lon, leg.from_lat),
  new AMap.LngLat(leg.to_lon,   leg.to_lat),
  (status, result) => { /* 高德自动画线 */ }
);
```

注意：高德坐标顺序是 **[经度 lon, 纬度 lat]**，和 `map_payload` 字段名相反，调用时别搞混。

**4. 高德 JS API Key**  
需要在高德开放平台申请 **Web端（JS API）Key**，和 Agent 后端用的 Web服务 Key 是**两个不同的 Key**。

**5. Agent 同学的前置条件（影响坐标质量）**  
`map_payload` 里坐标数据的质量依赖 Agent 同学在 `.env` 里配置的 `AMAP_API_KEY`（Web服务Key）。**联调前请先让 Agent 同学跑一次，确认返回的 `map_payload` 里 stops 的 lat/lon 都是非零值。**

---

## 六、总UI同学们之间的对接接口（最核心）

地图同学暴露一个全局函数，总UI同学在拿到 API 数据后调用它：

```javascript
// map.js（地图同学写）
window.renderTravelMap = function(mapPayload) {
  // 地图同学在这里实现：打标记、画路线、设中心点
};

// app.js（总UI同学写）
const response = await fetch('/api/plan', { ... });
const data = await response.json();
window.renderTravelMap(data.map_payload);  // 就这一行
```

### 地图同学需要给总UI同学的

| 交付物 | 说明 |
|--------|------|
| `map.js` | 包含 `window.renderTravelMap(payload)` 函数 |
| 高德 JS API Key | 用于 HTML 里引入高德 SDK |
| 地图容器 DOM id | 总UI同学的 HTML 里需要有对应的 `<div id="...">` |

### 总UI同学需要给地图同学的

| 交付物 | 说明 |
|--------|------|
| 地图容器的 DOM id | 总UI同学 HTML 里放地图的 `<div>` 的 id，双方约定好 |
| `map_payload` 的 JSON 样例 | 让地图同学本地调试用，见第四节 |
| 调用时机 | 确认是"首次渲染时调用一次"还是"用户切换日期时重新调用" |

---

## 七、推荐的文件分工

```
前端目录/
  ├── index.html          ← 总UI同学责：页面整体结构、Tab、侧边栏
  ├── style.css           ← 总UI同学负责：整体样式
  ├── app.js              ← 总UI同学负责：调 API、处理数据、调 renderTravelMap()
  └── map.js              ← 地图同学负责：只暴露 renderTravelMap()
```

---

## 八、联调步骤建议

1. **地图同学先用静态数据本地跑通**：把第四节的 JSON 样例硬编码进去，确保地图能正常显示
2. **总UI同学先用 mock 数据跑通 UI 布局**：把第四节的 JSON 样例作为假数据，确认整体布局没问题
3. **联调**：总UI同学接真实 API，拿到 `map_payload` 后调用地图同学的 `renderTravelMap()`
4. **处理边界情况**：坐标为 null / 0 的过滤，网络错误时的 fallback 提示
