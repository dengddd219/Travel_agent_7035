## author:SUN Bin
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

"""Environment-backed runtime settings.

All runtime configuration is intentionally concentrated here so the rest of the
codebase can depend on a single typed object instead of reading env vars
everywhere.
"""


@dataclass(slots=True)
class Settings:
    """Typed application settings loaded from `.env`."""
    foundry_resource: str = ""
    foundry_api_key: str = ""
    foundry_deployment: str = ""
    foundry_project_endpoint: str = ""
    amap_api_key: str = ""
    tavily_api_key: str = ""
    default_city: str = "Hong Kong"

    @classmethod
    def from_env(cls) -> "Settings":
        """Load all supported settings from environment variables."""
        _root = Path(__file__).resolve().parents[3]
        load_dotenv(_root / ".env", override=False)
        load_dotenv(override=False)
        return cls(
            foundry_resource=os.getenv("FOUNDRY_PROJECT_RESOURCE", "").strip(),
            foundry_api_key=os.getenv("FOUNDRY_PROJECT_API_KEY", "").strip(),
            foundry_deployment=os.getenv("FOUNDRY_PROJECT_DEPLOYMENT", "").strip(),
            foundry_project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip(),
            amap_api_key=os.getenv("AMAP_API_KEY", "").strip(),
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
            default_city=os.getenv("DEFAULT_CITY", "Hong Kong").strip() or "Hong Kong",
        )

    @property
    def has_llm_credentials(self) -> bool:
        """Whether the Azure / Foundry LLM connection can be used."""
        return bool(self.foundry_api_key and self.foundry_deployment and self.foundry_resource)

    @property
    def has_amap_key(self) -> bool:
        """Whether Amap-backed search and routing can call the real API."""
        return bool(self.amap_api_key)

    @property
    def azure_base_url(self) -> str:
        """Construct the Azure OpenAI compatible base URL from the resource name."""
        if not self.foundry_resource:
            return ""
        return f"https://{self.foundry_resource}.openai.azure.com/openai/v1/"
