from __future__ import annotations

from dataclasses import dataclass

from .config import Settings

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at import time
    OpenAI = None


@dataclass(slots=True)
class ResponseClientBundle:
    client: object
    model: str


def create_response_client(settings: Settings) -> ResponseClientBundle:
    if OpenAI is None:
        raise RuntimeError(
            "The `openai` package is not installed. Run `python3 -m pip install -r requirements.txt` first."
        )
    if not settings.has_llm_credentials:
        raise RuntimeError(
            "LLM credentials are incomplete. Please set FOUNDRY_PROJECT_RESOURCE, "
            "FOUNDRY_PROJECT_API_KEY, and FOUNDRY_PROJECT_DEPLOYMENT."
        )

    client = OpenAI(
        base_url=settings.azure_base_url,
        api_key=settings.foundry_api_key,
    )
    return ResponseClientBundle(client=client, model=settings.foundry_deployment)
