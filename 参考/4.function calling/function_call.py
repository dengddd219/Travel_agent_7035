# 疑问：
# 1. 为什么要定义tool
#   1. tool得到的数据可以是线上的API获取实时知识库，而大模型本身是截至时间的知识库训练结果，所以接入API使其获取实时知识
#   2. 并且工具本身也是大模型的一部分，所以需要定义tools
#   3. 需要告诉他我有一个工具，怎么使用，避免产生幻觉
# 2. 整个体现function calling 的流程是什么
# 3. 两次的request
# 4. completion是什么

# LLM的作用
# 我们发给LLM的东西只有tools
# LLM只负责他自己选择使用哪个工具，以及工具的参数
# 工具的返回值会再返回给LLM，LLM再根据返回值生成最终的response
# 整个过程是LLM在选择使用哪个工具，以及工具的参数，工具的返回值会再返回给LLM，LLM再根据返回值生成最终的response
# 决定是否调用哪个工具、构造参数（tool call 规划）
# 读你执行工具后给它的结果，生成一段对用户友好的自然语言回答

# 这个文件：
# 1. 定义了一个工具，get_current_time
# 2. 定义了tools，并告诉LLM我有一个工具，怎么使用
# 3. 第一次request，LLM选择使用哪个工具，以及工具的参数
# 4. 第二次request，工具的返回值会再返回给LLM，LLM再根据返回值生成最终的response
# 5. 最终的response会返回给用户
# 6. 整个过程是LLM在选择使用哪个工具，以及工具的参数，工具的返回值会再返回给LLM，LLM再根据返回值生成最终的response
# 7. 决定是否调用哪个工具、构造参数（tool call 规划）
# 8. 读你执行工具后给它的结果，生成一段对用户友好的自然语言回答

# # 流程：
# 这份代码展示了一个非常标准且完整的 **Function Calling（函数调用）** 架构。为了让你更直观地理解，我们可以将整个程序看作是一个协同工作的团队。

# 以下是代码中涉及的**核心角色及其作用**，以及**完整的交互流程**总结。

# ## 核心角色与作用

# 在这个“团队”中，有四个关键角色在发挥作用：

# * **User（用户）：**
#     * **作用：** 提出初始需求。在代码中体现为 `messages` 列表里的第一句话：“What's the current time in San Francisco, Tokyo, and Paris?”。
# * **Application / Code（你的 Python 程序）：**
#     * **作用：** 它是整个流程的“大管家”和调度中心。
#     * **具体任务：** 负责加载 API 密钥、定义工具说明书（`tools` 列表）、维护对话历史（`messages`）、发送网络请求给大模型，以及**真正在本地执行代码**。
# * **LLM / Model（大语言模型）：**
#     * **作用：** 充当“大脑”和“翻译官”。
#     * **具体任务：** 第一次请求时，它负责阅读问题和工具说明书，判断需要用什么工具，并提取出准确的参数（例如识别出需要查询三个城市）；第二次请求时，它负责把生硬的机器数据（JSON 格式的时间）转化为人类易读的自然语言。
# * **Tool / Local Function（本地函数）：**
#     * **作用：** 补足大模型能力的“外接组件”。
#     * **具体任务：** 在代码中就是 `get_current_time` 函数。它负责根据大模型给出的参数（城市名），执行具体的逻辑（查时区），并返回真实的数据结果。

# ---

# ## 完整执行流程

# 整个 Function Calling 的核心在于**“两问两答”**。以下是代码跑起来后的标准六步流程：



# * **第一步：环境与数据准备**
#     程序启动，加载环境变量（API Key 等），建立大模型客户端（`client`）。同时，把用户的提问放入对话历史 `messages` 中，并严格按照大模型要求的 JSON 格式定义好 `tools`（明确告诉模型 `get_current_time` 的存在和用法）。
# * **第二步：发起第一次请求（意图识别）**
#     程序将“用户的提问”和“工具说明书”打包，发送给大模型。此时的重点是 `tool_choice="auto"`，意味着让模型自己决定用不用工具。
# * **第三步：模型返回调用指令**
#     模型发现需要查时间，于是**不生成最终答案**，而是返回一个包含了 `tool_calls` 的特殊响应。这个响应明确指示程序：“请调用 `get_current_time` 函数，并传入 San Francisco、Tokyo、Paris 这些参数”。程序会将这条指令追加到 `messages` 历史中。
# * **第四步：本地拦截并执行函数**
#     程序通过 `if response_message.tool_calls:` 拦截到了大模型的指令。程序通过循环，解析出 JSON 参数，真正在本地运行了 `get_current_time(location="...")`，计算出具体的当前时间。
# * **第五步：组装执行结果**
#     程序将本地函数执行后得到的时间结果拼装成一个特定的字典格式（`role: "tool"`，并附带对应的 `tool_call_id`），再次追加到 `messages` 对话历史中。至此，`messages` 里包含了：用户问题、模型调用指令、本地真实数据。
# * **第六步：发起第二次请求（总结输出）**
#     程序带着这份极其详尽的 `messages` 上下文，**再次**请求大模型（这次不需要带 `tools` 参数了）。大模型读取到了真实的本地时间数据，将其组织、润色，最终输出“旧金山现在是XX点，东京是XX点...”的自然语言文本，程序将其打印展示给用户。

