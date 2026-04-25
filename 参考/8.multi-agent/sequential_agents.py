import asyncio
from typing import cast
import os
from agent_framework import Agent, Message
from agent_framework.openai import OpenAIChatClient
from agent_framework.orchestrations import SequentialBuilder
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

"""
Sample: Sequential workflow (agent-focused API) with shared conversation context

Build a high-level sequential workflow using SequentialBuilder and two domain agents.
The shared conversation (list[Message]) flows through each participant. Each agent
appends its assistant message to the context. The workflow outputs the final conversation
list when complete.

Note on internal adapters:
- Sequential orchestration includes small adapter nodes for input normalization
  ("input-conversation"), agent-response conversion ("to-conversation:<participant>"),
  and completion ("complete"). These may appear as ExecutorInvoke/Completed events in
  the stream—similar to how concurrent orchestration includes a dispatcher/aggregator.
  You can safely ignore them when focusing on agent progress.

"""


async def main() -> None:
    # 1) Create agents
    # using Azure OpenAI resource
    client = OpenAIChatClient(
        model=os.getenv("AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )

    writer = Agent(
        client=client,
        instructions=(
            "You are a concise copywriter. You must use the web search tool before drafting. "
            "Ground your answer in current web findings and provide one punchy marketing sentence "
            "followed by 2 short source citations with URLs."
        ),
        name="writer",
        tools=[client.get_web_search_tool(user_location={"type": "approximate", "country": "CN"})],
    )

    reviewer = client.as_agent(
        instructions=(
            "You are a thoughtful reviewer. Give brief feedback on the previous assistant message, "
            "including whether it appears grounded in current web sources and includes citations."
        ),
        name="reviewer",
    )

    # 2) Build sequential workflow: writer -> reviewer
    workflow = SequentialBuilder(participants=[writer, reviewer]).build()

    # 3) Run and collect outputs
    outputs: list[list[Message]] = []
    async for event in workflow.run(
        "Use web search to write a tagline for a budget-friendly eBike in China, grounded in current market info. "
        "Include 2 source URLs.",
        stream=True,
    ):
        if event.type == "output":
            outputs.append(cast(list[Message], event.data))

    if outputs:
        print("===== Final Conversation =====")
        for i, msg in enumerate(outputs[-1], start=1):
            name = msg.author_name or ("assistant" if msg.role == "assistant" else "user")
            print(f"{'-' * 60}\n{i:02d} [{name}]\n{msg.text}")

    """
    Sample Output:

    ===== Final Conversation =====
    ------------------------------------------------------------
    01 [user]
    Use web search to write a tagline for a budget-friendly eBike in China, grounded in current market info.
    Include 2 source URLs.
    ------------------------------------------------------------
    02 [writer]
    Ride smarter for less—China's value eBikes give you longer city range without stretching your budget.
    Sources:
    - https://example.com/source-1
    - https://example.com/source-2
    ------------------------------------------------------------
    03 [reviewer]
    This tagline clearly communicates affordability and the benefit of extended travel, making it
    appealing to budget-conscious consumers. It has a friendly and motivating tone, though it could
    be slightly shorter for more punch. Overall, a strong and effective suggestion!
    """


if __name__ == "__main__":
    asyncio.run(main())
