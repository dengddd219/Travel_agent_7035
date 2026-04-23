from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    WebSearchTool,
    WebSearchApproximateLocation,
)
import os
from dotenv import load_dotenv
load_dotenv()

# Format: "https://applied-llm-resource.ai.azure.com/api/projects/tai-man-chan-project"
PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT")

# Create clients to call Foundry API
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()

# Create an agent with the web search tool
agent = project.agents.create_version(
    agent_name="web-search-agent",
    definition=PromptAgentDefinition(
        model="gpt-5-mini",
        instructions="You are a helpful assistant that can search the web",
        tools=[
            WebSearchTool(
                user_location=WebSearchApproximateLocation(
                    country="CN", city="Hong Kong", region="Hong Kong"
                )
            )
        ],
    ),
    description="Agent for web search.",
)
print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")

# Send a query and stream the response
stream_response = openai.responses.create(
    stream=True,
    tool_choice="required",
    input="What is today's date and weather in Hong Kong?",
    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
)

# Process streaming events
for event in stream_response:
    if event.type == "response.created":
        print(f"Follow-up response created with ID: {event.response.id}")
    elif event.type == "response.output_text.delta":
        print(f"Delta: {event.delta}")
    elif event.type == "response.text.done":
        print(f"\nFollow-up response done!")
    elif event.type == "response.output_item.done":
        if event.item.type == "message":
            item = event.item
            if item.content[-1].type == "output_text":
                text_content = item.content[-1]
                for annotation in text_content.annotations:
                    if annotation.type == "url_citation":
                        print(f"URL Citation: {annotation.url}")
    elif event.type == "response.completed":
        print(f"\nFollow-up completed!")
        print(f"Full response: {event.response.output_text}")

# project.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
# print("Agent deleted")