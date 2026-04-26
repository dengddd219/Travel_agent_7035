# 刚拿到的版本
## 问题：
确认完了。结论是：**当前主 agent 确实会调用 RAG，也能拿到 `chunk_text` 原文；但最终行程里使用的是被压缩后的短 evidence，不是完整 chunk evidence layer。所以“会缺失很多信息”这个担心是成立的，只是当前代码已经比旧 prompt 描述的状态稍微前进了一步。**

**当前调用链**

1. 后端 `/api/chat` 调用 `TravelPlanningAgent.start_conversation/continue_conversation`，入口在 [backend/server.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/backend/server.py:250)。

2. 主 agent 在 `_execute()` 中生成 `strategy_queries`，然后调用 `get_strategy_context`，固定 `top_k=5`，位置在 [agent.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/3-travel_planner/travel_planner/agent.py:1878) 和 [agent.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/3-travel_planner/travel_planner/agent.py:1969)。

3. `get_strategy_context()` 在 [strategy_rag_adapter.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/3-travel_planner/travel_planner/tools/strategy_rag_adapter.py:441) 里执行：
   - 先跑本地 city RAG / BM25 cache；
   - 再尝试调用 A 组 `2-rag-retrival/search_notes.py` 的 hybrid 检索；
   - 按 signal count 选择 local 或 group_a 结果；
   - 返回 `results`，每条里有 `chunk_id / score / chunk_text / metadata`。

我本地测了重庆和上海，RAG 返回里确实有完整 `chunk_text` 和 `metadata.poi_names/tags/content_type`。但返回顶层**没有**旧 prompt 里希望新增的这些字段：

```text
evidence_chunks
strategy_evidence_by_poi
strategy_evidence_by_district
poi_cooccurrence
route_pair_hints
pitfall_evidence
```

**RAG 结果后面怎么被消费**

现在不是“把所有 chunk summary 后直接输出攻略”。更准确地说，是：

- [agent.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/3-travel_planner/travel_planner/agent.py:1441) `_merge_strategy_into_travel_tips()`：把每条 chunk 的首句截到约 140 字，塞进 travel tips。
- [agent.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/3-travel_planner/travel_planner/agent.py:1472) `_augment_poi_results_with_strategy()`：用 RAG 的 `recommended_pois` 去补地图 POI 候选。
- [planner.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/3-travel_planner/travel_planner/planner.py:168) `_normalize_strategy_context()`：从 `results` 里再抽 `poi_evidence`，但每个 POI 基本只留一个很短 snippet，超过 48 字会截断。
- [planner.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/3-travel_planner/travel_planner/planner.py:447) `_compose_reasoning()`：如果命中 `poi_evidence`，会写进 stop 的原因里。
- [agent.py](C:/Users/19841/Desktop/github/7035project/Travel_agent_7035/3-travel_planner/travel_planner/agent.py:1679) `_build_guide_references()`：只取前 3 条 chunk 的首句、部分避坑和区域 note，最多 4 条 reference。

**所以当前状态**

旧 prompt 里说“下游没有充分使用 chunk 原文”，现在仍然基本成立。当前 planner 已经会用一点 `chunk_text` 生成 POI reasoning，但这只是**浅层 evidence 使用**，不是完整 evidence-aware refactor。

主要信息损失点是：

- 完整 `chunk_text` 没有进入最终 `plan` 或 report，只在中间 `strategy_context["results"]` 存在。
- stop 级解释通常只保留 48 字左右的 snippet。
- `travel_tips` 和 `guide_references` 多数只取首句。
- 没有结构化的 `pitfall_evidence`、`route_pair_hints`、`district_evidence_map`。
- 共现关系只是 `companions` 字符串，不能真正驱动路线聚类。
- 最终 markdown report 没有单独的“攻略依据 / Retrieved Evidence”章节，只在原因和本地攻略里零散体现。

一句话：**RAG 当前不是只返回 summary，它返回原文 chunk；但主 agent 消费时把原文压得很薄，导致很多攻略细节不会流入最终行程。** 旧的 `RAG_EVIDENCE_REFACTOR_PROMPT.md` 仍然适合作为下一步改造方向。
## 解决：
我觉得这个效果差，不是单纯“RAG 检索不到”，而是 **RAG 证据被压扁后，和地图 POI、planner 打分混在一起失真了**。

这份输出暴露了 4 类问题：

