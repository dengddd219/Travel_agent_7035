import argparse
import os
from typing import Any, Dict, List, Optional, Tuple

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AutoCodeInterpreterToolParam,
    CodeInterpreterTool,
    PromptAgentDefinition,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

# --------------------------
# Agent defaults (edit here)
# --------------------------
AGENT_NAME = "airbnb-agent"
AGENT_VERSION="1"
MODEL_NAME = "gpt-5-mini"
AGENT_DESCRIPTION = "Code interpreter agent for data analysis and visualization."
AGENT_INSTRUCTIONS = (
    "You are a data analyst. Use Python to analyze the uploaded dataset, "
    "show key statistics, and explain findings clearly."
)
DATA_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "./data/listings.csv"))
# INITIAL_PROMPT = "Please run EDA on this dataset and summarize the most important findings."
INITIAL_PROMPT = "Please tell me what you can do."
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "./output"))


def get_project_and_openai_client(project_endpoint: Optional[str] = None) -> Tuple[AIProjectClient, Any]:
    """Create Foundry project and OpenAI clients from endpoint or environment."""
    endpoint = project_endpoint or os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT is not set in environment or .env.")

    project_client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    return project_client, project_client.get_openai_client()


def _upload_data_file(openai_client: Any, data_file_path: str) -> str:
    file_abs_path = os.path.abspath(data_file_path)
    if not os.path.exists(file_abs_path):
        raise FileNotFoundError(f"Data file not found: {file_abs_path}")

    with open(file_abs_path, "rb") as file_handle:
        uploaded = openai_client.files.create(purpose="assistants", file=file_handle)
    print(f"Uploaded data file: {uploaded.id}")
    return str(uploaded.id)


def _collect_generated_files(response: Any) -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "message":
            continue
        for content in getattr(item, "content", []) or []:
            for annotation in getattr(content, "annotations", []) or []:
                if getattr(annotation, "type", "") == "container_file_citation":
                    files.append(
                        {
                            "file_id": annotation.file_id,
                            "filename": annotation.filename,
                            "container_id": annotation.container_id,
                        }
                    )
    return files


def _download_generated_files(openai_client: Any, response: Any, output_dir: str) -> None:
    files = _collect_generated_files(response)
    if not files:
        return

    os.makedirs(output_dir, exist_ok=True)
    for file_info in files:
        file_content = openai_client.containers.files.content.retrieve(
            file_id=file_info["file_id"],
            container_id=file_info["container_id"],
        )
        target_path = os.path.join(output_dir, file_info["filename"])
        with open(target_path, "wb") as file_handle:
            file_handle.write(file_content.read())
        print(f"Downloaded generated file: {target_path}")


def create_agent(
    project_client: AIProjectClient,
    openai_client: Any,
    agent_name: str = AGENT_NAME,
    data_file_path: str = DATA_FILE_PATH,
    model_name: str = MODEL_NAME,
    instructions: str = AGENT_INSTRUCTIONS,
    description: str = AGENT_DESCRIPTION,
) -> Dict[str, str]:
    """Create a new agent version with Code Interpreter and one uploaded dataset."""
    file_id = _upload_data_file(openai_client=openai_client, data_file_path=data_file_path)

    agent = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=model_name,
            instructions=instructions,
            tools=[CodeInterpreterTool(container=AutoCodeInterpreterToolParam(file_ids=[file_id]))],
        ),
        description=description,
    )

    result = {
        "agent_name": str(agent.name),
        "agent_version": str(agent.version),
        "agent_id": str(agent.id),
        "file_id": file_id,
    }
    print(f"Created agent version: {result['agent_name']} v{result['agent_version']}")
    return result


def chat_with_agent(
    openai_client: Any,
    agent_name: str,
    agent_version: Optional[str] = None,
    initial_prompt: str = INITIAL_PROMPT,
    download_dir: str = DOWNLOAD_DIR,
) -> None:
    """Run a command-line chatbot session for multi-turn data analysis with the agent."""
    conversation = openai_client.conversations.create()

    agent_reference: Dict[str, str] = {"name": agent_name, "type": "agent_reference"}
    if agent_version:
        agent_reference["version"] = agent_version

    def send_message(user_input: str) -> None:
        response = openai_client.responses.create(
            conversation=conversation.id,
            input=user_input,
            extra_body={"agent_reference": agent_reference},
        )
        print(f"\nassistant> {response.output_text}\n")
        _download_generated_files(openai_client=openai_client, response=response, output_dir=download_dir)

    print(f"Starting chat with agent '{agent_name}'" + (f" (version {agent_version})" if agent_version else ""))
    print("Type 'exit' or 'quit' to end the session.\n")

    if initial_prompt:
        print(f"you> {initial_prompt}")
        send_message(initial_prompt)

    while True:
        user_text = input("you> ").strip()
        if user_text.lower() in {"exit", "quit"}:
            print("Chat ended.")
            break
        if not user_text:
            continue
        send_message(user_text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or chat with a Foundry code interpreter agent.")
    parser.add_argument("action", choices=["create", "chat"], help="create: create agent version, chat: run CLI chatbot")
    parser.add_argument("--agent-name", default=AGENT_NAME, help="Agent name")
    parser.add_argument("--agent-version", default=AGENT_VERSION, help="Agent version (needed for chat if not using latest)")
    parser.add_argument("--project-endpoint", default=None, help="Foundry project endpoint (or use FOUNDRY_PROJECT_ENDPOINT)")
    parser.add_argument("--data-file", default=DATA_FILE_PATH, help="Data file path used when creating agent")
    parser.add_argument("--model", default=MODEL_NAME, help="Model name used when creating agent")
    parser.add_argument("--instructions", default=AGENT_INSTRUCTIONS, help="Agent instructions used when creating agent")
    parser.add_argument("--description", default=AGENT_DESCRIPTION, help="Agent description used when creating agent")
    parser.add_argument("--initial-prompt", default=INITIAL_PROMPT, help="Initial prompt for chat mode")
    parser.add_argument("--download-dir", default=DOWNLOAD_DIR, help="Directory for generated files")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_client, openai_client = get_project_and_openai_client(project_endpoint=args.project_endpoint)

    if args.action == "create":
        create_agent(
            project_client=project_client,
            openai_client=openai_client,
            agent_name=args.agent_name,
            data_file_path=args.data_file,
            model_name=args.model,
            instructions=args.instructions,
            description=args.description,
        )
        return

    chat_with_agent(
        openai_client=openai_client,
        agent_name=args.agent_name,
        agent_version=args.agent_version,
        initial_prompt=args.initial_prompt,
        download_dir=args.download_dir,
    )


if __name__ == "__main__":
    main()
