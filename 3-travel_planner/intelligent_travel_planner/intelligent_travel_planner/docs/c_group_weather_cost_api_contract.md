# C 组 Weather / Cost -> B 组 Agent 接口协议草案

## 1. 目标

C 组负责向 B 组 Agent 提供两类辅助信息：

1. 旅行日期对应的天气信息
2. 城市级别的费用估算信息

B 组 Agent 会在 itinerary 规划时直接调用这些结果，所以 C 组的交付物不能只是“截图里的表”或“几个描述字符串”，而应当是**可直接调用的函数 + 稳定 JSON 返回结构 + 静态参考数据文件**。

一句话定义：

`C 组负责提供 trip conditions，B 组 Agent 负责把这些条件和攻略、地图信息一起转成 itinerary JSON。`

---

## 2. C 组应交付给 B 组什么

建议 C 组最终交付 4 样东西：

1. `get_weather(...)` 可调用函数
2. `estimate_cost(...)` 可调用函数
3. `city_cost_reference.json` 或 `city_cost_reference.csv`
4. `README / contract.md` 接口说明文档

如果做成 Python 模块，B 组最好能直接 import 调用。

如果做成 API，也至少要给：

- endpoint 地址
- 请求参数
- 返回 JSON schema
- 错误处理方式

---

## 3. 为什么不能只交“两个函数名字”

像下面这种定义，只能说明“你们想做什么”，不够 B 组真正接入：

```python
def get_weather(city: str, travel_dates: list[str]) -> list[dict]:
    ...

def estimate_cost(city: str, days: int, budget_level: str, user_budget: float = None) -> dict:
    ...
```

原因：

- 没有约定返回字段
- 字段类型不明确
- B 组不知道哪些字段是数值、哪些是文本
- 异常情况不明确
- fallback 行为不明确

所以必须额外定义清楚：

- 输入参数
- 返回 JSON 结构
- 缺省值
- 错误时怎么返回
- 哪些字段是 B 组强依赖

---

## 4. 天气接口推荐协议

### 4.1 推荐函数签名

```python
def get_weather(city: str, travel_dates: list[str]) -> dict:
    ...
```

如果 C 组更喜欢按“起始日期 + 天数”写，也可以接受：

```python
def get_weather(city: str, trip_days: int, start_date: str = "") -> dict:
    ...
```

但为了减少适配成本，建议最终返回结构固定。

---

### 4.2 推荐返回结构

```json
{
  "city": "成都",
  "source": "open-meteo",
  "start_date": "2026-05-01",
  "forecast": [
    {
      "date": "2026-05-01",
      "summary": "多云",
      "temp_min": 18,
      "temp_max": 27,
      "precipitation_probability": 35,
      "outdoor_suitability": "mixed",
      "clothing_advice": "短袖+薄外套",
      "planning_advice": "上午适合户外，下午保留室内备选"
    }
  ],
  "best_outdoor_days": ["2026-05-02"],
  "risky_days": ["2026-05-03"]
}
```

---

### 4.3 B 组强依赖字段

| 字段 | 是否必须 | 说明 | B 组用途 |
|---|---|---|---|
| `city` | 必须 | 城市名 | 校验是否匹配用户城市 |
| `forecast[].date` | 必须 | 日期 | 对齐日程天数 |
| `forecast[].summary` | 必须 | 天气概况 | 展示和解释 |
| `forecast[].temp_min` | 必须 | 最低温 | 生成穿衣建议、用户展示 |
| `forecast[].temp_max` | 必须 | 最高温 | 生成穿衣建议、用户展示 |
| `forecast[].precipitation_probability` | 必须 | 降雨概率 | 判断是否适合户外 |
| `forecast[].outdoor_suitability` | 必须 | `good/mixed/poor` | 规划室外/室内活动 |

### 4.4 推荐字段

| 字段 | 是否推荐 | 说明 | B 组用途 |
|---|---|---|---|
| `source` | 推荐 | 天气来源 | 记录数据来源 |
| `start_date` | 推荐 | 起始日期 | 日程对齐 |
| `forecast[].clothing_advice` | 推荐 | 穿衣建议 | 展示层使用 |
| `forecast[].planning_advice` | 推荐 | 规划建议 | 解释为什么换室内活动 |
| `best_outdoor_days` | 推荐 | 户外最优日期 | 优先放景点 / 远点 |
| `risky_days` | 推荐 | 高风险天气日 | 安排商场 / 博物馆 / 餐饮 |

---

## 5. 费用接口推荐协议

### 5.1 推荐函数签名

```python
def estimate_cost(
    city: str,
    days: int,
    budget_level: str,
    travelers: int = 1,
    user_budget: float | None = None
) -> dict:
    ...
```

---

### 5.2 推荐返回结构

```json
{
  "city": "成都",
  "days": 3,
  "travelers": 2,
  "budget_level": "medium",
  "currency": "CNY",
  "breakdown": {
    "hotel_per_night": {
      "min": 250,
      "max": 400
    },
    "food_per_day": {
      "min": 120,
      "max": 220
    },
    "local_transport_total": {
      "min": 60,
      "max": 120
    }
  },
  "totals": {
    "min": 1090,
    "max": 2200,
    "mid": 1645
  },
  "budget_fit": {
    "user_budget": 1800,
    "within_budget": true
  },
  "pricing_notes": [
    "不含往返大交通",
    "五一节假日酒店价格可能上浮"
  ],
  "assumptions": [
    "默认市区住宿",
    "默认地铁 / 打车混合出行"
  ]
}
```

