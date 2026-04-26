# RAG Evidence Refactor Prompt For `3-travel_planner`

## Goal

改造 `3-travel_planner` 对 RAG 结果的消费方式。目标不是改 A 组 RAG 检索本身，而是让 B 组 Agent / Planner 真正把攻略知识库当作“规划证据”来使用，而不是只把它当作 POI/tag 信号源。

---

## Background

当前系统已经能从 RAG 取回 Top-K chunk，返回内容里包含：

- `chunk_id`
- `score`
- `chunk_text`
- `metadata`，其中有 `poi_names`、`tags`、`districts`、`travel_type_tags` 等

相关文件：

- `1-rag_pipeline_delivery/DEV_SPEC.md`
- `1-rag_pipeline_delivery/a_group_rag_api_contract.md`

当前 `3-travel_planner` 的问题不在“拿不到 chunk 原文”，而在“拿到了，但下游没有充分使用”。

当前现状大致是：

1. `strategy_rag_adapter.py`
   - `get_strategy_context()` 已返回 `results`
   - 每条 result 里有 `chunk_text`
   - 但 `_summarize_strategy()` 主要把这些结果压缩成：
     - `recommended_pois`
     - `theme_suggestions`
     - `local_pitfalls`
     - `neighborhood_notes`

2. `agent.py`
   - 会读取 `strategy_context["results"]`
   - 但目前主要只是：
     - 把 chunk 首句转成 tips
     - 把 chunk 首句转成 guide references
   - 也就是说，chunk 原文只被浅层消费

3. `planner.py`
   - 实际规划阶段主要消费的是 summary signals
   - 没有把 chunk 原文当作一等 evidence 继续往后传

这导致：

- itinerary 能排出来
- 但攻略的“本地经验”“可信解释”“避坑提醒”“攻略风格”“与知识库的耦合深度”都不够强
- 知识库最值钱的人类经验内容没有真正流进最终输出

---

## Refactor Objectives

希望把当前架构从：

`RAG -> POI/tag signals -> planner`

升级为：

`RAG -> evidence layer -> planner/report/explanations`

具体目标有 5 个：

1. 能把合理的景点安排在一起
   - 不只是因为它们同区
   - 还要因为攻略里反复共同出现、适合同日串联、或者有路线上的共现关系

2. 产出的攻略是有结构性的
   - 不是一份泛泛 markdown
   - 而是每个 stop / POI 都有自己的说明块

3. 具备本地化程度
   - 能体现攻略原文中的本地经验
   - 不只是通用旅游模板话术

4. 具备可信解释
   - 能回答“为什么选这个点”“为什么和另一个点排一起”
   - 解释应来自检索证据，不是只写“攻略推荐”

5. 包含避坑提醒、攻略风格、与知识库的耦合深度
   - 比如预约提醒、别踩坑、某片区适合连逛、某点适合早去/晚去等

---

## Files To Modify

请优先看这些文件：

1. `3-travel_planner/travel_planner/tools/strategy_rag_adapter.py`
2. `3-travel_planner/travel_planner/agent.py`
3. `3-travel_planner/travel_planner/planner.py`

可参考：

- `1-rag_pipeline_delivery/DEV_SPEC.md`
- `1-rag_pipeline_delivery/a_group_rag_api_contract.md`

---

## Suggested Implementation

原则：增量改造，兼容现有流程，不要推翻整个 planner。

### 1. Add An Evidence Layer In `strategy_rag_adapter.py`

当前 `get_strategy_context()` 返回：

- `results`
- `recommended_pois`
- `theme_suggestions`
- `local_pitfalls`
- `neighborhood_notes`

请保留这些字段，同时新增一层更适合下游消费的 evidence 字段。

建议新增：

- `evidence_chunks`
- `strategy_evidence_by_poi`
- `strategy_evidence_by_district`
- `poi_cooccurrence`
- `route_pair_hints`
- `pitfall_evidence`

建议结构示例：

```json
{
  "evidence_chunks": [
    {
      "chunk_id": "xxx",
      "score": 0.92,
      "chunk_text": "什刹海和南锣鼓巷东西不要买，看看景色就可以了。",
      "source_title": "北京citywalk攻略",
      "content_type": "local_tip",
      "poi_names": ["什刹海", "南锣鼓巷"],
      "districts": ["西城区", "东城区"],
      "tags": ["citywalk", "避坑"]
    }
  ],
  "strategy_evidence_by_poi": {
    "什刹海": [
      {
        "chunk_id": "xxx",
        "score": 0.92,
        "snippet": "什刹海和南锣鼓巷东西不要买，看看景色就可以了。"
      }
    ]
  },
  "strategy_evidence_by_district": {
    "东城区": [
      {
        "chunk_id": "yyy",
        "score": 0.88,
        "snippet": "这一区域适合步行连逛。"
      }
    ]
  },
  "poi_cooccurrence": {
    "故宫": ["景山", "天安门"]
  },
  "route_pair_hints": [
    {
      "from": "故宫",
      "to": "景山",
      "strength": 0.9,
      "evidence": "攻略里经常同段出现"
    }
  ],
  "pitfall_evidence": [
    {
      "scope": "poi",
      "target": "什刹海",
      "snippet": "东西不要买，看看景色就可以了。"
    }
  ]
}
```

