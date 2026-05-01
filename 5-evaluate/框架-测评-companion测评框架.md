# 陪伴 Agent 测评完整说明指南

> 适用目标：用于向老板/PPT 第一部分讲清楚“我们为什么要搭建陪伴 Agent 测评框架、测评策略是什么、为什么这样设计、全流程如何运行”。第二部分再接实际跑分结果即可。

---

## 1. 一句话总览

陪伴 Agent 不是普通问答系统，它要在旅行现场的动态环境中完成“理解用户状态、判断风险、调用工具、重排计划、持续对话”的长链路任务。因此测评不能只看最后一句回答好不好，而要看完整轨迹是否正确。

本项目的陪伴 Agent 测评框架采用 **VitaBench-style 轨迹评测思路**：让 Agent 在“模拟用户 + 工具环境 + 状态记忆”的任务环境里跑完整对话，再用 **原子 rubric checklist + 滑动窗口 LLM judge + 多次重复运行指标** 判断任务是否完成、能力短板在哪里、结果是否稳定。

---

## 2. 为什么要搭建这个测评框架

### 2.1 业务原因：陪伴 Agent 的风险点不在“会不会聊天”，而在“现场能不能做对”

旅行陪伴场景有几个特点：

- 信息不完整：用户经常只说“老人走不动了”“时间不够了”，不会一次性说清当前位置、剩余时间、偏好和约束。
- 环境会变化：天气、体力、排队、闭馆、交通、饭点、火车/航班 deadline 都会改变计划。
- 工具链很重要：Agent 需要查询地点、路线、天气、候选 POI、应急资源，并把工具结果转成可执行建议。
- 安全和体验都重要：老人不适、走失、暴雨、赶车等场景不能只给景点推荐。

所以只测最终回答会漏掉关键问题。例如：

- 最后回答看起来合理，但没有先问当前位置。
- 回复很热情，但没有调用路线/天气/重排工具。
- 工具调用了，但参数错了。
- 第一次答对了，但多跑几次不稳定。
- 遇到老人胸闷仍然继续安排景点。

这就是为什么要做轨迹级测评，而不是只做人类主观打分。

### 2.2 工程原因：没有测评闭环，就无法知道该改哪里

陪伴 Agent 的失败通常不是单一问题，而可能来自三类不同能力：

- 推理错：没有识别时间预算、deadline、安全优先级、老人行动限制。
- 工具错：没有调用必要工具、工具顺序错、参数错、遗漏二次验证。
- 交互错：该澄清时没澄清、没有记住用户已完成/跳过的节点、没有给可执行下一步。

如果只有一个总分，无法指导迭代。这个框架把每个任务拆成原子 rubrics，并按 **reasoning / tool / interaction** 三个维度归因，目的是让后续优化能落到具体模块。

### 2.3 汇报原因：给老板看的不是“我跑了几个 case”，而是一套可复用评测资产

这个框架的价值不是某一次分数，而是形成一套可持续复用的评测体系：

- 有标准任务集：10 城市 × 3 任务 = 30 个 benchmark seed tasks。
- 有自动运行脚本：`companion_eval_pipeline.py`。
- 有可复查轨迹：`trajectories.jsonl`。
- 有细粒度打分：`trial_results.jsonl`。
- 有汇总指标：`summary.json`。
- 有失败归因：按推理/工具/交互维度定位问题。
- 有离线和 LLM 两种模式：既能低成本回归，也能接近真实使用场景。

---

## 3. PPT 第一部分建议结构：三段论评测策略

可以按下面三段讲，三段之间互斥、并列、递进。

### 策略一：离线规则基线，先验证“系统基本盘能不能稳定跑”

**核心问题：** 不调用 LLM 时，Agent 的任务流、状态更新、工具 mock、rubric 检查是否成立？

**怎么做：**

- 使用 `--no-agent-llm`
- 使用 `--simulator rule`
- 使用 `--evaluator rule`
- 跑完整 30 个任务

