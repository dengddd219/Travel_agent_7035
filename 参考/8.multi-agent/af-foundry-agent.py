# pip install agent-framework
import os
import asyncio
from agent_framework.foundry import FoundryChatClient, RawFoundryAgent
from azure.identity.aio import AzureCliCredential
from azure.ai.projects.models import PromptAgentDefinition
from azure.ai.projects.aio import AIProjectClient
from typing import Annotated
from pydantic import Field
from dotenv import load_dotenv
load_dotenv()


def build_foundry_chat_client(
    credential: AzureCliCredential,
    *,
    endpoint: str | None = None,
    model: str | None = None,
) -> FoundryChatClient:
    return FoundryChatClient(
        credential=credential,
        project_endpoint=endpoint or os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        model=model or os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
    )


# Basic Agent Creation
# AZURE_AI_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME must be in .env
async def create_agent():
    async with (
        AzureCliCredential() as credential,
        build_foundry_chat_client(credential).as_agent(
            name="HelperAgent",
            instructions="You are a helpful assistant."
        ) as agent,
    ):
        result = await agent.run("Hello!")
        print(result)


# Explicit Configuration
async def create_agent_explicit():
    async with (
        AzureCliCredential() as credential,
        build_foundry_chat_client(
            credential,
            endpoint="https://applied-llm-resource.services.ai.azure.com/api/projects/applied-llm",
            model="gpt-4.1-mini",
        ).as_agent(
            name="HelperAgent",
            instructions="You are a helpful assistant."
        ) as agent,
    ):
        result = await agent.run("Hello!")
        print(result)


# Using an Existing Agent
async def use_agent():
    async with (
        AzureCliCredential() as credential,
        AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client,
        RawFoundryAgent(
            project_client=project_client,
            agent_name="allm-course-agent",
            credential=credential,
        ) as agent,
    ):

        result = await agent.run("Tell me about individual assignments")
        print(result)


# Create and Manage Persistent Agents
async def create_and_manage_agent():
    async with (
        AzureCliCredential() as credential,
        AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client,
    ):
        # Create a persistent agent
        created_agent = await project_client.agents.create_version(
            agent_name="PersistentAgent",
            definition=PromptAgentDefinition(
                model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
                instructions="You are a helpful assistant."
            ),
        )
        print("Agent created")

        try:
            # Use the agent
            async with RawFoundryAgent(
                project_client=project_client,
                credential=credential,
                agent_name=created_agent.name,
                agent_version=created_agent.version,
            ) as agent:
                result = await agent.run("Hello!")
                print(result)
        finally:
            # Clean up the agent
            await project_client.agents.delete_version(
                agent_name=created_agent.name,
                agent_version=created_agent.version
            )
            print("Agent deleted")


# Function Tools
def get_weather(
    location: Annotated[str, Field(description="The location to get the weather for.")],
) -> str:
    """Get the weather for a given location."""
    return f"The weather in {location} is sunny with a high of 25°C."

async def agent_with_function():
    async with (
        AzureCliCredential() as credential,
        build_foundry_chat_client(credential).as_agent(
            name="WeatherAgent",
            instructions="You are a helpful weather assistant.",
            tools=get_weather
        ) as agent,
    ):
        result = await agent.run("What's the weather like in Seattle?")
        print(result)


# # Code Interpreter
async def agent_with_code_interpreter():
    async with AzureCliCredential() as credential:
        client = build_foundry_chat_client(credential)
        async with client.as_agent(
            name="CodingAgent",
            instructions="You are a helpful assistant that can write and execute Python code.",
            tools=client.get_code_interpreter_tool(),
        ) as agent:
            result = await agent.run("Calculate the factorial of 20 using Python code.")
            print(result)



# Streaming Responses
async def agent_streaming():
    async with (
        AzureCliCredential() as credential,
        build_foundry_chat_client(credential).as_agent(
            name="StreamingAgent",
            instructions="You are a helpful assistant."
        ) as agent,
    ):
        print("Agent: ", end="", flush=True)
        async for chunk in agent.run("Tell me a short story", stream=True):
            if chunk.text:
                print(chunk.text, end="", flush=True)
        print()

async def main():
    await create_agent()
    print("=" * 20)

    await create_agent_explicit()
    print("=" * 20)

    await use_agent()
    print("=" * 20)

    await create_and_manage_agent()
    print("=" * 20)

    await agent_with_function()
    print("=" * 20)

    await agent_with_code_interpreter()
    print("=" * 20)

    await agent_streaming()

if __name__ == "__main__":
    asyncio.run(main())

