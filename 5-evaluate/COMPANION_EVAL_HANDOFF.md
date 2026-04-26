# 陪伴 Agent 测评交接文档

> 接收方直接按本文档操作即可跑出测评结果，无需阅读其他文件。

---

## 一、前置确认

### 目录结构（接收时应已存在）

```
Travel_agent_7035/
├── 5-evaluate/
│   ├── companion_eval_pipeline.py   ← 测评主脚本
│   ├── companion_tasks/
│   │   ├── index.json               ← 任务索引（30 个任务，10 城市）
│   │   ├── beijing.json
│   │   ├── shanghai.json
│   │   └── ...（共 10 个城市 JSON）
│   └── companion_eval_runs/         ← 每次运行结果自动写入此处
└── 7-companion-agent/
    ├── companion_agent.py
    ├── config.py
    ├── models.py
    ├── token_costing.py
    ├── tools/
    └── tests/
```

### Python 环境

本项目有两个 Python 环境，**必须用 miniconda**（venv 没有 pytest）：

```bash
# 确认用的是 miniconda Python
C:/Users/<用户名>/miniconda3/python.exe --version
# 应输出 Python 3.13.x
```

---

## 二、运行前检查（30 秒）

先跑单元测试确认代码没有损坏：

```bash
# 在项目根目录 Travel_agent_7035/ 下运行
C:/Users/<用户名>/miniconda3/python.exe -m pytest 7-companion-agent/tests/ -v
```

期望输出：`23 passed in 1.10s`，全绿即可继续。

---

## 三、测评命令

**所有命令必须在项目根目录 `Travel_agent_7035/` 下运行。**

### 模式 A：无 LLM 确定性跑分（推荐优先跑，零配置）

不需要任何 API Key，完全本地运行：

```bash
python 5-evaluate/companion_eval_pipeline.py \
  --num-trials 1 \
  --max-turns 6 \
  --simulator rule \
  --evaluator rule \
  --no-agent-llm
```

Windows cmd 版本（`^` 换行）：

```cmd
python 5-evaluate/companion_eval_pipeline.py ^
  --num-trials 1 ^
  --max-turns 6 ^
  --simulator rule ^
  --evaluator rule ^
  --no-agent-llm
```

- 30 个任务全跑，约 1-2 分钟
- 结果写入 `5-evaluate/companion_eval_runs/<timestamp>/`

### 模式 B：全功能 LLM 跑分（需要 API Key）

先配置环境变量（复制 `.env.example` 为 `.env` 并填写）：

```
# .env（填写以下任一组即可）

# 方式一：标准 OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# 方式二：Azure / Foundry（项目原有配置）
FOUNDRY_PROJECT_API_KEY=...
FOUNDRY_PROJECT_ENDPOINT=...
FOUNDRY_PROJECT_DEPLOYMENT=gpt-4o
```

然后运行标准基准测评（官方推荐配置）：

```bash
python 5-evaluate/companion_eval_pipeline.py \
  --num-trials 4 \
  --max-turns 6 \
  --simulator llm \
  --evaluator hybrid
```

- 30 任务 × 4 trials = 120 条轨迹
- 耗时约 10-20 分钟（取决于 API 延迟）
- **注意**：没有填 Key 时会自动降级为 rule 模式，不会报错崩溃

---

## 四、常用筛选参数

```bash
# 只跑某一城市
python 5-evaluate/companion_eval_pipeline.py --city Beijing --num-trials 1 --simulator rule --evaluator rule --no-agent-llm

# 只跑 1 个任务快速验证
python 5-evaluate/companion_eval_pipeline.py --city Beijing --max-tasks 1 --num-trials 1 --max-turns 3 --simulator rule --evaluator rule --no-agent-llm

# 指定某个具体任务
python 5-evaluate/companion_eval_pipeline.py --task-id companion_beijing_001 --num-trials 1 --simulator rule --evaluator rule --no-agent-llm

# 指定输出目录
python 5-evaluate/companion_eval_pipeline.py --num-trials 1 --simulator rule --evaluator rule --no-agent-llm --out-dir 5-evaluate/companion_eval_runs/my_run
```

---

## 五、读取结果

每次运行在 `5-evaluate/companion_eval_runs/<timestamp>/` 下生成三个文件：

| 文件 | 内容 |
|------|------|
| `summary.json` | **主要结果**，总体指标 + 按城市 + 按任务 |
| `trial_results.jsonl` | 每个 task × trial 的详细得分 |
| `trajectories.jsonl` | 完整交互轨迹（用户消息、Agent 回复、工具调用） |

### 关键指标说明（`summary.json` → `overall`）

| 字段 | 含义 | 期望值 |
|------|------|--------|
| `strict_success_rate` | 所有 rubric 全部通过的比例 | 越高越好 |
| `avg_rubric_score` | 平均 rubric 通过率（允许部分通过）| 越高越好 |
| `avg_tool_success` | 必须工具调用覆盖率 | 越高越好 |
| `pass_at_k` | k 次 trial 中至少 1 次成功的任务比例 | 主要汇报指标 |
| `avg_at_k` | k 次 trial 平均成功率 | 主要汇报指标 |
| `pass_all_k` | k 次 trial 全部成功的任务比例 | 稳定性指标 |

### 示例结果（rule 模式单任务 smoke test）

```json
{
  "strict_success_rate": 1.0,
  "avg_rubric_score": 1.0,
  "avg_tool_success": 1.0,
  "pass_at_k": 1.0,
  "avg_at_k": 1.0,
  "pass_all_k": 1.0
}
```

---

## 六、Simulator / Evaluator 模式对照

| 参数 | 说明 |
|------|------|
| `--simulator rule` | 确定性用户模拟，不调 LLM，CI/离线用 |
| `--simulator llm` | LLM 模拟真实用户，无 Key 时自动降级 rule |
| `--simulator auto` | 有 Key 用 LLM，否则用 rule |
| `--evaluator rule` | 确定性 rubric 检查，不调 LLM |
| `--evaluator hybrid` | 确定性检查 + LLM 裁判，无 Key 时只跑 rule 部分 |
| `--evaluator llm` | 纯 LLM 裁判 |
| `--no-agent-llm` | 强制 Agent 用确定性 fallback（工具调用用 mock 数据） |

---

## 七、任务集说明

- **总计 30 个任务**，覆盖 10 座城市，每城市 3 个
- 城市：Beijing / Shanghai / Chengdu / Chongqing / Guangzhou / Shenzhen / Hangzhou / Xian / Xiamen / Nanjing
- 任务类型覆盖：附近搜索、行程重规划、时间协调、应急处置
- 任务文件位置：`5-evaluate/companion_tasks/<city>.json`

---

## 八、常见问题

**Q：运行时报 `ModuleNotFoundError`**

确认在项目根目录 `Travel_agent_7035/` 下运行，不要在 `5-evaluate/` 或 `7-companion-agent/` 子目录下运行。

**Q：`--simulator llm` 但实际用的是 rule**

正常现象，说明 `.env` 里没有配置有效的 API Key，pipeline 自动降级。检查 `.env` 文件是否存在且 Key 已填写。

**Q：pytest 找不到**

用 miniconda Python，不要用项目 `.venv` 里的 Python：
```bash
C:/Users/<用户名>/miniconda3/python.exe -m pytest 7-companion-agent/tests/ -v
```

**Q：想看单条任务的详细失败原因**

查看 `trial_results.jsonl`，找对应 `task_id`，看 `failed_rubrics` 字段。
