# 参考代码索引

> 目的：快速定位可复用的代码片段，避免每次重新扫描文件。
> 覆盖：`3.chatbot/`、`5.agents/`、`8.multi-agent/`

---

## 快速查找表（按需求找文件）

| 我想要... | 去哪个文件 | 找什么 |
|---|---|---|
| 初始化 Azure OpenAI / Foundry 客户端 | `3.chatbot/azure_openai_client.py` | `AzureOpenAIClient.__init__` |
| 多轮对话状态管理（conversation_history） | `3.chatbot/chatbot_simple.py` | `Chatbot.chat()` |
| 长对话 token 超限时裁剪 | `3.chatbot/chatbot2.py` | `remove_oldest_messages()` |
| 长对话 token 超限时摘要压缩（推荐） | `3.chatbot/chatbot3_summarization.py` | `summarize_old_messages()` |
| Foundry 端点客户端初始化 | `3.chatbot/chatbot_foundry_openai.py` | `main()` 前几行 |
| Streamlit UI 骨架（含 session_state） | `3.chatbot/chatbot2_streamlit.py` | `_init_state()` + `main()` |
| **工具调用 while 循环（核心）** | `5.agents/agent_function_calling_v2.py` | `while True` 那段 |
| 工具路由字典（tool_impls） | `5.agents/agent_function_call_db.py` | `tool_impls = {...}` |
| Streamlit + Agent 完整架构 | `5.agents/agent_function_call_db_streamlit.py` | `AgentRuntime` + `TurnResult` + `_run_turn()` |
| Chat Completions API function calling（非 Agents SDK） | `5.agents/function_call_db.py` | `run_conversation()` |
| WebSearchTool + streaming | `5.agents/agent_web_search.py` | `main()` |
| MCP 人工审批流程 | `5.agents/agent_foundry_iq.py` | `mcp_approval_request` 处理段 |
| `@tool` 装饰器 + session + streaming 快速入门 | `8.multi-agent/af-azure-openai-agent.py` | 全文，按 section 找 |
| Foundry 客户端（AzureCliCredential，无 API key） | `8.multi-agent/af-foundry-agent.py` | `FoundryChatClient` 初始化 |
| 条件路由工作流（查到有货→预订，没货→替代） | `8.multi-agent/af-hotel-booking.py` | `WorkflowBuilder` + `.add_edge()` |
| 并发多 Agent 扇出 | `8.multi-agent/concurrent_agents.py` | `ConcurrentBuilder` |
| 并发查询 + LLM 聚合结果 | `8.multi-agent/concurrent_custom_aggregator.py` | `with_aggregator()` |
| Triage → 专业 Agent 路由（Handoff） | `8.multi-agent/handoff_simple.py` | `HandoffBuilder` + `with_start_agent()` |
| 自治 Agent（不等用户，自己循环） | `8.multi-agent/handoff_autonomous.py` | `with_autonomous_mode()` |
| 人工审核计划后再执行 | `8.multi-agent/magentic_human_plan_review.py` | `enable_plan_review=True` |
| 工具调用需要人工批准 | `8.multi-agent/sequential_builder_tool_approval.py` | `@tool(approval_mode="always_require")` |
| 顺序 Agent 流水线（A做完B做） | `8.multi-agent/sequential_agents.py` | `SequentialBuilder` |
| 顺序流水线 + 中间人工反馈 | `8.multi-agent/sequential_request_info.py` | `with_request_info()` |
| GroupChat（多 Agent 轮流发言） | `8.multi-agent/group_chat_agent_manager.py` | `GroupChatBuilder` + `orchestrator_agent` |

---

## 3.chatbot — 文件详情

### `azure_openai_client.py`
**核心类：** `AzureOpenAIClient`
**作用：** 底层 LLM 客户端封装，所有其他文件依赖它。

关键方法：
- `get_response(messages)` → 调用 `chat.completions.create`，返回 response 对象
- `get_response_to_image(system, prompt, image_path)` → 多模态，图片 base64 编码
- `generate_embedding(text)` → embeddings API
- `get_token_usage(response)` → 解析 usage，计算成本
- `check_content_filter(response)` → Azure 内容过滤