1. **RAG 信息损失**
   原文里可能有“武康路-安福路-乌鲁木齐中路-富民路可连成路线”，但最终只变成一句截断 snippet，丢了路线结构、时间建议、避坑、适合人群。

2. **POI 候选污染**
   “又喜商店”“LOOKNOW”“宝记·本帮融合菜”被当成“景点”，说明地图 POI 搜索结果没有按旅游语义过滤，餐厅/商店混进了景点行程。

3. **RAG 权重误用**
   “在攻略里被多次提到”现在会强行加分，但没有判断它是主景点、顺路小店、餐厅、购物点，导致小众打卡点抢占核心行程。

4. **planner 路线约束不够硬**
   第 2 天写“静安区”，但第一站跑到宝山区，说明 district clustering 没有作为强约束，只是弱排序。

**我建议优化顺序**

第一步不要先改最终文案，而是先把 RAG 中间层补齐。现在应该从：

```text
RAG chunk -> recommended_pois/theme/local_pitfalls -> planner
```

改成：

```text
RAG chunk -> structured evidence layer -> candidate rerank -> planner -> report citations
```

**RAG Evidence 层要补这些字段**

在 `strategy_rag_adapter.py` 里新增：

```json
{
  "evidence_chunks": [
    {
      "chunk_id": "...",
      "score": 0.91,
      "chunk_text": "完整原文",
      "snippet": "围绕 POI 的原文片段",
      "source_title": "...",
      "content_type": "route_plan",
      "poi_names": ["武康路", "安福路", "乌鲁木齐中路"],
      "poi_roles": {
        "武康路": "anchor",
        "安福路": "nearby_walk",
        "LOOKNOW": "optional_shop"
      },
      "route_sequence": ["武康路", "安福路", "乌鲁木齐中路", "富民路"],
      "time_suggestions": ["afternoon"],
      "pitfalls": ["需要穿舒服的鞋"]
    }
  ],
  "poi_evidence_map": {
    "武康路": [
      {
        "snippet": "武康路-安福路-乌鲁木齐中路-富民路可连成暴走路线",
        "role": "anchor",
        "source_title": "上海压马路打卡攻略..."
      }
    ]
  },
  "route_pair_hints": [
    {
      "from": "武康路",
      "to": "安福路",
      "strength": 0.9,
      "evidence": "攻略原文中明确连成路线"
    }
  ],
  "pitfall_evidence": [
    {
      "target": "武康路",
      "snippet": "暴走路线，建议穿舒服的鞋"
    }
  ]
}
```

核心是：**不要只拿首句 summary，要把“路线关系、POI 角色、避坑、时间建议”提出来。**

**planner 侧怎么用**

1. **POI 分类要重排**
   - `餐厅` 只能进用餐 slot，不能当景点。
   - `商店/买手店/咖啡店` 默认是 optional stop，不能压过核心景点。
   - `route_plan` 里的第一个/高频景点可以是 anchor，其他是 nearby/optional。

2. **RAG 加分要分层**
   - anchor POI：高加分。
   - route co-occurrence：同日聚类加分。
   - optional shop/cafe：只在附近顺路时加分。
   - pitfall warning：不一定降权，但要进入备注。
   - 只出现一次、且不是 route anchor 的 POI，不能靠“攻略提到”直接上榜。

3. **区域聚类变硬约束**
   例如第 2 天 area 是静安区，就不应该把宝山区餐厅塞进上午第一站，除非用户明确必去。可以加规则：
   - 同一天跨区数 <= 2
   - 非 must_visit 且距离主区域 > 8km 的候选降权或剔除
   - 餐饮 POI 必须靠近当天景点路线

4. **snippet 不能简单截 48 字**
   现在 “店 ▪Tagi - ...” 这种明显是截坏了。应该按 POI 附近窗口抽取：
   - 找到 POI 名在 chunk_text 中的位置；
   - 向前后扩展 80-120 字；
   - 按句号/换行裁剪；
   - 清理 emoji、标签、重复标题。

**最终报告应该变成这样**

不是现在这种：

```text
原因：在检索到的攻略里被多次提到。
```

而是：

```text
原因：武康路是这条 citywalk 的主轴，攻略中明确把“武康路-安福路-乌鲁木齐中路-富民路”作为连续步行路线。
本地提醒：这条线偏暴走，建议穿舒服的鞋。
攻略依据：上海压马路打卡攻略...
```

**优先改动建议**

我会按这个顺序改：

