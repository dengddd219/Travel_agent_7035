import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, CodeInterpreterTool, AutoCodeInterpreterToolParam
from dotenv import load_dotenv
load_dotenv()

# Create a new agent
# Load the CSV file to be processed
asset_file_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "./data/listings.csv")
)

# Format: "https://applied-llm-resource.ai.azure.com/api/projects/tai-man-chan-project"
PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT")

# Create clients to call Foundry API
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()

# Upload the CSV file for the code interpreter to use
file = openai.files.create(purpose="assistants", file=open(asset_file_path, "rb"))
print(f"File uploaded: {file.id}")
# Create agent with code interpreter tool
agent = project.agents.create_version(
    agent_name="airbnb-agent",
    definition=PromptAgentDefinition(
        model="gpt-5-mini",
        instructions="You are a helpful assistant.",
        tools=[CodeInterpreterTool(container=AutoCodeInterpreterToolParam(file_ids=[file.id]))],
    ),
    description="Code interpreter agent for data analysis and visualization.",
)
print(f"Agent created: {agent.id} {agent.name} {agent.version}")
# Create a conversation for the agent interaction
conversation = openai.conversations.create()

# Send request to create a chart and generate a file
response = openai.responses.create(
    conversation=conversation.id,
    input="Could you please run EDA on the uploaded csv file and provide a summary of the results to me?",
    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
)

# Extract file information from response annotations
file_id = ""
filename = ""
container_id = ""

# Get the last message which should contain file citations
last_message = response.output[-1]  # ResponseOutputMessage
if (
    last_message.type == "message"
    and last_message.content
    and last_message.content[-1].type == "output_text"
    and last_message.content[-1].annotations
):
    file_citation = last_message.content[-1].annotations[-1]  # AnnotationContainerFileCitation
    if file_citation.type == "container_file_citation":
        file_id = file_citation.file_id
        filename = file_citation.filename
        container_id = file_citation.container_id
        print(f"Found generated file: {filename} (ID: {file_id})")

#print response
print(response.output_text)
# Clean up resources
# project.agents.delete_version(agent_name=agent.name, agent_version=agent.version)

# Download the generated file if available
if file_id and filename:
    file_content = openai.containers.files.content.retrieve(file_id=file_id, container_id=container_id)
    print(f"File ready for download: {filename}")
    file_path = os.path.join(os.path.dirname(__file__), filename)
    with open(file_path, "wb") as f:
        f.write(file_content.read())
    print(f"File downloaded successfully: {file_path}")
else:
    print("No file generated in response")

# Use an existing agent
# from azure.identity import DefaultAzureCredential
# from azure.ai.projects import AIProjectClient
#
# my_endpoint = "https://applied-llm-resource.services.ai.azure.com/api/projects/applied-llm"
#
# project_client = AIProjectClient(
#     endpoint=my_endpoint,
#     credential=DefaultAzureCredential(),
# )
#
# my_agent = "airbnb-agent"
# my_version = "1"
#
# openai_client = project_client.get_openai_client()
#
# # Reference the agent to get a response
# response = openai_client.responses.create(
#     input=[{"role": "user", "content": "Tell me what you can help with."}],
#     extra_body={"agent_reference": {"name": my_agent, "version": my_version, "type": "agent_reference"}},
# )
#
# print(f"Response output: {response.output_text}")