```python
# 初始化方式
client = AzureOpenAIClient()  # 自动从 .env 读取

# 调用方式
response = client.get_response(messages)
text = response.choices[0].message.content
```

---

### `chatbot_simple.py`
**核心类：** `Chatbot`
**作用：** 最干净的多轮对话骨架。

```python
# 核心结构
class Chatbot:
    conversation_history = []   # 存 {role, content} 列表

    def chat(self, user_input):
        messages = [{"role": "system", "content": self.system_message}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_input})
        response = self.client.get_response(messages)
        # 追加到历史
        self.conversation_history.append({"role": "user", "content": user_input})
        self.conversation_history.append({"role": "assistant", "content": reply})
```

---

### `chatbot2.py`
**作用：** 在 chatbot_simple 基础上加 token 预算管理。

关键函数：
- `count_chat_tokens(messages, model)` → 精确计算 prompt token 数
- `remove_oldest_messages(messages, token_limit, model)` → 从 index 1 起删最老的 user+assistant 对

---

### `chatbot3_summarization.py`
**作用：** 用摘要替代删除，保留长对话的语义。

```python
def summarize_old_messages(messages, client, model):
    # 保留 system + 最近4条，其余发给 LLM 做摘要
    summary = client.get_response(summary_prompt)
    new_messages = [system_msg,
                    {"role": "system", "content": f"Previous summary: {summary}"}]
    new_messages.extend(recent_4)
    return new_messages
```

---

### `chatbot_foundry_openai.py`
**作用：** 使用 Foundry 端点（非 Azure OpenAI 直连）的客户端初始化。

```python
client = OpenAI(
    base_url="https://" + os.getenv("FOUNDRY_PROJECT_RESOURCE") + ".openai.azure.com/openai/v1/",
    api_key=os.getenv("FOUNDRY_PROJECT_API_KEY")
)
```

---

### `chatbot2_streamlit.py`
**作用：** Streamlit UI 完整骨架，含 session_state 和 token 侧边栏。

```python
# session_state 初始化
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# 渲染历史消息
for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
```

---

## 5.agents — 文件详情

### `agent_function_calling_v2.py` ⭐ 最重要
**作用：** 标准工具调用循环，处理多工具连续调用。

```python
# 核心 while 循环
while True:
    pending_calls = [item for item in response.output if item.type == "function_call"]
    if not pending_calls:
        break
    tool_outputs = []
    for item in pending_calls:
        result = _run_tool_call(item)
        tool_outputs.append({
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": result
        })
    response = openai_client.responses.create(input=tool_outputs, ...)
```

**注意：** `agent_function_calling.py`（v1）有 bug，只处理一次，不用它。

---

### `agent_function_call_db.py`
**作用：** 工具路由字典模式，避免大量 if-elif。

```python
tool_impls = {
    "get_movie":    get_movie,
    "add_movie":    add_movie,
    "delete_movie": delete_movie,
}

def _run_tool_call(item):
    fn = tool_impls[item.name]
    args = json.loads(item.arguments)
    return json.dumps(fn(**args), ensure_ascii=False)
```

---

### `agent_function_call_db_streamlit.py` ⭐
**作用：** 最完整的 Streamlit + Agent 架构，三层分离设计。

```python
@dataclass
class TurnResult:
    output_text: str
    logs: list
    failed: bool
    error_message: str

@dataclass
class AgentRuntime:
    openai_client: object
    agent_name: str
    conversation_id: str
    tool_impls: dict

async def _run_turn(runtime, user_input, progress_callback=None) -> TurnResult:
    # 完整工具循环 + 进度回调
    ...
```

---

### `function_call_db.py`
**作用：** Chat Completions API（非 Agents SDK）的 function calling 写法。

```python
# 工具定义为 dict list
response = client.chat.completions.create(
    model=..., messages=messages, tools=tools, tool_choice="auto"
)
# 处理 tool_calls
if response.choices[0].message.tool_calls:
    for tool_call in response.choices[0].message.tool_calls:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        result = tool_impls[name](**args)
        messages.append({"role": "tool", "tool_call_id": tool_call.id,
                          "name": name, "content": json.dumps(result)})
```

---

### `agent_web_search.py`
**作用：** WebSearchTool + streaming 响应。