1. `strategy_rag_adapter.py`：新增 evidence layer，不改变 A 组接口。
2. `planner.py`：让 `_normalize_strategy_context()` 消费 `poi_evidence_map / route_pair_hints / pitfall_evidence`。
3. `planner.py`：修 POI scoring，区分 anchor / optional / food / shop。
4. `planner.py`：加强 day clustering，限制跨区和远距离异常点。
5. `render_markdown_report()`：新增“攻略依据 / 本地提醒 / 避坑”输出。
6. 顺手修掉英文 fallback 文案，比如 `Keep this stop grouped...` 这种不该出现在中文报告里。

一句话：**RAG 不应该只负责“推荐几个 POI”，而应该负责给 planner 提供“为什么这些点应该放一起、谁是主点、谁是顺路点、有什么坑”的证据层。** 当前最缺的就是这一层。

## 步骤1:RAG处理
第一个要优化的是：**RAG Evidence Layer，也就是把 `chunk_text` 原文证据结构化后再交给 planner。**

现在的问题是：RAG 返回了原文，但下游只取首句或短 snippet，导致路线关系、避坑、时间建议、POI 角色都丢了。

优化目标：

```text
从：
chunk_text -> recommended_pois / theme_suggestions / local_pitfalls

改成：
chunk_text -> poi_evidence_map / route_pair_hints / pitfall_evidence / poi_roles
```

先做这一层，后面 planner 才能知道：

- 哪些点是主景点 anchor；
- 哪些只是顺路小店 optional；
- 哪些点适合放在同一天；
- 哪些攻略原文明确提示避坑；
- 最终报告该引用哪条攻略依据。

## 步骤2：攻略信息处理避免全推荐或者挤占行程
第二个要优化的是：**POI 角色识别与候选过滤。**

现在 RAG 里出现的所有 `poi_names` 基本都被当成“推荐景点”处理，所以会出现：

- 餐厅被排成上午景点；
- 商店/买手店抢占核心行程；
- 小众打卡点压过真正主景点；
- `recommended_pois` 越多，planner 越容易被噪声带偏。

优化目标：

```text
从：
RAG 提到的 POI = 推荐景点

改成：
RAG 提到的 POI = anchor / nearby / optional_shop / food / pitfall / transit / ignore
```

具体要做：

- `route_plan` chunk 中高频、靠前、被路线串联的点标为 `anchor` 或 `nearby_walk`。
- 餐厅、小吃、咖啡馆标为 `food`，只能进吃饭/休息 slot。
- 商店、买手店、品牌店标为 `optional_shop`，只在同区顺路时加入。
- 明确带“不要去 / 避坑 / 排队 / 太远”的点标为 `pitfall`，不直接加分。
- 没有坐标、分类不清、距离主路线太远的点降权或过滤。

这一步解决的是：**RAG 召回内容有价值，但不能把所有被提到的地点都当作行程主点。**

## 步骤三：路线优化
第三个要优化的是：**路线聚类和跨区约束。**

现在 planner 虽然有 district priority，但它只是弱排序，所以会出现：

- 标题写“第 2 天：静安区”，第一站却跑到宝山区；
- 同一天跨很多区；
- 为了塞一个 RAG 推荐点，路线变得绕；
- 餐厅/商店没有被约束在当天主路线附近。

优化目标：

```text
从：
按 RAG 推荐分 + POI 分数排序，再尽量聚类

改成：
先确定当天主区域 / 路线簇，再只在这个簇里选主点和顺路点
```

具体要做：

- 用 `route_pair_hints` 把攻略里明确同线出现的点组成 route cluster。
- 每一天先选一个主 cluster，例如“武康路-安福路-乌鲁木齐中路”。
- 非 must-visit 的远距离点，如果离当天主 cluster 太远，直接降权或剔除。
- 同一天跨区数设置上限，比如最多 2 个区。
- 餐厅、咖啡、商店只能作为当天 cluster 附近的补充点。
- 如果某个点虽然 RAG 推荐但破坏路线，就放进“备选”，不要硬塞进主行程。

这一步解决的是：**行程应该先顺路，再好看；RAG 应该帮助聚类，而不是制造跨城跳点。**

## 步骤四：报告优化
第四个要优化的是：**最终报告的 evidence 输出方式。**

现在报告里的原因经常是：

```text
在检索到的攻略里被多次提到。
```

或者：

```text
本地提示里也特别提到：【上海压马路打卡攻略...
```

问题是它不像一份真正的攻略依据，用户看不出：

