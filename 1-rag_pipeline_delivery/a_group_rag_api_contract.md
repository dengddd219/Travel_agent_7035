# A 组 RAG -> B 组 Agent 接口协议草案

## 1. 目标

A 组负责从攻略知识库中检索与用户需求相关的内容，并将结果以**结构化 JSON** 返回给 B 组 Agent。

B 组 Agent 不希望只拿到“原始段落”，而是希望拿到：

1. 可检索的原文片段
2. 可规划的结构化字段
3. 可解释的检索分数和来源信息

一句话定义：

`A 组负责“找内容 + 抽结构”，B 组负责“汇总信息 + 生成 itinerary JSON”`

---

## 2. 为什么不能只返回简单 metadata

下面这种字段太少，只能做基础检索展示，不足以支持 itinerary 规划：

```json
{
  "city": "成都",
  "category": "美食",
  "title": "成都火锅终极攻略",
  "source_id": "xiaohongshu_xxxxx",
  "chunk_index": 2
}
```

原因：

- `category` 太粗，无法区分“景点推荐 / 路线建议 / 避坑提醒 / 亲子信息”
- 缺少 `poi_names`，B 组无法直接把攻略内容转给地图工具
- 缺少 `districts`，B 组无法做区域聚类和合理排程
- 缺少 `chunk_text`，B 组无法知道这段内容到底在说什么
- 缺少 `score`，B 组无法判断检索结果可信度和优先级

---

## 3. A 组给 B 组的推荐返回结构

### 3.1 顶层返回格式

```json
{
  "query": "成都亲子游有什么推荐景点",
  "city": "成都",
  "retrieval_mode": "rag",
  "top_k": 5,
  "results": []
}
```

---

## 4. 每条检索结果的标准结构

```json
{
  "chunk_id": "xiaohongshu_xxxxx_002",
  "score": 0.86,
  "chunk_text": "如果带小朋友来成都，熊猫基地建议早上先去，下午可以安排宽窄巷子轻松逛吃。",
  "metadata": {
    "source_id": "xiaohongshu_xxxxx",
    "source_platform": "xiaohongshu",
    "title": "成都亲子游路线攻略",
    "city": "成都",
    "content_type": "family_route",
    "tags": ["亲子", "熊猫基地", "宽窄巷子"],
    "poi_names": ["成都大熊猫繁育研究基地", "宽窄巷子"],
    "districts": ["成华区", "青羊区"],
    "travel_type_tags": ["family"],
    "published_at": "2026-04-01",
    "chunk_index": 2
  }
}
```

---

## 5. 字段要求

### 5.1 必须字段

这些字段是 B 组 Agent 强依赖的，建议 A 组必须返回：

| 字段 | 是否必须 | 说明 | B 组用途 |
|---|---|---|---|
| `chunk_id` | 必须 | chunk 唯一标识 | 去重、日志、引用来源 |
| `score` | 必须 | 检索相关度分数 | 排序、过滤低质量结果 |
| `chunk_text` | 必须 | 当前 chunk 原文 | 理解推荐理由、生成解释 |
| `metadata.city` | 必须 | 城市 | 过滤跨城噪声 |
| `metadata.content_type` | 必须 | 内容类型 | 判断该 chunk 是“攻略 / 美食 / 行程 / 避坑” |
| `metadata.tags` | 必须 | 标签数组 | 与用户兴趣匹配 |
| `metadata.poi_names` | 必须 | POI 名称数组 | 交给地图工具做标准化和坐标补全 |
| `metadata.districts` | 必须 | 行政区 / 商圈数组 | 做区域聚类、减少来回绕路 |
| `metadata.source_id` | 必须 | 原始来源 ID | 回溯来源 |
| `metadata.chunk_index` | 必须 | chunk 序号 | 重建上下文 |

### 5.2 推荐字段

这些字段不是第一版必须，但如果有，会明显提高 B 组 Agent 的规划质量：