```python
agent = project.agents.create_version(
    definition=PromptAgentDefinition(
        model="gpt-5-mini",
        tools=[WebSearchTool(user_location=WebSearchApproximateLocation(city="Hong Kong"))]
    )
)
stream = openai.responses.create(stream=True, input="...", extra_body={...})
for event in stream:
    if event.type == "response.output_text.delta":
        print(event.delta, end="")
```

---

## 8.multi-agent — 文件详情

### `af-azure-openai-agent.py` ⭐ 入门必读
**作用：** agent_framework 所有基础用法合集。

```python
# 初始化
client = OpenAIChatClient(model=..., azure_endpoint=..., api_key=..., api_version=...)

# 注册工具
@tool
def get_weather(location: str) -> str:
    return f"The weather in {location} is sunny."

agent = client.as_agent(instructions="...", tools=get_weather)

# 多轮 session
session = agent.create_session()
r1 = await agent.run("My name is Alice", session=session)
r2 = await agent.run("What's my name?", session=session)  # 记得

# Streaming
async for chunk in agent.run("Tell me a story.", stream=True):
    if chunk.text:
        print(chunk.text, end="")

# 内置工具
web_search = client.get_web_search_tool()
code_interpreter = client.get_code_interpreter_tool()
```

---

### `af-hotel-booking.py` ⭐
**作用：** 条件路由工作流，根据查询结果走不同分支。

```python
# Pydantic 结构化输出
class BookingResult(BaseModel):
    has_availability: bool
    destination: str

# 条件分支
workflow = (
    WorkflowBuilder(start_executor=availability_agent, output_executors=[display])
    .add_edge(availability_agent, booking_agent,     condition=has_availability)
    .add_edge(availability_agent, alternative_agent, condition=no_availability)
    .build()
)
```

---

### `handoff_simple.py` ⭐
**作用：** Triage Agent 路由到专业 Agent，完成后返回。

```python
workflow = (
    HandoffBuilder(
        participants=[triage, refund_agent, order_agent, support_agent],
        termination_condition=lambda conv: "complete" in conv[-1].text.lower(),
    )
    .with_start_agent(triage)
    .build()
)
result = await workflow.run(user_message)
```

---

### `concurrent_custom_aggregator.py` ⭐
**作用：** 并发多 Agent 查询 + LLM 聚合结果。

```python
async def summarize_results(results):
    # 合并所有 agent 的输出成一个回答
    response = await client.get_response([system_msg, combined_user_msg])
    return response.messages[-1].text

workflow = ConcurrentBuilder(
    participants=[researcher, marketer, legal]
).with_aggregator(summarize_results).build()
```

---

### `sequential_agents.py`
**作用：** 顺序流水线，A 完成后 B 处理 A 的输出。

```python
workflow = SequentialBuilder(participants=[writer, reviewer]).build()
result = await workflow.run("Write a tagline...")
```

---

### `sequential_builder_tool_approval.py`
**作用：** 敏感工具调用前需要人工审批。

```python
@tool(approval_mode="always_require")
def execute_query(query: str) -> str: ...

# 流程：LLM 想调用 → 暂停 → 等人类批准 → 继续
responses[req_id] = request.to_function_approval_response(approved=True)
```

---

### `sequential_request_info.py`
**作用：** 顺序流水线中某个 Agent 完成后等待人工反馈再继续。

```python
workflow = SequentialBuilder(
    participants=[drafter, editor, finalizer]
).with_request_info(agents=["editor"]).build()
```

---

### `group_chat_agent_manager.py`
**作用：** 多 Agent 轮流发言，由一个 orchestrator Agent 动态选发言者。

```python
workflow = GroupChatBuilder(
    participants=[researcher, writer],
    orchestrator_agent=orchestrator,
    termination_condition=lambda msgs: len(msgs) >= 4,
).build()
```

---

### `magentic_human_plan_review.py`
**作用：** 执行复杂任务前，先生成计划让人审核再执行。

```python
workflow = MagenticBuilder(
    participants=[researcher, coder],
    enable_plan_review=True,
    max_round_count=10,
).build()
# 收到 plan_review_request → 批准或修改
responses[req_id] = request.approve()
responses[req_id] = request.revise("去掉第三步，改成...")
```
