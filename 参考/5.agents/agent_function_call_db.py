import json
import os
from typing import Any, Callable, Dict, List

from dotenv import load_dotenv

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition, CodeInterpreterTool
from azure.identity import DefaultAzureCredential
from openai import BadRequestError

from function_call_db import (
    get_boxoffice,
    get_fandango_reviews,
    get_fbposts,
    get_imdb_id_by_title,
    get_movie_overview,
)



DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "./output"))


def _to_tool_output(value: Any) -> str:
    """Normalizes callable outputs into a string payload for tool responses."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _build_tools() -> List[FunctionTool]:
    return [
        CodeInterpreterTool(),
        FunctionTool(
            name="get_imdb_id_by_title",
            description="Get IMDb IDs matching a movie title.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Movie title or partial title to search for.",
                    }
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            strict=True,
        ),
        FunctionTool(
            name="get_movie_overview",
            description=(
                "Get movie details by IMDb ID, including year, rating, runtime, genres, "
                "box office metadata, and summary."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "imdb_id": {
                        "type": "string",
                        "description": "IMDb ID such as tt0454876.",
                    }
                },
                "required": ["imdb_id"],
                "additionalProperties": False,
            },
            strict=True,
        ),
        FunctionTool(
            name="get_boxoffice",
            description="Get weekly box office records by IMDb ID.",
            parameters={
                "type": "object",
                "properties": {
                    "imdb_id": {
                        "type": "string",
                        "description": "IMDb ID such as tt0454876.",
                    }
                },
                "required": ["imdb_id"],
                "additionalProperties": False,
            },
            strict=True,
        ),
        FunctionTool(
            name="get_fbposts",
            description="Get sample Facebook posts for a movie by IMDb ID.",
            parameters={
                "type": "object",
                "properties": {
                    "imdb_id": {
                        "type": "string",
                        "description": "IMDb ID such as tt0454876.",
                    }
                },
                "required": ["imdb_id"],
                "additionalProperties": False,
            },
            strict=True,
        ),
        FunctionTool(
            name="get_fandango_reviews",
            description="Get sample Fandango reviews for a movie by IMDb ID.",
            parameters={
                "type": "object",
                "properties": {
                    "imdb_id": {
                        "type": "string",
                        "description": "IMDb ID such as tt0454876.",
                    }
                },
                "required": ["imdb_id"],
                "additionalProperties": False,
            },
            strict=True,
        ),
    ]


def _log_code_interpreter_activity(response: Any) -> None:
    """Prints concise logs when a response includes Code Interpreter events."""
    for item in getattr(response, "output", []) or []:
        item_type = getattr(item, "type", "")
        if item_type != "code_interpreter_call":
            continue

        call_id = getattr(item, "call_id", None) or getattr(item, "id", "unknown")
        status = getattr(item, "status", "unknown")
        print(f"[CODE INTERPRETER] call_id={call_id} status={status}")


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
        print(f"[CODE INTERPRETER FILE] Downloaded: {target_path}")


def main() -> None:
    load_dotenv()

    project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model_deployment = os.getenv("FOUNDRY_PROJECT_DEPLOYMENT")

    if not project_endpoint or not model_deployment:
        raise ValueError(
            "FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_PROJECT_DEPLOYMENT must be set in your environment."
        )

    download_dir = os.getenv("CODE_INTERPRETER_DOWNLOAD_DIR", DOWNLOAD_DIR)

    tool_impls: Dict[str, Callable[..., Any]] = {
        "get_imdb_id_by_title": get_imdb_id_by_title,
        "get_movie_overview": get_movie_overview,
        "get_boxoffice": get_boxoffice,
        "get_fbposts": get_fbposts,
        "get_fandango_reviews": get_fandango_reviews,
    }

    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=project_endpoint, credential=credential) as project_client,
        project_client.get_openai_client() as openai_client,
    ):
        agent = project_client.agents.create_version(
            agent_name="movie-db-agent",
            definition=PromptAgentDefinition(
                model=model_deployment,
                instructions=(
                    "You are a movie analytics assistant. Use the provided tools to look up movie IDs, "
                    "overview metadata, box office history, Facebook posts, and Fandango reviews. "
                    "When a title is provided, call get_imdb_id_by_title first, then use IMDb IDs for other tools."
                ),
                tools=_build_tools(),
            ),
        )
        print("Agent created:", agent.id, agent.name, agent.version)
        print(f"Code Interpreter enabled. Generated files will be saved to: {download_dir}")

        conversation = openai_client.conversations.create()

        while True:
            user_input = input("Enter a prompt for the movie agent. Use 'quit' to exit.\nUSER: ").strip()
            if user_input.lower() == "quit":
                print("Exiting chat.")
                break

            openai_client.conversations.items.create(
                conversation_id=conversation.id,
                items=[{"type": "message", "role": "user", "content": user_input}],
            )

            response = openai_client.responses.create(
                conversation=conversation.id,
                extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
            )
            _log_code_interpreter_activity(response)
            _download_generated_files(openai_client=openai_client, response=response, output_dir=download_dir)

            if response.status == "failed":
                print(f"Response failed: {response.error}")
                continue

            turn_failed = False

            # Continue the function-calling loop until the model returns plain text.
            while True:
                pending_calls = [item for item in response.output if item.type == "function_call"]
                if not pending_calls:
                    break

                print(
                    "[TOOL CALL IDS]",
                    [f"{item.name}:{item.call_id}" for item in pending_calls],
                )

                tool_outputs: List[Dict[str, str]] = []
                for item in pending_calls:
                    function = tool_impls.get(item.name)
                    try:
                        args = json.loads(item.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {"_raw_arguments": item.arguments}

                    print(f"[TOOL CALL] name={item.name} args={args}")

                    if function is None:
                        result = json.dumps({"error": f"Unknown function: {item.name}"})
                    else:
                        try:
                            result = _to_tool_output(function(**args))
                        except Exception as exc:  # Keep the chat alive even if tool execution fails.
                            result = json.dumps({"error": f"{type(exc).__name__}: {exc}"})

                    if not item.call_id:
                        print(f"[TOOL ERROR] Missing call_id for function call: {item.name}")
                        turn_failed = True
                        break

                    tool_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": item.call_id,
                            "output": result,
                        }
                    )

                if turn_failed:
                    break

                try:
                    response = openai_client.responses.create(
                        input=tool_outputs,
                        conversation=conversation.id,
                        extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
                    )
                    _log_code_interpreter_activity(response)
                    _download_generated_files(openai_client=openai_client, response=response, output_dir=download_dir)
                except BadRequestError as exc:
                    print(f"Tool output submission failed: {exc}")
                    turn_failed = True
                    break

                if response.status == "failed":
                    print(f"Response failed: {response.error}")
                    turn_failed = True
                    break

            if turn_failed:
                print("AGENT: Turn failed due to unresolved tool calls. Please retry your prompt.")
                continue

            print(f"AGENT: {response.output_text}")


if __name__ == "__main__":
    main()

# test: visualize the weekly box office revenue for Life of Pi.