- 这条建议来自哪篇攻略；
- 原文到底说了什么；
- 为什么这些点要放在一起；
- 有什么本地提醒或避坑；
- 哪些是核心安排，哪些只是顺路补充。

优化目标：

```text
从：
模糊一句“攻略提到”

改成：
每个核心 stop 带 1 条短证据 + 本地提醒 + 避坑/顺路说明
```

报告里应该输出成这样：

```text
上午：武康路
原因：作为当天 citywalk 主轴，适合串联安福路、乌鲁木齐中路和富民路。
攻略依据：攻略中明确提到“武康路-安福路-乌鲁木齐中路-富民路可连成暴走路线”。
本地提醒：这条线步行量较大，建议穿舒服的鞋。
```

具体要做：

- `DayPlanItem` 增加 `guide_evidence` / `local_note` / `pitfall_note` 字段。
- `render_markdown_report()` 显示这些字段。
- 不再把完整 chunk 首句硬塞进“原因”。
- 把英文 fallback 文案统一翻译或替换掉。
- 报告末尾可以加一个“攻略依据”小节，列出用到的来源标题和 chunk_id。

这一步解决的是：**让用户感觉这份行程真的读过攻略，而不是只套了模板。**

## 步骤五：RAG质量和查询拆解
第五个要优化的是：**RAG 检索质量和查询拆解。**

前面几步主要是“怎么消费 RAG”，但如果一开始召回的 chunk 就偏了，后面怎么排都容易歪。

现在的问题是：

- `strategy_queries` 有时太泛，比如“上海 三天 行程”；
- 查询没有区分“路线 / 美食 / 避坑 / 亲子 / 预算 / 夜景”；
- top_k 较小，召回内容容易被一两篇攻略带偏；
- RAG 结果没有按 content_type 做配额，可能全是 citywalk 或全是小店；
- 重庆这类城市如果 query 编码或本地 cache 不稳定，就可能出现召回弱的问题。

优化目标：

```text
从：
一组泛 query -> top_k chunks

改成：
多意图 query bundle -> 分类型召回 -> 去重 rerank -> evidence layer
```

具体要做：

- 拆出多组查询：
  - `route_query`: “上海 3天 路线 citywalk”
  - `anchor_query`: “上海 必去 景点 外滩 武康路”
  - `food_query`: “上海 本帮菜 小吃 推荐”
  - `pitfall_query`: “上海 旅游 避坑 排队 预约”
  - `local_query`: “上海 本地人 推荐 小众”
- 每类 query 各取少量 top_k，避免一种内容霸榜。
- 对 `content_type` 做配额，例如 route_plan 至少 2 条，pitfall_warning/local_tip 至少 1 条。
- 对重复标题、重复 source_id 去重。
- 对包含用户 avoid 的 chunk 降权。
- 对 `poi_names` 为空、只有标签没有实际路线的 chunk 降权。
- 将最终高质量 chunk 再进入 evidence layer。

这一步解决的是：**RAG 不只要召回相关，还要召回“可规划”的信息。**

## 最后一步：评测和闭环
第六个要优化的是：**评测与调试闭环。**

前面改完之后，必须有办法判断“是真的变好了”，否则很容易只是文案看起来更长，但路线仍然不合理。

优化目标：

```text
从：
人工看一眼报告感觉好不好

改成：
固定 case + 结构化指标 + trace 对照
```

具体要做：

- 在 `5-evaluate` 增加主 agent 的固定测试 case，例如：
  - 上海 3 天 citywalk；
  - 重庆 3 天美食夜景；
  - 北京 3 天文化路线；
  - 成都 5 天美食轻松游。
- 每个 case 检查：
  - 是否调用 `get_strategy_context`；
  - RAG 是否返回 `evidence_chunks`；
  - 每天跨区数是否 <= 2；
  - 餐厅是否没有被排成上午景点；
  - 每个核心 stop 是否有 guide evidence；
  - report 是否没有英文 fallback；
  - avoid / pitfall 是否没有被硬塞进主路线。
- 在 `eval_trace.jsonl` 里记录：
  - `retrieval_mode`
  - `evidence_chunk_count`
  - `guide_evidence_used_count`
  - `route_pair_hint_count`
  - `cross_district_day_count`
  - `food_as_attraction_count`
- 用一份 before/after 报告对比：
  - 原报告；
  - 新报告；
  - 结构指标变化；
  - 失败原因标签。

这一步解决的是：**优化不能只靠感觉，要能复现、能定位、能证明。**