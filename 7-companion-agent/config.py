from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None


@dataclass(slots=True)
class Settings:
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = ""
    openai_api_version: str = ""
    amap_api_key: str = ""
    default_city: str = "北京"
    request_timeout_s: int = 20

    @staticmethod
    def _normalize_openai_base_url(raw_base_url: str) -> str:
        base_url = raw_base_url.strip().rstrip("/")
        if not base_url:
            return ""

        if base_url.endswith("/openai/v1"):
            return f"{base_url}/"

        if "/api/projects/" in base_url:
            return f"{base_url}/openai/v1/"

        if base_url.endswith(".openai.azure.com") or base_url.endswith(".services.ai.azure.com"):
            return f"{base_url}/openai/v1/"

        return f"{base_url}/" if base_url.endswith("/openai") else base_url

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(__file__).resolve().parent.parent
        if load_dotenv:
            load_dotenv(root / ".env", override=False)
            load_dotenv(override=False)

        api_key = (
            os.getenv("OPENAI_API_KEY", "").strip()
            or os.getenv("AZURE_OPENAI_API_KEY", "").strip()
            or os.getenv("FOUNDRY_PROJECT_API_KEY", "").strip()
        )
        base_url = cls._normalize_openai_base_url(
            os.getenv("OPENAI_BASE_URL", "").strip()
            or os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
            or os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
        )
        model = (
            os.getenv("OPENAI_MODEL", "").strip()
            or os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
            or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "").strip()
            or os.getenv("AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME", "").strip()
            or os.getenv("FOUNDRY_PROJECT_DEPLOYMENT", "").strip()
            or os.getenv("FOUNDRY_MODEL", "").strip()
            or "gpt-4o-mini"
        )

        return cls(
            openai_api_key=api_key,
            openai_base_url=base_url,
            openai_model=model,
            openai_api_version=(
                os.getenv("OPENAI_API_VERSION", "").strip()
                or os.getenv("AZURE_OPENAI_API_VERSION", "").strip()
                or "2024-10-21"
            ),
            amap_api_key=os.getenv("AMAP_API_KEY", "").strip(),
            default_city=os.getenv("DEFAULT_CITY", "北京").strip() or "北京",
            request_timeout_s=int(os.getenv("REQUEST_TIMEOUT_S", "20").strip() or "20"),
        )

    @property
    def has_llm_credentials(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)

    @property
    def has_amap_key(self) -> bool:
        return bool(self.amap_api_key)

    @property
    def is_azure_openai(self) -> bool:
        base = self.openai_base_url.lower()
        return ".openai.azure.com" in base or ".services.ai.azure.com" in base or "api-version" in base

    @property
    def azure_endpoint(self) -> str:
        base = self.openai_base_url.strip().rstrip("/")
        if not base:
            return ""
        if "/openai/" in base:
            return base.split("/openai/", 1)[0]
        return base
