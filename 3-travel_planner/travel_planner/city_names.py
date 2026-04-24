## author:SUN Bin
from __future__ import annotations

"""Centralized city-name normalization.

Why this file matters:
- users may type city names in Chinese or English
- city profiles use canonical English names
- provider APIs and RAG corpus often prefer Chinese names

So every layer should route through this registry instead of hardcoding its own
city-name mapping.
"""

# Canonical city registry used across profile loading, API calls, and UI output.
CITY_NAME_REGISTRY = {
    "Hong Kong": {"zh": "香港", "en": "Hong Kong"},
    "Tokyo": {"zh": "东京", "en": "Tokyo"},
    "Chengdu": {"zh": "成都", "en": "Chengdu"},
    "Shanghai": {"zh": "上海", "en": "Shanghai"},
    "Beijing": {"zh": "北京", "en": "Beijing"},
    "Guangzhou": {"zh": "广州", "en": "Guangzhou"},
    "Shenzhen": {"zh": "深圳", "en": "Shenzhen"},
    "Hangzhou": {"zh": "杭州", "en": "Hangzhou"},
    "Xian": {"zh": "西安", "en": "Xian"},
    "Chongqing": {"zh": "重庆", "en": "Chongqing"},
    "Xiamen": {"zh": "厦门", "en": "Xiamen"},
    "Nanjing": {"zh": "南京", "en": "Nanjing"},
}

RAG_FOLDER_REGISTRY = {
    "Hong Kong": "hongkong",
    "Tokyo": "tokyo",
    "Chengdu": "chengdu",
    "Shanghai": "shanghai",
    "Beijing": "beijing",
    "Guangzhou": "guangzhou",
    "Shenzhen": "shenzhen",
    "Hangzhou": "hangzhou",
    "Xian": "xian",
    "Chongqing": "chongqing",
    "Xiamen": "xiamen",
    "Nanjing": "nanjing",
}

CITY_ALIASES = {
    "hong kong": "Hong Kong",
    "香港": "Hong Kong",
    "tokyo": "Tokyo",
    "东京": "Tokyo",
    "chengdu": "Chengdu",
    "成都": "Chengdu",
    "shanghai": "Shanghai",
    "上海": "Shanghai",
    "beijing": "Beijing",
    "北京": "Beijing",
    "guangzhou": "Guangzhou",
    "广州": "Guangzhou",
    "shenzhen": "Shenzhen",
    "深圳": "Shenzhen",
    "hangzhou": "Hangzhou",
    "杭州": "Hangzhou",
    "xian": "Xian",
    "xi'an": "Xian",
    "西安": "Xian",
    "chongqing": "Chongqing",
    "重庆": "Chongqing",
    "xiamen": "Xiamen",
    "厦门": "Xiamen",
    "nanjing": "Nanjing",
    "南京": "Nanjing",
}


def normalize_city_name(city: str | None) -> str:
    """Normalize free-form user input into one canonical city key."""
    raw = (city or "").strip()
    if not raw:
        return ""
    return CITY_ALIASES.get(raw.lower(), raw)


def city_name_bundle(city: str | None) -> dict[str, str]:
    """Return all useful name variants for one city.

    The planner mainly stores the canonical English name, while:
    - RAG often needs a folder name or Chinese city
    - UI sometimes wants Chinese display text
    - some providers work better with English
    """
    canonical = normalize_city_name(city)
    bundle = CITY_NAME_REGISTRY.get(canonical)
    if bundle:
        return {
            "canonical": canonical,
            "city_en": bundle["en"],
            "city_zh": bundle["zh"],
        }
    return {
        "canonical": canonical,
        "city_en": canonical,
        "city_zh": canonical,
    }


def provider_city_name(city: str | None, provider: str = "zh") -> str:
    """Return the city name in the format preferred by a downstream provider."""
    bundle = city_name_bundle(city)
    if provider == "en":
        return bundle["city_en"]
    return bundle["city_zh"]


def rag_city_folder(city: str | None) -> str | None:
    """Map a city to the folder name used by the delivered RAG corpus."""
    canonical = normalize_city_name(city)
    if not canonical:
        return None
    return RAG_FOLDER_REGISTRY.get(canonical)
