# pip install agent-framework
# 1.0.1
import os
from dotenv import load_dotenv
load_dotenv()

import asyncio
from agent_framework.openai import OpenAIChatClient
from agent_framework import tool

def build_azure_openai_chat_client() -> OpenAIChatClient:
    return OpenAIChatClient(
        model=os.getenv("AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )
    # Azure OpenAI resource would be used

async def azure_openai_chat_example():
    agent = build_azure_openai_chat_client().as_agent(
        name="Joker",
        instructions="You are good at telling jokes.",
    )
    result = await agent.run("Tell me a joke about a pirate.")
    print(result)


async def coding_agent_example():
    client = build_azure_openai_chat_client()
    code_interpreter = client.get_code_interpreter_tool()
    agent = client.as_agent(
        name="CodingAgent",
        instructions="You are a helpful assistant with access to code interpreter.",
        tools=[code_interpreter],
    )
    result = await agent.run("Write and run a Python script that calculates fibonacci numbers.")
    print(result)


async def hosted_tools_example():
    client = build_azure_openai_chat_client()
    code_interpreter = client.get_code_interpreter_tool()
    web_search = client.get_web_search_tool()
    file_search = client.get_file_search_tool(vector_store_ids=["vs_uZCQQLslmx7EJD6Wzl3AJwOB"]) # vector store under Azure OpenAI resource
    mcp_tool_mslearn= client.get_mcp_tool(
        name="Microsoft Learn",
        url="https://learn.microsoft.com/api/mcp",
        approval_mode="never_require",
    ) # no authentication is needed

    agent = client.as_agent(
        name="PowerAgent",
        instructions="You have access to various tools. For questions related to Micorsoft Azure, use the MCP tool.",
        tools=[code_interpreter, web_search, mcp_tool_mslearn, file_search],
    )

    query="Show me the list of Azure OpenAI models available in different regions."
    result=await agent.run(query) # test mcp ms learn
    print(result)
    print("-" * 20)

    result = await agent.run("How many employees does Tencent have?") # test file search
    print(result)
    print("-" * 20)

    result = await agent.run("Search for bitcoin prices for the past week on the web and then calculate the average daily bitcoin price for the past week using Python. Show me the details.") # test web search and code interpreter
    print(result)



@tool
def get_weather(location: str) -> str:
    """Get the weather for a given location."""
    return f"The weather in {location} is sunny, 25°C."

async def function_example():
    agent = build_azure_openai_chat_client().as_agent(
        instructions="You are a weather assistant.",
        tools=get_weather,
    )
    result = await agent.run("What's the weather in Tokyo?")
    print(result)


async def thread_example():
    agent = build_azure_openai_chat_client().as_agent(
        instructions="You are a helpful assistant.",
    )
    session =  agent.create_session()

    result1 = await agent.run("My name is Alice", session=session)
    print(result1)
    result2 = await agent.run("What's my name?", session=session)
    print(result2)  # Remembers "Alice"


async def streaming_example():
    agent = build_azure_openai_chat_client().as_agent(
        instructions="You are a creative storyteller.",
    )
    print("Agent: ", end="", flush=True)
    async for chunk in agent.run("Tell me a short story about AI.", stream=True):
        if chunk.text:
            print(chunk.text, end="", flush=True)
    print()



async def main():
    print("Test simple chat: ")
    await azure_openai_chat_example()
    print("=" * 20)

    print("Test coding agent: ")
    await coding_agent_example()
    print("=" * 20)

    print("Test hosted tools: ")
    await hosted_tools_example()
    print("=" * 20)

    print("Test function calling: ")
    await function_example()
    print("=" * 20)

    print("Test context management: ")
    await thread_example()
    print("=" * 20)

    print("Test streaming: ")
    await streaming_example()
    print("=" * 20)

if __name__ == "__main__":
    asyncio.run(main())