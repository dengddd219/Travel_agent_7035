import json
import mimetypes
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import CodeInterpreterTool, FunctionTool, PromptAgentDefinition
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
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".svg"}


@dataclass
class TurnResult:
    output_text: str
    generated_files: List[Dict[str, Any]]
    logs: List[str]
    failed: bool = False
    error_message: str = ""


@dataclass
class AgentRuntime:
    credential: DefaultAzureCredential
    project_client: AIProjectClient
    openai_client: Any
    agent_name: str
    conversation_id: str
    download_dir: str
    tool_impls: Dict[str, Callable[..., Any]]


def _to_tool_output(value: Any) -> str:
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


def _log_code_interpreter_activity(
    response: Any, progress_callback: Optional[Callable[[str], None]] = None
) -> List[str]:
    logs: List[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "code_interpreter_call":
            continue
        call_id = getattr(item, "call_id", None) or getattr(item, "id", "unknown")
        status = getattr(item, "status", "unknown")
        logs.append(f"code_interpreter call_id={call_id} status={status}")
        if progress_callback:
            progress_callback(f"Code Interpreter: {status} ({call_id})")
    return logs


def _is_image_file(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    if ext in IMAGE_EXTENSIONS:
        return True
    mime, _ = mimetypes.guess_type(filename)
    return bool(mime and mime.startswith("image/"))


def _download_generated_files(openai_client: Any, response: Any, output_dir: str) -> List[Dict[str, Any]]:
    files = _collect_generated_files(response)
    if not files:
        return []

    os.makedirs(output_dir, exist_ok=True)
    downloaded_files: List[Dict[str, Any]] = []
    for file_info in files:
        file_content = openai_client.containers.files.content.retrieve(
            file_id=file_info["file_id"],
            container_id=file_info["container_id"],
        )
        data = file_content.read()
        safe_name = os.path.basename(file_info["filename"])
        target_name = f"{file_info['file_id']}_{safe_name}"
        target_path = os.path.join(output_dir, target_name)
        with open(target_path, "wb") as file_handle:
            file_handle.write(data)

        mime, _ = mimetypes.guess_type(safe_name)
        downloaded_files.append(
            {
                "file_id": file_info["file_id"],
                "filename": safe_name,
                "path": target_path,
                "bytes": data,
                "mime": mime or "application/octet-stream",
                "is_image": _is_image_file(safe_name),
            }
        )
    return downloaded_files


def _create_runtime() -> AgentRuntime:
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

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)
    openai_client = project_client.get_openai_client()

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
    conversation = openai_client.conversations.create()

    return AgentRuntime(
        credential=credential,
        project_client=project_client,
        openai_client=openai_client,
        agent_name=agent.name,
        conversation_id=conversation.id,
        download_dir=download_dir,
        tool_impls=tool_impls,
    )


def _run_turn(
    runtime: AgentRuntime,
    user_input: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> TurnResult:
    if progress_callback:
        progress_callback("Message sent to agent")

    runtime.openai_client.conversations.items.create(
        conversation_id=runtime.conversation_id,
        items=[{"type": "message", "role": "user", "content": user_input}],
    )

    response = runtime.openai_client.responses.create(
        conversation=runtime.conversation_id,
        extra_body={"agent_reference": {"name": runtime.agent_name, "type": "agent_reference"}},
    )

    if progress_callback:
        progress_callback("Agent started planning response")

    logs = _log_code_interpreter_activity(response, progress_callback=progress_callback)
    generated_files = _download_generated_files(
        openai_client=runtime.openai_client,
        response=response,
        output_dir=runtime.download_dir,
    )

    if response.status == "failed":
        return TurnResult(
            output_text="",
            generated_files=generated_files,
            logs=logs,
            failed=True,
            error_message=f"Response failed: {response.error}",
        )

    while True:
        pending_calls = [item for item in response.output if item.type == "function_call"]
        if not pending_calls:
            break

        tool_outputs: List[Dict[str, str]] = []
        for item in pending_calls:
            function = runtime.tool_impls.get(item.name)
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw_arguments": item.arguments}

            logs.append(f"tool_call name={item.name} args={args}")
            if progress_callback:
                progress_callback(f"Function call: {item.name}")

            if function is None:
                result = json.dumps({"error": f"Unknown function: {item.name}"})
                if progress_callback:
                    progress_callback(f"Function failed: {item.name} (not implemented)")
            else:
                try:
                    result = _to_tool_output(function(**args))
                    if progress_callback:
                        progress_callback(f"Function completed: {item.name}")
                except Exception as exc:
                    result = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
                    if progress_callback:
                        progress_callback(f"Function failed: {item.name} ({type(exc).__name__})")

            if not item.call_id:
                return TurnResult(
                    output_text="",
                    generated_files=generated_files,
                    logs=logs,
                    failed=True,
                    error_message=f"Missing call_id for function call: {item.name}",
                )

            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": result,
                }
            )

        try:
            if progress_callback:
                progress_callback(f"Submitting {len(tool_outputs)} tool result(s) to agent")

            response = runtime.openai_client.responses.create(
                input=tool_outputs,
                conversation=runtime.conversation_id,
                extra_body={"agent_reference": {"name": runtime.agent_name, "type": "agent_reference"}},
            )
        except BadRequestError as exc:
            return TurnResult(
                output_text="",
                generated_files=generated_files,
                logs=logs,
                failed=True,
                error_message=f"Tool output submission failed: {exc}",
            )

        logs.extend(_log_code_interpreter_activity(response, progress_callback=progress_callback))
        generated_files.extend(
            _download_generated_files(
                openai_client=runtime.openai_client,
                response=response,
                output_dir=runtime.download_dir,
            )
        )

        if response.status == "failed":
            return TurnResult(
                output_text="",
                generated_files=generated_files,
                logs=logs,
                failed=True,
                error_message=f"Response failed: {response.error}",
            )

    return TurnResult(output_text=response.output_text or "", generated_files=generated_files, logs=logs)