# 简单来说，整个过程就是：**你问模型怎么做 -> 模型给你列出参数指令 -> 你自己照做并拿到数据 -> 你把数据丢给模型 -> 模型帮你总结出漂亮话。**
# 总而言之，就是你自己定义好具备功能的function，然后LLM 根据query识别需要用什么function，在tools中说明，然后调用function，然后用自然语言输出给用户

import os
import json
from openai import AzureOpenAI
from openai import OpenAI
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Create a .env File: In your project directory, create a file named .env.
# Add Variables: Inside the .env file, define your variables in the format: NAME=VALUE.
# For example, you can define the AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY variables.
# Load Variables in Your Code: Use the python-dotenv package to load these variables in your Python script.
load_dotenv()  # Load environment variables from .env file
####两种方案
# 1. Azure OpenAI API (old; API key shared by instructor for all students to use)
# Initialize the Azure OpenAI client
# client = AzureOpenAI(
#     azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
#     api_key=os.getenv("AZURE_OPENAI_API_KEY"),
#     api_version=os.getenv("AZURE_OPENAI_API_VERSION")
# )
# Define the deployment you want to use for your chat completions API calls
# deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT") # gpt-5-mini, gpt-4.1-mini, gpt-4.1, etc.

# 2. Microsoft Foundry OpenAI API (new; Foundry project API key shared by instructor的URL和API)
# Initialize the Microsoft Foundry OpenAI client
client = OpenAI(
    base_url="https://"+os.getenv("FOUNDRY_PROJECT_RESOURCE")+".openai.azure.com/openai/v1/",
    api_key=os.getenv("FOUNDRY_PROJECT_API_KEY")
)
# Define the deployment you want to use for your chat completions API calls
deployment_name = os.getenv("FOUNDTRY_PROJECT_DEPLOYMENT") # gpt-5-mini, gpt-4.1-mini, etc.

# Simplified timezone data
TIMEZONE_DATA = {
    "tokyo": "Asia/Tokyo",
    "san francisco": "America/Los_Angeles",
    "paris": "Europe/Paris"
}
# 第一个function，简单的python function
def get_current_time(location):
    """Get the current time for a given location"""
    print(f"get_current_time called with location: {location}")
    location_lower = location.lower()

    for key, timezone in TIMEZONE_DATA.items():
        if key in location_lower:
            print(f"Timezone found for {key}")
            current_time = datetime.now(ZoneInfo(timezone)).strftime("%I:%M %p")
            return json.dumps({
                "location": location,
                "current_time": current_time
            })

    print(f"No timezone data found for {location_lower}")
    return json.dumps({"location": location, "current_time": "unknown"})


def run_conversation():
    # Initial user message
    # messages = [{"role": "user", "content": "What's the current time in San Francisco"}]  # Single function call
    messages = [{"role": "user", "content": "What's the current time in San Francisco, Tokyo, and Paris?"}] # Parallel function call with a single tool/function defined

    # Define the function for the model
    tools = [  # 在function calling中，tools是一个列表，列表中包含一个字典，字典中包含一个type和function，需要定义tools，区别于自谦的prompt engineering
        {
            "type": "function",
            "function": {
                "name": "get_current_time",#function name不能随便起名字，
                "description": "Get the current time in a given location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city name, e.g. San Francisco",
                        },
                    },
                    "required": ["location"],
                },
            }
        }
    ]

    # First API call: Ask the model to use the function
    response = client.chat.completions.create(
        model=deployment_name,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )

    # Process the model's response
    response_message = response.choices[0].message
    messages.append(response_message)

    print("Model's response:")
    print(response_message)

    # Handle function calls
    if response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            if tool_call.function.name == "get_current_time":
                function_args = json.loads(tool_call.function.arguments)
                print(f"Function arguments: {function_args}")
                time_response = get_current_time(
                    location=function_args.get("location")
                )
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": "get_current_time",
                    "content": time_response,
                })
    else:
        print("No tool calls were made by the model.")

    # print(messages)

    # Second API call: Get the final response from the model
    final_response = client.chat.completions.create(
        model=deployment_name,
        messages=messages, 
        # 没有tool，你已经得到最终的response了
    )

    return final_response.choices[0].message.content


# Run the conversation and print the result
print(run_conversation())