from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
import os
from dotenv import load_dotenv

load_dotenv()
print("[1/8] Environment variables loaded.")

# Format: "https://applied-llm-resource.ai.azure.com/api/projects/tai-man-chan-project"
PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
print(f"[2/8] Foundry endpoint configured: {bool(PROJECT_ENDPOINT)}")

# Load the file to be indexed for search.
asset_file_path = (Path(__file__).parent / "./data/Course Introduction.pptx").resolve()
print(f"[3/8] Search asset path: {asset_file_path}")

# Create clients to call Foundry API
print("[4/8] Initializing AI Project and OpenAI clients...")
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()
print("[4/8] Clients initialized.")

# Create vector store and upload file
print("[5/8] Creating vector store...")
vector_store = openai.vector_stores.create(name="CourseInfoStore")
print(f"[5/8] Vector store created: {vector_store.id}")

print("[6/8] Uploading course file to vector store (this may take a moment)...")
with asset_file_path.open("rb") as file_handle:
    vector_store_file = openai.vector_stores.files.upload_and_poll(
        vector_store_id=vector_store.id,
        file=file_handle,
    )
print(f"[6/8] Upload complete. Vector store file id: {vector_store_file.id}")

# Create agent with file search tool
print("[7/8] Creating agent version with file search tool...")
agent = project.agents.create_version(
    agent_name="allm-course-agent",
    definition=PromptAgentDefinition(
        model="gpt-5-mini",
        instructions=(
            """You are a Course Assistant Agent for the Applied LLMs course.
Your role is to help students understand the course introduction, learning objectives, structure, assessment, policies, and expectations, strictly based on the official course PPT provided as knowledge.
You act as a teaching assistant, not a decision‑maker."""
        ),
        tools=[FileSearchTool(vector_store_ids=[vector_store.id])],
    ),
    description="File search agent for course information queries.",
)
print(f"[7/8] Agent ready: {agent.name} (version: {agent.version})")

# Create conversation and generate response
print("[8/8] Creating conversation and requesting response...")
conversation = openai.conversations.create()
print(f"[8/8] Conversation created: {conversation.id}")

response = openai.responses.create(
    conversation=conversation.id,
    input="Tell me about the Applied LLMs course.",
    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
)
print("Response received:\n")
print(response.output_text)
print("\nDone.")

# Clean up resources
# project.agents.delete_version(
#     agent_name=agent.name,
#     agent_version=agent.version,
# )
# openai.vector_stores.delete(vector_store.id)