| 字段 | 是否推荐 | 说明 | B 组用途 |
|---|---|---|---|
| `metadata.title` | 推荐 | 原文标题 | 给报告增加引用可读性 |
| `metadata.source_platform` | 推荐 | 如 xiaohongshu / mafengwo | 记录来源类型 |
| `metadata.travel_type_tags` | 推荐 | 如 family / food / leisure | 与用户画像对齐 |
| `metadata.published_at` | 推荐 | 发布时间 | 判断信息新鲜度 |
| `metadata.price_level` | 推荐 | 价格标签 | 预算控制 |
| `metadata.time_suggestions` | 推荐 | 如 morning / evening | 帮助排时段 |
| `metadata.poi_types` | 推荐 | 景点 / 美食 / 商圈 | 规划混排更稳定 |

---

## 6. `content_type` 建议枚举

建议不要继续使用单一 `category`，改为更细的 `content_type`。

推荐枚举值：

```text
attraction_guide
food_guide
route_plan
family_guide
hidden_gem
shopping_guide
local_tip
pitfall_warning
transport_tip
budget_tip
```

如果 A 组觉得太多，第一版至少保证下面 5 类：

```text
attraction_guide
food_guide
route_plan
family_guide
pitfall_warning
```

---

## 7. B 组对 A 组的最小可交付要求

如果 A 组开发资源有限，B 组可以接受一个最小版本：

```json
{
  "query": "成都亲子游有什么推荐景点",
  "city": "成都",
  "results": [
    {
      "chunk_id": "xiaohongshu_xxxxx_002",
      "score": 0.86,
      "chunk_text": "熊猫基地建议早上去，宽窄巷子适合下午轻松逛。",
      "metadata": {
        "source_id": "xiaohongshu_xxxxx",
        "city": "成都",
        "content_type": "family_guide",
        "tags": ["亲子", "熊猫基地"],
        "poi_names": ["成都大熊猫繁育研究基地", "宽窄巷子"],
        "districts": ["成华区", "青羊区"],
        "chunk_index": 2
      }
    }
  ]
}
```

这已经够 B 组做：

- 攻略知识补充
- 地点标准化
- 地区聚类
- itinerary JSON 生成

---

## 8. B 组如何使用 A 组结果

B 组 Agent 对 A 组结果的使用方式如下：

1. 用 `score` 对检索结果排序
2. 用 `city` 过滤错误城市内容
3. 用 `content_type` 判断内容类型
4. 用 `tags` 与用户兴趣做匹配
5. 用 `poi_names` 交给地图工具查坐标、营业时间、票价
6. 用 `districts` 做按区聚类
7. 用 `chunk_text` 提取推荐理由、注意事项、避坑提示
8. 将这些信息与天气和预算模块一起汇总，输出最终 itinerary JSON

---

## 9. A 组与 B 组的职责边界

### A 组负责

- 从知识库检索相关 chunk
- 返回 chunk 原文
- 返回结构化 metadata
- 尽量抽取 POI / district / tag

### B 组负责

- 用户需求解析
- 调用 A 组接口
- 调用地图和天气预算工具
- 标准化不同来源数据
- 生成最终 itinerary JSON

### 不建议 A 组承担

- 最终 itinerary 排程
- 路线优化
- JSON 日程生成

这些应该由 B 组 Agent 负责，不然职责会混乱。

---

## 10. 协商时可以直接说的话

你可以直接对 A 组说：

> 我们 B 组 Agent 的核心产出是最终 itinerary JSON，所以你们返回给我们的内容不能只有标题和 category。  
> 对我们最关键的是：`chunk_text`、`score`、`poi_names`、`districts`、`content_type`、`tags`。  
> 这样我们才能把攻略知识稳定接到地图、天气和预算模块里，最终生成可执行的日程。

---

## 11. 最终建议

### 最推荐方案

A 组返回：

- 原文 chunk
- 检索分数
- 结构化 metadata

### 最低可接受方案

A 组至少返回：

- `chunk_id`
- `score`
- `chunk_text`
- `city`
- `content_type`
- `tags`
- `poi_names`
- `districts`
- `source_id`
- `chunk_index`

---

## 12. 一句话版本

`A 组负责把攻略内容检索出来并附带足够的结构化字段，B 组 Agent 才能把这些知识可靠地转成 itinerary JSON。`