**为什么这样做：**

离线基线成本低、速度快、结果确定。它不用于证明 Agent 很智能，而是用于证明评测任务、工具接口、状态流转、rubric 规则本身没有坏。

**产出价值：**

- 得到稳定 baseline。
- 发现规则路径和工具链的硬错误。
- 可以作为后续每次改代码后的回归测试。

**当前已有结果：**

```text
strict_success_rate = 23.3%
avg_rubric_score = 50.1%
avg_tool_success = 31.7%
```

这组结果代表“确定性离线版 Agent 在当前 30 任务上的 baseline 表现”。

---

### 策略二：全 LLM 轨迹仿真，再验证“真实 Agent 场景能不能做对”

**核心问题：** 当用户、Agent、裁判都由 LLM 驱动时，系统是否能在接近真实对话的环境中完成任务？

完整 LLM 测评必须包含三方：

| 角色 | 作用 | 为什么缺一不可 |
|---|---|---|
| LLM 用户模拟器 | 扮演真实游客，按任务设定逐步补充信息 | 测 Agent 是否会主动澄清、是否能处理多轮上下文 |
| LLM Agent 本体 | Agent 自己判断意图、规划工具调用、组织回复 | 测的才是真正的 Agent 智能，而不是固定规则流程 |
| LLM 裁判 | 按 rubric 判断完整轨迹是否满足要求 | 避免只看关键词，能判断语义和过程证据 |

**怎么做：**

- 不传 `--no-agent-llm`
- 使用 `--simulator llm`
- 使用 `--evaluator hybrid`
- 当前评测代码会强制 Agent 本体走 `agentic_llm` 路径，避免被确定性任务流截走。

**为什么这样做：**

真实用户不会按固定脚本说话，Agent 的 LLM 决策也有概率性，单次成功不能代表稳定。因此需要让三方都进入 LLM 状态，再通过多次 trial 观察成功率和稳定性。

**产出价值：**

- 测到 Agent 本体的 LLM 决策能力。
- 测到多轮交互能力。
- 测到 LLM judge 对复杂轨迹的语义判断。
- 可报告 token、成本、延迟。

---

### 策略三：轨迹级归因分析，最后回答“失败到底失败在哪里”

**核心问题：** 如果任务失败，是推理失败、工具失败，还是交互失败？

**怎么做：**

每个任务都有原子 rubrics，例如：

- 是否识别 4 小时时间预算。
- 是否在当前位置缺失时先澄清。
- 是否调用 `replan_itinerary`。
- 是否保留 must-visit POI。
- 是否考虑老人行动限制。

评测器会把完整轨迹拆成窗口，用 sliding-window evaluator 更新每条 rubric 的状态，最后输出：

- `strict_success`
- `rubric_score`
- `dimension_scores.reasoning`
- `dimension_scores.tool`
- `dimension_scores.interaction`
- `failed_rubrics`
- `failure_tags`

**为什么这样做：**

最终分数只能说明“好不好”，轨迹归因才能说明“该改哪里”。对 Agent 来说，过程证据比最终文本更重要。

**产出价值：**

- 可以定位失败模块。
- 可以解释为什么总分低。
- 可以给后续迭代排序：先修工具链、推理 prompt，还是交互策略。

---

## 4. 参考方法和论文依据

### 4.1 主要参考：VitaBench

本框架主要参考 `5-evaluate/龙猫测评.md` 中整理的 VitaBench 方法。

论文/资料：

- VitaBench: Benchmarking LLM Agents with Versatile Interactive Tasks in Real-world Applications
- arXiv: https://arxiv.org/abs/2509.26490
- 官网: https://vitabench.github.io/

借鉴点：

1. **不只看最终答案，而是看完整 trajectory。**
   Agent 在任务环境中与用户、工具、状态交互，评测完整过程。

