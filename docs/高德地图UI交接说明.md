# 高德地图 UI 交接说明

## 当前正式链路

- 后端入口是 `backend/server.py`
- 正式聊天页是 `6-UI/UI/chat.html`
- 地图脚本是 `6-UI/map_UI/map.js`
- 地图样式是 `6-UI/map_UI/map.css`
- 后端返回的地图数据由 `3-travel_planner/travel_planner/ui_backend.py` 中的 `build_map_payload()` 生成

当前项目不再使用以下旧入口：

- `3-travel_planner/travel_planner/api.py`
- `6-UI/travel_chat.html`
- `6-UI/UI/index.html`
- `/api/plan`
- `/api/refine`

## 前后端对接方式

前端统一调用：

```http
POST /api/chat
Content-Type: application/json
```

首轮请求：

```json
{
  "message": "我想去上海玩3天，喜欢美食和历史，预算中等",
  "conversation_id": null,
  "conversation_state": null
}
```

多轮续聊：

```json
{
  "message": "第二天能不能换一个景点？",
  "conversation_id": "conv_abc123",
  "conversation_state": { "...": "..." }
}
```

响应里前端最关心的字段：

- `report`
- `map_payload`
- `itinerary_json`
- `hotel_recommendations`
- `cost_summary`
- `conversation_id`
- `conversation_state`

## 地图集成方式

`chat.html` 在拿到后端响应后，直接把 `map_payload` 传给地图组件：

```javascript
const response = await fetch('/api/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

const data = await response.json();
window.renderTravelMap(data.map_payload, {
  containerId: 'map-container',
  modeSelector: '#route-mode-controls',
  statusSelector: '#map-status',
});
```

地图组件对外暴露的唯一核心接口：

```javascript
window.renderTravelMap(mapPayload, options)
```

## 地图容器约定

- 地图容器 DOM id：`map-container`
- 路线模式切换容器：`#route-mode-controls`
- 地图状态栏：`#map-status`

## `map_payload` 关键字段

```json
{
  "city": "Shanghai",
  "center": { "lat": 31.23, "lon": 121.47 },
  "days": [
    {
      "day_index": 1,
      "area": "Huangpu",
      "theme": "Classic landmarks",
      "color": "#0EA5E9",
      "stops": [],
      "legs": []
    }
  ],
  "all_stops": []
}
```

重点字段说明：

- `days[].stops[]`：地图打点数据
- `days[].legs[]`：路线段数据
- `all_stops[]`：全量点位，用于全局视角
- `center`：默认中心点

## 注意事项

- 当前高德地图使用 GCJ-02 坐标系
- `lat` 或 `lon` 为 `null` / `0` 的点应跳过渲染
- 项目正式运行方式是 `uvicorn backend.server:app --reload`
- 浏览器访问 `http://127.0.0.1:8000/` 或 `/chat`，都会进入同一套聊天 UI