要求：

- 从已有 `results` 派生，不改 A 组接口
- 数量控制在合理范围，比如 top 5~8 条高价值 evidence
- 去重
- snippet 可以截断，但要保留原始 `chunk_text`

### 2. Make `agent.py` Evidence-Aware

当前相关位置：

- `_merge_strategy_into_travel_tips()`
- `_build_guide_references()`

希望改成 evidence-aware：

- `travel_tips` 不只是“首句 snippet”
- 而是能区分：
  - `poi-specific evidence`
  - `district evidence`
  - `pitfall evidence`
  - `route clustering evidence`

建议：

- 给 `tool_results["get_travel_tips"]` 合并更多 evidence
- 给最终 `plan` 增加：
  - `guide_references`
  - `strategy_evidence_summary`
  - `poi_evidence_map`
  - `district_evidence_map`

### 3. Extend `planner.py` Strategy Context Normalization

当前 `_normalize_strategy_context()` 主要保留：

- `recommended_pois`
- `theme_suggestions`
- `district_priority`
- `local_pitfalls`

希望扩展成还能处理：

- `poi_evidence_map`
- `district_evidence_map`
- `cooccurrence_map`
- `pitfall_map`
- `route_pair_hints`

目标不是让 planner 直接做复杂 NLP，而是让它能利用这些 evidence 增强：

1. POI scoring
   - 被多条攻略证据支持的点可加权
   - 被明确避坑的点要降权或加提醒

2. Day clustering
   - 攻略高频共现的 POI 尽量排在一起
   - 攻略高频提到的 district 组合可优先成组

3. Reasoning / explanation
   - 每个 stop 最好能附 1~2 条 evidence snippet
   - 能说明“为什么选中它”“为什么和前后点排在一起”

4. Planning notes
   - 每一天附局部的本地提醒 / 避坑提示

### 4. Reflect Guide Evidence In Final Report

当前报告可以继续 deterministic render，但请让它至少多出一层 evidence 感。

希望最终报告不是只写：

- `Day 1: 故宫 -> 景山 -> 王府井`

而是能写成类似：

- 故宫
  - 选择理由：攻略中高频出现，且与景山/天安门经常被同日串联
  - 本地建议：建议上午优先安排
  - 避坑提醒：证件/预约信息提前确认
  - 攻略依据：xxx / yyy

- 什刹海
  - 本地提醒：适合看景，不建议在景区内消费纪念品
  - 攻略依据：xxx

如果不适合把完整证据放进主报告，也可以新增一个：

- `Retrieved Guide Evidence`
- `攻略依据`
- `Local Notes & Pitfalls`

小节。

---

## Acceptance Criteria

改完后，希望至少满足以下标准：

1. `get_strategy_context()` 除 summary signals 外，新增可直接消费的 evidence 层
2. planner/report 至少有一处明确使用 evidence，而不是只使用 POI/tag signals
3. 最终 itinerary / report 能体现：
   - 本地化程度
   - 可信解释
   - 避坑提醒
   - 攻略风格
   - 与知识库的耦合深度
4. 不破坏现有 deterministic planner 主流程
5. 不要求改 A 组 RAG 接口
6. `group_a_search_notes` 路径和 `local_bm25` fallback 路径都能工作
7. 尽量保留现有字段，避免大面积破坏下游依赖

---

## Non-Goals

这次不要做这些事：

- 不改 A 组检索接口
- 不重写 chunking / embedding / reranking
- 不大改 planner 整体架构
- 不强行引入新的复杂 citation 框架
- 不做 full LLM report regeneration unless necessary

这次只做一件事：

让 `chunk_text` 原文证据真正流进 B 组系统，而不是在 adapter 层被压扁成少量 summary signals。

---

## Expected Delivery Notes

改完请说明：

1. 改了哪些文件
2. 新增了哪些字段
3. evidence 具体在哪些链路被消费
4. before / after 的返回结构对比
5. 一个最小示例：
   - 某条 chunk 如何变成 POI evidence / pitfall evidence / report explanation

---

## Clarification

这里不是要求“让 LLM 直接吃所有 chunk 原文自由发挥”，而是希望把 RAG 结果提升为规划证据层。

也就是说：

- 结构化规划仍然保留
- 但结构化规划要被原文证据增强
- RAG 不再只是候选点提供者，而是 itinerary 的证据提供者