2. **任务复杂度拆成三维：reasoning / tool / interaction。**
   本项目也按推理、工具、交互三类 rubric 做失败归因。

3. **使用 user simulator。**
   用户不是一次性给出完整需求，而是根据对话逐步暴露约束。

4. **使用 rubric-based sliding-window evaluator。**
   把完整轨迹按窗口评估，每个窗口更新相关 rubrics。

5. **使用 all-or-nothing success policy。**
   所有 required rubrics 都满足才算任务成功，同时保留部分得分用于分析。

6. **重复运行，报告稳定性。**
   通过 `Avg@k / Pass@k / Pass^k` 区分“偶尔能做对”和“稳定能做对”。

### 4.2 辅助参考：Agentic Design Patterns 的评测思想

`5-evaluate/RAG测评.md` 和 `5-evaluate/eval_plan.md` 中也提到 Agentic Design Patterns 的评测思想：Agent 系统除了传统工程指标，还要关注语义质量、工具调用轨迹、RAG/知识使用、LLM-as-Judge 等 Agent 特有指标。

本框架吸收的点是：

- 传统工程指标：延迟、token、成本、错误率。
- Agent 特有指标：响应质量、工具轨迹、状态变化、多轮一致性、LLM-as-Judge。

---

## 5. 当前框架的整体流程

完整流程可以讲成 7 步：

```text
1. 加载任务集
   ↓
2. 初始化 CompanionState
   ↓
3. LLM/Rule 用户模拟器发起用户消息
   ↓
4. Companion Agent 执行一轮或多轮任务
   ↓
5. 记录完整 trajectory：用户消息、Agent 回复、工具调用、状态快照
   ↓
6. Rule / LLM / Hybrid evaluator 按 rubrics 打分
   ↓
7. 汇总 strict、rubric、tool、dimension、Avg@k、Pass@k、Pass^k
```

对应代码：

| 环节 | 文件 |
|---|---|
| 评测主入口 | `5-evaluate/companion_eval_pipeline.py` |
| 任务集 | `5-evaluate/companion_tasks/` |
| Agent 本体 | `7-companion-agent/companion_agent.py` |
| 状态对象 | `7-companion-agent/models.py` |
| 工具实现 | `7-companion-agent/tools/` |
| token/cost 统计 | `7-companion-agent/token_costing.py` |
| 输出目录 | `5-evaluate/companion_eval_runs/` |

---

## 6. 任务集设计

当前任务集是 v0.2：

```text
10 个城市 × 3 个任务 = 30 个任务
```

城市覆盖：

```text
Beijing / Shanghai / Chengdu / Chongqing / Guangzhou
Shenzhen / Hangzhou / Xian / Xiamen / Nanjing
```

任务覆盖：

- 行程重排：时间不够、已完成/跳过节点、must-visit 保留。
- 天气扰动：下雨、室内替代、减少户外步行。
- 老人/行动限制：体力下降、步行风险、休息点。
- 应急场景：胸闷、走失、手机没电、拥挤场景。
- 搜索推荐：附近餐厅/咖啡/休息点，结合口味、距离、家庭适配。
- deadline 协调：赶火车、晚餐预约、闭馆风险。

每个任务包含：

| 字段 | 含义 |
|---|---|
| `initial_state` | 初始城市、行程、同行人、已完成节点等 |
| `user_scenario` | 模拟用户完整隐藏任务 |
| `first_user_message` | 第一轮用户输入 |
| `expected_trajectory` | 必须满足的意图和工具调用 |
| `required_rubrics` | 原子评测标准 |
| `failure_tags` | 失败归因标签 |

---

## 7. Rubric 设计：为什么用原子标准

一个任务不会只写“是否回答得好”，而是拆成多个原子 rubrics。

示例：

```json
{
  "key": "extract_time_budget",
  "dimension": "reasoning",
  "rubric": "Agent extracts the 4-hour remaining time budget."
}
```

