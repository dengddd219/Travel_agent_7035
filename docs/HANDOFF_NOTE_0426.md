# A 组任务交接说明（2026-04-26）

## 一、已完成的工作

### 1. RAG 检索质量（不涉及 LLM）
- **HR@5 = 93.5%, MRR = 0.98**（V7 pipeline，40 条 query，4 城市）
- 报告位置：`1-rag_pipeline_delivery/evaluation_report.md`
- 此指标为纯检索层面评测，不依赖 LLM，数据稳定可靠。

### 2. Step 3/5/6 代码实现
| Step | 文件 | 内容 |
|------|------|------|
| Step 3 跨区硬约束 | `3-travel_planner/travel_planner/planner.py` | `MAX_DISTRICTS_PER_DAY=3`，第三区≤5km，cooccurrence_boost=0.8 |
| Step 5 内容配额 | `3-travel_planner/travel_planner/tools/strategy_rag_adapter.py` | `_apply_content_type_quota()` 保证 route_plan≥2、pitfall≥1 |
| Step 6 路线质量指标 | `5-evaluate/ragas_evaluator.py` | `_compute_route_quality()` + 覆盖率汇总 |

### 3. Companion Agent 评测（已全部跑通）

**无 LLM 确定性评测：**
- strict=23.3%, rubric=50.1%, tool=31.7%
- 结果：`5-evaluate/companion_eval_runs/20260426_175115/`

**全功能 LLM 评测（4 trials × 30 tasks = 120 轮）：**
- strict=28.3%, rubric=59.8%, tool=41.3%
- interaction=72.1%, reasoning=70.6%
- pass@4=46.7%
- Token 消耗：$0.31 / ¥2.25
- 结果：`5-evaluate/companion_eval_runs/20260426_175454/`

### 4. CLAUDE.md 已更新
- 包含评测现状、迭代历史、文件速查。

### 5. 后端 /api/companion 路由已注册
- PID 8525 运行中，`/api/companion` 可用。

---

## 二、未完成 / 已知问题

### RAGAS 生成质量评测（跑通但结果无效）

**问题描述：**
gpt-5-mini 是推理模型（reasoning model），与普通 GPT-4o 不同：
1. **chat.completions API 返回空 content**：gpt-5-mini 不兼容传统 chat 接口，content 字段始终为空字符串。
2. **Responses API 的 reasoning token 问题**：模型先消耗大量 token 做内部推理（用户不可见），如果 `max_output_tokens` 设太小（如 500），推理吃掉全部额度，实际回答为空。
3. **项目级 endpoint 不可用**：`.env` 中的 `FOUNDRY_PROJECT_ENDPOINT`（含 `/api/projects/...`）不支持任何 api-version，必须用资源级 URL（`https://applied-llm-resource.services.ai.azure.com`）。

**当前评测脚本状态：**
- 已改为使用 Responses API + 资源级 endpoint（`5-evaluate/ragas_evaluator.py`）
- 但 `max_output_tokens` 仍需调大 + 加 `reasoning={"effort": "low"}`
- 12 条 case 检索全部正常，LLM 生成部分因上述原因结果为 0

**修复方案（预计改 2 行代码即可）：**
```python
# 在 _generate_answer 和 _judge 的 responses.create() 中：
max_output_tokens=4096,          # 从 500 改大
reasoning={"effort": "low"},     # 减少推理消耗
```

### 主 Agent 评测
- 完全没开始。

### 前端陪伴 Agent 验证
- 后端路由已注册，但实际前端测试未做。

### 规划输出迭代
- 未进一步迭代。

---

## 三、API 调用兼容性速查

| 调用方式 | endpoint 级别 | api-version | 结果 |
|----------|-------------|-------------|------|
| `responses.create()` | 资源级 | `2025-03-01-preview` | ✅ 有效 |
| `responses.create()` | 项目级 | 任意 | ❌ 400 |
| `chat.completions` | 资源级 | 任意 | ⚠️ 200 但 content 为空 |
| `chat.completions` | 项目级 | 任意 | ❌ 400 |

资源级 = `https://applied-llm-resource.services.ai.azure.com`
项目级 = `https://applied-llm-resource.services.ai.azure.com/api/projects/xuejun-deng-project`

---

## 四、文件变更清单

| 文件 | 变更 |
|------|------|
| `5-evaluate/ragas_evaluator.py` | Responses API 适配 + route_quality 指标 |
| `5-evaluate/ragas_result.json` | RAGAS 评测结果（当前全 0，待修复重跑）|
| `3-travel_planner/travel_planner/planner.py` | Step 3 跨区硬约束 |
| `3-travel_planner/travel_planner/tools/strategy_rag_adapter.py` | Step 5 内容配额 |
| `5-evaluate/companion_eval_runs/` | Companion 评测结果 |
| `CLAUDE.md` | 全面更新 |
