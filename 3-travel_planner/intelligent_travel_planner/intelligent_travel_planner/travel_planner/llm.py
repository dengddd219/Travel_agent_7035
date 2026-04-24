## author:SUN Bin
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at import time
    OpenAI = None

"""Thin wrapper around the OpenAI-compatible client.

We keep the LLM initialization in a small dedicated module so the rest of the
system never needs to know SDK-specific setup details.
"""


@dataclass(slots=True)
class ResponseClientBundle:
    """Minimal bundle containing the client object and chosen deployment name."""
    client: object
    model: str


def create_response_client(settings: Settings) -> ResponseClientBundle:
    """Build the response client used by agent orchestration and UI polishing."""
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