def _render_generated_files(files: List[Dict[str, Any]], message_key: str) -> None:
    if not files:
        return

    st.markdown("**Generated files**")
    for idx, file_info in enumerate(files):
        file_label = f"{file_info['filename']} ({file_info['mime']})"
        if file_info["is_image"]:
            st.image(file_info["bytes"], caption=file_label, width='stretch')

        st.download_button(
            label=f"Download {file_info['filename']}",
            data=file_info["bytes"],
            file_name=file_info["filename"],
            mime=file_info["mime"],
            key=f"download-{message_key}-{idx}-{file_info['file_id']}",
        )


def _render_message(message: Dict[str, Any], index: int) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message.get("content") or "")
        _render_generated_files(message.get("files", []), f"msg-{index}")
        logs = message.get("logs") or []
        if logs:
            with st.expander("Debug logs"):
                for log in logs:
                    st.text(log)


def main() -> None:
    st.set_page_config(page_title="Movie DB Agent", layout="wide")
    st.title("Movie DB Agent (Streamlit)")
    st.caption("Uses Azure Foundry agent + function tools + Code Interpreter artifacts.")

    if "runtime" not in st.session_state:
        try:
            status = st.status("Initializing Azure Foundry agent...", expanded=False)
            st.session_state.runtime = _create_runtime()
            status.update(label="Agent initialized", state="complete")
            st.session_state.messages = []
        except Exception as exc:
            st.error(str(exc))
            st.stop()

    runtime: AgentRuntime = st.session_state.runtime

    with st.sidebar:
        st.write(f"Agent: `{runtime.agent_name}`")
        st.write(f"Download dir: `{runtime.download_dir}`")
        if st.button("Start new conversation"):
            runtime.conversation_id = runtime.openai_client.conversations.create().id
            st.session_state.messages = []
            st.rerun()

    for idx, message in enumerate(st.session_state.messages):
        _render_message(message, idx)

    user_input = st.chat_input("Ask about a movie and request plots/tables/files...")
    if not user_input:
        return

    st.session_state.messages.append({"role": "user", "content": user_input})
    _render_message(st.session_state.messages[-1], len(st.session_state.messages) - 1)

    with st.chat_message("assistant"):
        status = st.status("Agent is thinking...", expanded=True)
        progress_placeholder = st.empty()
        progress_events: List[str] = []

        def on_progress(event: str) -> None:
            progress_events.append(event)
            latest_events = progress_events[-6:]
            progress_placeholder.markdown("**Live activity**\n" + "\n".join(f"- {entry}" for entry in latest_events))
            status.update(label=f"Agent is working: {event}", state="running")

        result = _run_turn(runtime, user_input, progress_callback=on_progress)
        status.update(label="Turn completed", state="complete")

        if result.failed:
            assistant_text = f"Turn failed: {result.error_message}"
        else:
            assistant_text = result.output_text or "(No text response returned.)"

        st.markdown(assistant_text)
        _render_generated_files(result.generated_files, f"msg-{len(st.session_state.messages)}")
        if result.logs:
            with st.expander("Debug logs"):
                for log in result.logs:
                    st.text(log)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": assistant_text,
            "files": result.generated_files,
            "logs": result.logs,
        }
    )


if __name__ == "__main__":
    main()

# test: visualize the weekly box office revenue for Life of Pi.