---

### 5.3 B 组强依赖字段

| 字段 | 是否必须 | 说明 | B 组用途 |
|---|---|---|---|
| `city` | 必须 | 城市名 | 校验结果 |
| `days` | 必须 | 天数 | 校验预算计算 |
| `budget_level` | 必须 | 预算档位 | 与用户画像对齐 |
| `currency` | 必须 | 币种 | 展示 |
| `breakdown.hotel_per_night.min/max` | 必须 | 酒店单晚区间 | 预算解释 |
| `breakdown.food_per_day.min/max` | 必须 | 餐饮单日区间 | 预算解释 |
| `breakdown.local_transport_total.min/max` | 必须 | 本地交通区间 | 预算解释 |
| `totals.min/max` | 必须 | 总预算区间 | 是否超预算 |

### 5.4 推荐字段

| 字段 | 是否推荐 | 说明 | B 组用途 |
|---|---|---|---|
| `totals.mid` | 推荐 | 中位估算值 | 排序与展示 |
| `travelers` | 推荐 | 出行人数 | 更准确估算 |
| `budget_fit.user_budget` | 推荐 | 用户预算 | 判断是否超支 |
| `budget_fit.within_budget` | 推荐 | 是否在预算内 | 规划降级版本 |
| `pricing_notes` | 推荐 | 价格提醒 | 节假日 / 旺季说明 |
| `assumptions` | 推荐 | 假设条件 | 降低误解 |

---

## 6. 静态费用参考表也必须交

除了函数，C 组还应交一份静态城市费用表，例如：

- `city_cost_reference.json`
- 或 `city_cost_reference.csv`

建议至少覆盖：

- 10 个核心城市
- 3 档预算：`low / medium / high`
- 3 类成本：`hotel / food / local_transport`

推荐结构：

```json
{
  "成都": {
    "low": {
      "hotel_per_night": {"min": 100, "max": 180},
      "food_per_day": {"min": 60, "max": 100},
      "local_transport_total_per_3_days": {"min": 40, "max": 80}
    },
    "medium": {
      "hotel_per_night": {"min": 250, "max": 400},
      "food_per_day": {"min": 120, "max": 220},
      "local_transport_total_per_3_days": {"min": 60, "max": 120}
    }
  }
}
```

这份静态表的意义是：

- API 失败时可 fallback
- 新城市上线时先有 baseline
- demo 现场更稳定

---

## 7. B 组如何使用 C 组结果

B 组 Agent 对 C 组结果的典型使用方式如下：

### 天气结果

1. 看 `outdoor_suitability`
2. 如果是 `poor`，优先安排室内景点 / 商场 / 餐饮
3. 如果是 `good`，优先安排公园 / 观景台 / 长距离步行
4. 用 `risky_days` 做整天的 fallback
5. 用 `temp_min/temp_max` 和 `summary` 生成用户提示

### 费用结果

1. 用 `totals.min/max` 给出整体预算区间
2. 用 `budget_fit.within_budget` 判断是否需要降级规划
3. 用 `breakdown` 给用户解释钱花在哪
4. 在同类 POI 候选很多时，优先选择更符合预算档位的方案

---

## 8. 最低可接受交付版本

如果 C 组时间有限，B 组最低可以接受：

### 最低版天气接口

```json
{
  "city": "成都",
  "forecast": [
    {
      "date": "2026-05-01",
      "summary": "多云",
      "temp_min": 18,
      "temp_max": 27,
      "precipitation_probability": 35,
      "outdoor_suitability": "mixed"
    }
  ]
}
```

### 最低版费用接口

```json
{
  "city": "成都",
  "days": 3,
  "budget_level": "medium",
  "currency": "CNY",
  "breakdown": {
    "hotel_per_night": {"min": 250, "max": 400},
    "food_per_day": {"min": 120, "max": 220},
    "local_transport_total": {"min": 60, "max": 120}
  },
  "totals": {
    "min": 670,
    "max": 1420
  }
}
```

---

## 9. C 组与 B 组的职责边界

### C 组负责

- 接天气 API
- 提供天气结构化结果
- 整理城市费用静态表
- 提供费用估算函数

### B 组负责

- 调用天气与费用接口
- 把这些结果和攻略、地图信息汇总
- 做 itinerary 排程
- 输出最终 itinerary JSON

### 不建议 C 组负责

- 最终景点排序
- 行程时间安排
- JSON itinerary 生成

这些属于 B 组 Agent 的职责。

---

## 10. 协商时可以直接说的话

你可以直接对 C 组说：

> 我们 B 组 Agent 会直接消费你们的天气和费用结果，所以你们不能只给字符串说明或者一张静态表。  
> 我们需要你们交给我们：两个可调用函数、稳定的 JSON schema、以及一份静态费用参考表。  
> 天气侧我们最需要 `date / temp_min / temp_max / precipitation_probability / outdoor_suitability`；  
> 费用侧我们最需要 `breakdown + totals(min/max/mid)` 的数值字段。

---

## 11. 最终建议

### 最推荐方案

C 组交付：

- `get_weather(...)`
- `estimate_cost(...)`
- `city_cost_reference.json/csv`
- 接口说明文档

### 最低可接受方案

C 组至少交付：

- 一个天气函数
- 一个费用函数
- 两个函数的稳定 JSON 返回
- 一份静态城市费用表

---

## 12. 一句话版本

`C 组负责把天气和费用条件结构化交给 B 组，B 组 Agent 再把这些条件融合进最终 itinerary JSON。`
