# 高德地图 UI 交付包

这是给总 UI 同学对接用的精简交付包。只需要关注本文件夹，不需要读取原项目里的 Streamlit/Folium 旧 demo。

## 文件说明

- `map.js`
  - 地图组件核心文件
  - 暴露 `window.renderTravelMap(mapPayload, options)`
- `map.css`
  - demo 样式和地图 marker/popup 样式
- `map_demo.html`
  - 地图同学自测页面
- `integration_minimal.html`
  - 正式页面最小接入示例，不包含联调说明、Key 状态、示例代码等自测面板
- `mock_map_payload.js`
  - 静态 mock 数据，来自交接文档示例
- `amap-env.js`
  - 静态 key 文件。新电脑没有 `.env` 时，demo 会自动回退到这里的内置 key
- `serve_demo.py`
  - 本地自测服务，优先从 `../azure_client/.env` 读取高德 key；如果没有，则自动回退到 `amap-env.js`

## 最小接入方式

总 UI 页面需要有一个地图容器：

```html
<div id="map-container"></div>
```

然后加载高德 SDK、样式和地图组件：

```html
<link rel="stylesheet" href="./map.css" />
<script src="https://webapi.amap.com/maps?v=2.0&key=你的高德JSKey&plugin=AMap.Scale,AMap.ToolBar,AMap.Walking,AMap.Driving,AMap.Transfer"></script>
<script src="./map.js"></script>
```

拿到后端返回后调用：

```javascript
const response = await fetch("/api/plan", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ user_message: "我想去上海玩3天" })
});

const data = await response.json();
window.renderTravelMap(data.map_payload, {
  containerId: "map-container"
});
```

## Demo 页和正式接入页的区别

- `map_demo.html`
  - 给地图同学和测试同学自测用
  - 包含联调说明、Key 状态、示例代码、测试按钮
  - 不建议直接放进最终产品页面
- `integration_minimal.html`
  - 给总 UI 同学参考正式接入方式
  - 只保留地图容器、SDK 加载、`map.js` 和一次 `renderTravelMap()` 调用
  - 总 UI 同学可以照这个页面把地图嵌进自己的正式 UI

## 高德 Key 配置

高德 JS API v2 推荐配置两项：

```env
AMAP_JS_API_KEY=你的高德Web端JSKey
AMAP_SECURITY_JSCODE=你的高德JS安全密钥
```

如果用本文件夹里的 demo 服务，推荐把这两个变量放到项目的 `azure_client/.env` 中。`serve_demo.py` 会优先读取 `.env`；如果新电脑上没有这个文件，会自动回退到当前目录下 `amap-env.js` 里内置的 key。

## 本地自测方式

如果整个交付包是单独发给同学的，直接进入本文件夹执行：

```powershell
python serve_demo.py
```

如果这个文件夹仍放在原项目根目录下，也可以在项目根目录执行：

```powershell
E:\miniconda\python.exe amap_ui_delivery\serve_demo.py
```

或如果本机 Python 正常：

```powershell
python amap_ui_delivery\serve_demo.py
```

然后打开：

```text
http://127.0.0.1:8126/map_demo.html
```

## `renderTravelMap` 参数

```javascript
window.renderTravelMap(mapPayload, {
  containerId: "map-container",
  focusDay: "all",
  routeModeOverride: null,
  city: "上海",
  togglesSelector: "#map-toggles",
  modeSelector: "#route-mode-controls",
  legendSelector: "#map-legend",
  listSelector: "#day-list",
  statusSelector: "#map-status"
});
```

### 常用参数

- `containerId`
  - 地图容器 id，默认 `map-container`
- `focusDay`
  - `"all"` 或某一天编号，例如 `"2"`
- `routeModeOverride`
  - `null`：跟随后端 `legs[].mode`
  - `"walking"`：步行预览
  - `"driving"`：驾车预览
  - `"transit"`：公交/地铁预览
- `city`
  - 公交/地铁预览需要城市名，例如 `"上海"`

注意：路线预览只影响地图画线，不修改后端返回的时间、距离、预算和文案。

## 支持的 map_payload 字段

- `center.lat`
- `center.lon`
- `days[].day_index`
- `days[].area`
- `days[].theme`
- `days[].color`
- `days[].inter_stop_distance_m`
- `days[].inter_stop_duration_min`
- `days[].stops[]`
- `days[].legs[]`

## 当前能力

- 高德地图初始化
- 多天路线不同颜色
- 编号 marker
- 点击 marker 弹窗
- 步行/驾车真实道路路线
- 公交/地铁预览，失败时自动步行兜底
- 无效坐标过滤
- 重复调用自动清理旧图层
- Day 切换
- 路线预览方式切换

## 对接注意事项

- 后端 `map_payload` 坐标应为 GCJ-02，高德地图无需转换
- `lat/lon` 为 `0` 或 `null` 的 stop 会被跳过
- 总 UI 后续只需要调用 `window.renderTravelMap(data.map_payload)`
- 如果路线变直线，请看状态框里的失败原因
- 如果底图不显示，优先检查高德 JS Key、securityJsCode、域名白名单
- 如果状态框出现 `CUQPS_HAS_EXCEEDED_THE_LIMIT`，说明高德路线服务触发 QPS/频率限制。当前组件已经做了路线请求限速和成功路线缓存，建议稍等几秒或刷新后再试，避免连续快速切换预览方式。

## 新数据如何接入

### 情况 1：总 UI 已经能调后端 API

不需要改地图组件文件。总 UI 拿到接口返回后，直接把新的 `map_payload` 传进来即可：

```javascript
const response = await fetch("/api/plan", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ user_message: "我想去上海玩3天" })
});

const data = await response.json();
window.renderTravelMap(data.map_payload, {
  containerId: "map-container",
  city: data.map_payload?.city || "上海"
});
```

如果是多轮修改：

```javascript
const response = await fetch("/api/refine", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    conversation_id,
    user_message: "第二天改成轻松一点"
  })
});

const data = await response.json();
window.renderTravelMap(data.map_payload, {
  containerId: "map-container",
  city: data.map_payload?.city || "上海"
});
```

### 情况 2：只有一份新的静态 `map_payload`

如果只是本地看效果，直接替换 `mock_map_payload.js` 里的：

```javascript
window.mockMapPayload = { ... };
```

把 `{ ... }` 换成新的 `map_payload` 对象，然后刷新 `map_demo.html` 就能看到新路线。

注意：不要把完整 API 响应粘进去，只粘 `map_payload` 这一层。完整 API 响应通常是：

```json
{
  "conversation_id": "...",
  "report": "...",
  "map_payload": { "center": {}, "days": [] }
}
```

这里应该只复制：

```json
{ "center": {}, "days": [] }
```

## Key 已内置说明

本交付包的 `amap-env.js` 已经内置当前 demo 使用的 Web端 JS Key 和安全密钥。对接同学把整个 `amap_ui_delivery` 文件夹拷到新电脑后，直接运行 `python serve_demo.py` 即可自测。若同级目录存在 `../azure_client/.env`，则会优先使用 `.env` 中的配置。正式项目上线前，建议按团队安全规范改成由环境变量或后端配置注入，不要把 key 提交到公开仓库。