这样设计有三个原因：

1. **可解释。**
   总分低时能知道是哪条能力没过。

2. **可复查。**
   可以回到 `trajectories.jsonl` 看证据。

3. **可迭代。**
   失败项可以直接变成下一轮 prompt、工具、状态机优化目标。

三类维度：

| 维度 | 关注点 | 示例 |
|---|---|---|
| `reasoning` | 是否理解约束并做正确决策 | 时间预算、deadline、must-visit、安全优先级 |
| `tool` | 是否正确选择工具和参数 | replan、route、weather、candidate search |
| `interaction` | 是否会多轮对话和给可执行建议 | 主动澄清、记住偏好、解释下一步 |

---

## 8. 三种运行模式

### 8.1 离线规则模式：快速 baseline

用途：

- 本地快速回归。
- 不消耗 LLM token。
- 先验证任务集和工具路径。

命令：

```bash
python 5-evaluate/companion_eval_pipeline.py ^
  --num-trials 1 ^
  --max-turns 6 ^
  --simulator rule ^
  --evaluator rule ^
  --no-agent-llm
```

含义：

| 参数 | 含义 |
|---|---|
| `--simulator rule` | 用户由规则脚本模拟 |
| `--evaluator rule` | 裁判由确定性规则判断 |
| `--no-agent-llm` | Agent 本人不调用 LLM |

适合汇报为：**离线确定性 baseline**。

---

### 8.2 全 LLM 模式：真实 Agent 轨迹评测

用途：

- 测真实 LLM Agent 能力。
- 用户、Agent、裁判都调用 LLM。
- 更接近线上多轮对话。

命令：

```bash
python 5-evaluate/companion_eval_pipeline.py ^
  --num-trials 4 ^
  --max-turns 6 ^
  --simulator llm ^
  --evaluator hybrid
```

含义：

| 角色 | 当前行为 |
|---|---|
| 用户 | `--simulator llm`，LLM 用户模拟器 |
| Agent | 不传 `--no-agent-llm`，强制走 agentic LLM |
| 裁判 | `--evaluator hybrid`，规则 + LLM sliding-window judge |

适合汇报为：**全功能 LLM benchmark**。

---

### 8.3 Hybrid 裁判模式：兼顾稳定和语义判断

`--evaluator hybrid` 不是纯 LLM 裁判，而是：

```text
确定性检查 + LLM sliding-window judge
```

为什么不用纯 LLM：

- 工具是否调用、工具名是否正确，这类事实可以由规则稳定判断。
- 语义是否满足 rubric、是否考虑老人限制，这类问题更适合 LLM judge。

因此 hybrid 模式更适合正式汇报。

---

## 9. 输出文件怎么读

每次运行会生成：

```text
5-evaluate/companion_eval_runs/<run_id>/
├── summary.json
├── trial_results.jsonl
└── trajectories.jsonl
```

### 9.1 `summary.json`

用于 PPT 汇总页。

重点字段：

| 字段 | 含义 |
|---|---|
| `strict_success_rate` | 所有 required rubrics 全过的比例 |
| `avg_rubric_score` | 平均 rubric 通过率 |
| `avg_tool_success` | 必须工具调用的通过率 |
| `dimension_scores.reasoning` | 推理维度平均得分 |
| `dimension_scores.tool` | 工具维度平均得分 |
| `dimension_scores.interaction` | 交互维度平均得分 |
| `pass_at_k` | k 次中至少成功一次的比例 |
| `pass_all_k` | k 次全部成功的比例 |
| `total_token_usage` | Agent + evaluator 的总 token/cost |

### 9.2 `trial_results.jsonl`

用于失败分析页。

重点字段：

| 字段 | 含义 |
|---|---|
| `task_id` | 任务编号 |
| `strict_success` | 单次 trial 是否严格成功 |
| `failed_rubrics` | 失败的原子标准 |
| `rubric_details` | 每条 rubric 的判定和理由 |
| `failure_tags` | 失败归因标签 |
| `token_usage` | Agent 本人的 token 使用 |

