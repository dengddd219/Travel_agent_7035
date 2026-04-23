import json
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool
from openai.types.responses.response_input_param import McpApprovalResponse, ResponseInputParam
import os
from dotenv import load_dotenv
load_dotenv()

# Format: "https://resource_name.ai.azure.com/api/projects/project_name"
PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
MCP_CONNECTION_NAME = "GitHub" # GitHub under the Catalog tab; github-copilot for a Custom MCP tool; set up a connection in the Tools page via "Connect a tool".

# Create clients to call Foundry API
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()

# [START tool_declaration]
tool = MCPTool(
    server_label="GitHub",
    server_url="https://api.githubcopilot.com/mcp",
    require_approval="always",
    project_connection_id=MCP_CONNECTION_NAME,
)
# [END tool_declaration]

# Create a prompt agent with MCP tool capabilities
agent = project.agents.create_version(
    agent_name="GitHub-agent",
    definition=PromptAgentDefinition(
        model="gpt-5-mini",
        instructions="Use MCP tools as needed",
        tools=[tool],
    ),
)
print(f"Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})")

# Create a conversation to maintain context across multiple interactions
conversation = openai.conversations.create()
print(f"Created conversation (id: {conversation.id})")

def run_turn(prompt: str) -> None:
    response = openai.responses.create(
        conversation=conversation.id,
        input=prompt,
        extra_body={"agent_reference": {"name": agent.name, "version": agent.version, "type": "agent_reference"}},
    )

    while True:
        input_list: ResponseInputParam = []
        for item in response.output:
            if item.type == "mcp_approval_request" and item.id:
                print("MCP approval requested")
                print(f"  Server: {item.server_label}")
                print(f"  Tool: {getattr(item, 'name', '<unknown>')}")
                print(
                    f"  Arguments: {json.dumps(getattr(item, 'arguments', None), indent=2, default=str)}"
                )

                # Approve only after you review the tool call.
                # In production, implement your own approval UX and policy.
                should_approve = (
                    input("Approve this MCP tool call? (y/N): ").strip().lower() == "y"
                )
                input_list.append(
                    McpApprovalResponse(
                        type="mcp_approval_response",
                        approve=should_approve,
                        approval_request_id=item.id,
                    )
                )

        if not input_list:
            print(f"Response: {response.output_text}")
            return

        response = openai.responses.create(
            conversation=conversation.id,
            input=input_list,
            extra_body={"agent_reference": {"name": agent.name, "version": agent.version, "type": "agent_reference"}},
        )


# Start with the example query already in this file.
initial_query = "What is my username in my GitHub profile?"
print(f"\nRunning initial query: {initial_query}")
run_turn(initial_query)

while True:
    user_query = input("\nEnter a query (or type 'quit'/'exit' to stop): ").strip()
    if user_query.lower() in {"quit", "exit"}:
        print("Exiting.")
        break
    if not user_query:
        continue
    run_turn(user_query)

# Clean up resources by deleting the agent version
# project.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
# print("Agent deleted")