### 9.3 `trajectories.jsonl`

用于复盘证据页。

它记录：

- 用户说了什么。
- Agent 回了什么。
- Agent 调了什么工具。
- 工具参数是什么。
- 工具结果是什么。
- 状态怎么变化。

如果老板问“为什么这个 case 失败”，就从这里拿证据。

---

## 10. 指标解释：PPT 可直接使用

### 10.1 `strict_success_rate`

所有 required rubrics 都通过才算成功。

适合回答：

```text
这个 Agent 在严格业务标准下，有多少任务能完整完成？
```

### 10.2 `avg_rubric_score`

统计所有原子 rubrics 的平均通过率。

适合回答：

```text
即使任务没完全成功，它完成了多少关键步骤？
```

### 10.3 `avg_tool_success`

统计必要工具调用是否完成。

适合回答：

```text
Agent 是不是会正确使用工具，而不是只靠语言生成？
```

### 10.4 `dimension_scores`

分成 reasoning / tool / interaction。

适合回答：

```text
失败主要是推理问题、工具问题，还是交互问题？
```

### 10.5 `Avg@k / Pass@k / Pass^k`

多次运行稳定性指标。

| 指标 | 含义 | 解读 |
|---|---|---|
| `Avg@k` | k 次平均成功率 | 平均水平 |
| `Pass@k` | k 次至少成功一次 | 有没有可能做对 |
| `Pass^k` | k 次全部成功 | 是否稳定可靠 |

对 Agent 来说，`Pass^k` 很重要，因为线上不能依赖“偶尔做对”。

---

## 11. 当前已验证状态

当前已经验证：

1. **离线规则跑分可用。**
   已得到 baseline：`strict=23.3% / rubric=50.1% / tool=31.7%`。

2. **LLM simulator + LLM judge 已跑通。**
   修复了 `gpt-5-mini` 对显式 `temperature=0.0/0.2` 不兼容的问题。现在遇到 temperature unsupported 会自动去掉 temperature 重试。

3. **Agent 本人 LLM 路径已纳入测评。**
   评测中不传 `--no-agent-llm` 时，会强制 Companion Agent 走 agentic LLM，而不是被确定性任务流截走。

4. **全 LLM 单任务 smoke 已通过。**
   `compat_true_full_llm_smoke` 中 Agent 本人真实调用 LLM：

```text
agent token_usage:
llm_call_count = 1
total_tokens = 1765

total_token_usage:
llm_call_count = 2
total_tokens = 5605
```

5. **单元测试通过。**

```text
23 passed
```

---

## 12. 标准操作流程

### 12.1 前置检查

在项目根目录运行：

```bash
python -m py_compile 5-evaluate/companion_eval_pipeline.py 7-companion-agent/companion_agent.py
```

再进入 `7-companion-agent` 跑单测：

```bash
cd 7-companion-agent
python -m pytest tests/ -q
cd ..
```

期望：

```text
23 passed
```

### 12.2 跑离线 baseline

```bash
python 5-evaluate/companion_eval_pipeline.py ^
  --num-trials 1 ^
  --max-turns 6 ^
  --simulator rule ^
  --evaluator rule ^
  --no-agent-llm ^
  --out-dir 5-evaluate/companion_eval_runs/rule_baseline
```

### 12.3 跑全 LLM smoke

先跑单任务，确认三方 LLM 都能调用：

```bash
python 5-evaluate/companion_eval_pipeline.py ^
  --task-id companion_beijing_001 ^
  --num-trials 1 ^
  --max-turns 3 ^
  --simulator llm ^
  --evaluator hybrid ^
  --out-dir 5-evaluate/companion_eval_runs/full_llm_smoke
```

检查：

- `summary.json` 里 `config.agent_llm_enabled = true`
- `summary.json` 里 `evaluation_llm_token_usage.llm_call_count > 0`
- `trial_results.jsonl` 里 `token_usage.llm_call_count > 0`

这三项同时满足，才说明用户、裁判、Agent 本人都进入了 LLM 测试。

### 12.4 跑正式全量 LLM benchmark

```bash
python 5-evaluate/companion_eval_pipeline.py ^
  --num-trials 4 ^
  --max-turns 6 ^
  --simulator llm ^
  --evaluator hybrid ^
  --out-dir 5-evaluate/companion_eval_runs/full_llm_k4
```

这才是适合最终汇报的正式跑分。

---

## 13. PPT 第一部分建议页结构

### 第 1 页：为什么需要专门测评 Companion Agent

要点：

- 旅行陪伴是动态、多轮、工具密集型任务。
- 只看最终回答无法发现过程错误。
- 风险来自推理、工具、交互三类能力。
- 因此需要轨迹级、rubric 化、可归因的测评框架。

### 第 2 页：参考方法

要点：

- 参考 VitaBench。
- 核心思想：环境 + 模拟用户 + 工具轨迹 + rubric checklist + sliding-window judge。
- 从单轮问答评测升级为真实任务过程评测。

### 第 3 页：三段论测评策略

三段：

1. 离线规则基线：验证基本盘。
2. 全 LLM 轨迹仿真：验证真实 Agent 能力。
3. 轨迹级归因分析：定位失败原因。

### 第 4 页：评测闭环

可以画成：

```text
任务集构建
  → 用户模拟
  → Agent 执行
  → 工具调用
  → 轨迹记录
  → rubric 评估
  → 指标汇总
  → 失败归因
  → 下一轮优化
```

### 第 5 页：指标体系

分三层：

| 层级 | 指标 | 回答的问题 |
|---|---|---|
| 任务成功 | `strict_success_rate` / `Pass@k` | 是否完整完成任务 |
| 过程质量 | `rubric_score` / `dimension_scores` | 哪些能力强弱 |
| 工程可用 | token / latency / cost | 是否可上线、是否可扩展 |

### 第 6 页：为什么这个框架可持续

要点：

- 任务集可扩展。
- 运行脚本自动化。
- 结果可复查。
- 失败可归因。
- 能同时支持离线回归和全 LLM benchmark。

---

## 14. 汇报时可以直接说的话

> 我们没有只用最终回答来评价陪伴 Agent，而是搭了一套轨迹级测评框架。原因是陪伴 Agent 的核心风险在过程里：它是否理解现场约束，是否主动澄清，是否正确调用工具，是否在老人、天气、deadline 等动态场景下做出安全决策。

> 整个测评策略分三层。第一层是离线规则基线，用来快速验证任务集、工具链和状态流转；第二层是全 LLM 轨迹仿真，让用户、Agent 本体和裁判都由 LLM 驱动，接近真实线上交互；第三层是轨迹级归因分析，把失败拆成推理、工具、交互三类，指导后续迭代。

> 这套方法参考了 VitaBench 的设计：不是只看最终答案，而是在真实任务环境中记录完整 trajectory，用原子 rubrics 和 sliding-window LLM judge 判断每个目标是否完成，并通过多次运行的 Avg@k、Pass@k、Pass^k 衡量稳定性。

---

## 15. 当前下一步

第一部分策略说明完成后，第二部分建议直接接实际结果：

1. 展示离线 baseline：`strict=23.3% / rubric=50.1% / tool=31.7%`。
2. 展示全 LLM smoke 已经跑通，证明三方 LLM 测评链路成立。
3. 跑正式 `full_llm_k4`，输出正式 benchmark。
4. 按城市、任务类型、reasoning/tool/interaction 三维分析失败。
5. 给出下一轮优化优先级：优先修工具调用，还是推理 prompt，还是交互澄清策略。
