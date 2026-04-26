from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


# USD per 1M tokens. Values are defaults only; override with
# LLM_INPUT_USD_PER_1M and LLM_OUTPUT_USD_PER_1M when using custom/Azure pricing.
MODEL_PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5.5": (1.75, 14.00),
    "gpt-5.1": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5": (1.25, 10.00),
}

DEFAULT_CNY_PER_USD = 7.20


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _usage_value(usage: Any, *names: str) -> int:
    if usage is None:
        return 0
    for name in names:
        if isinstance(usage, dict) and name in usage:
            return _to_int(usage.get(name))
        if hasattr(usage, name):
            return _to_int(getattr(usage, name))
    return 0


def _model_key(model: str | None) -> str | None:
    normalized = (model or "").strip().lower()
    if not normalized:
        return None
    if normalized in MODEL_PRICING_USD_PER_1M:
        return normalized
    for key in sorted(MODEL_PRICING_USD_PER_1M, key=len, reverse=True):
        if key in normalized:
            return key
    return None


def _pricing_for_model(model: str | None) -> tuple[float | None, float | None, str, str | None]:
    env_input = _to_float(os.getenv("LLM_INPUT_USD_PER_1M"))
    env_output = _to_float(os.getenv("LLM_OUTPUT_USD_PER_1M"))
    if env_input is not None and env_output is not None:
        return env_input, env_output, "env_override", model

    key = _model_key(model)
    if key is None:
        return None, None, "unpriced_model", None
    input_price, output_price = MODEL_PRICING_USD_PER_1M[key]
    return input_price, output_price, "default_pricing_table", key


def cny_per_usd() -> float:
    return _to_float(os.getenv("TOKEN_COST_CNY_PER_USD")) or DEFAULT_CNY_PER_USD


def estimate_token_count(text: str, model: str | None = None) -> tuple[int, str]:
    """Return a local token count when possible, otherwise a rough char estimate."""
    try:
        import tiktoken  # type: ignore

        try:
            encoding = tiktoken.encoding_for_model(model or "gpt-4o-mini")
        except Exception:
            encoding = tiktoken.get_encoding("o200k_base")
        return len(encoding.encode(text or "")), "tiktoken"
    except Exception:
        chinese = sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")
        others = len(text or "") - chinese
        return int(chinese / 1.5 + others / 4), "character_estimate"


def token_usage_from_response_usage(
    usage: Any,
    *,
    model: str | None = None,
    source: str = "api_usage_field",
    llm_call_count: int = 1,
) -> dict[str, Any]:
    input_tokens = _usage_value(usage, "prompt_tokens", "input_tokens")
    output_tokens = _usage_value(usage, "completion_tokens", "output_tokens")
    total_tokens = _usage_value(usage, "total_tokens")
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return with_token_cost(
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "llm_call_count": llm_call_count,
            "model": model,
            "source": source if usage is not None else "api_usage_missing",
        },
        model=model,
    )


def token_usage_from_response(
    response: Any,
    *,
    model: str | None = None,
    llm_call_count: int = 1,
) -> dict[str, Any]:
    return token_usage_from_response_usage(
        getattr(response, "usage", None),
        model=model,
        llm_call_count=llm_call_count,
    )


def estimated_token_usage(
    input_text: str,
    output_text: str,
    *,
    model: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    input_tokens, input_source = estimate_token_count(input_text, model)
    output_tokens, output_source = estimate_token_count(output_text, model)
    usage_source = source or (
        "local_tokenizer_estimate" if input_source == output_source == "tiktoken" else "character_estimate"
    )
    note = (
        "estimated locally; provider API usage field was not available"
        if usage_source != "api_usage_field"
        else ""
    )
    return with_token_cost(
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "llm_call_count": 0,
            "model": model,
            "source": usage_source,
            "tokenizer": input_source if input_source == output_source else f"{input_source}/{output_source}",
            "note": note,
        },
        model=model,
    )


def zero_token_usage(*, model: str | None = None, source: str = "no_llm_call") -> dict[str, Any]:
    return with_token_cost(
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_call_count": 0,
            "model": model,
            "source": source,
        },
        model=model,
    )


def calculate_token_cost(token_usage: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
    resolved_model = model or token_usage.get("model")
    input_price, output_price, pricing_source, priced_model = _pricing_for_model(str(resolved_model or ""))
    input_tokens = _to_int(token_usage.get("input_tokens") or token_usage.get("total_input_tokens"))
    output_tokens = _to_int(token_usage.get("output_tokens") or token_usage.get("total_output_tokens"))

    cost = {
        "currency": "USD",
        "model": resolved_model,
        "priced_model": priced_model,
        "pricing_source": pricing_source,
        "input_usd_per_1m_tokens": input_price,
        "output_usd_per_1m_tokens": output_price,
        "input_usd": 0.0,
        "output_usd": 0.0,
        "total_usd": 0.0,
        "total_cny": 0.0,
        "cny_per_usd": cny_per_usd(),
    }
    if input_price is None or output_price is None:
        return cost

    input_usd = input_tokens / 1_000_000 * input_price
    output_usd = output_tokens / 1_000_000 * output_price
    total_usd = input_usd + output_usd
    cost.update(
        {
            "input_usd": round(input_usd, 8),
            "output_usd": round(output_usd, 8),
            "total_usd": round(total_usd, 8),
            "total_cny": round(total_usd * cost["cny_per_usd"], 6),
        }
    )
    return cost


def with_token_cost(token_usage: dict[str, Any] | None, *, model: str | None = None) -> dict[str, Any]:
    usage = dict(token_usage or {})
    input_tokens = _to_int(usage.get("input_tokens") or usage.get("total_input_tokens"))
    output_tokens = _to_int(usage.get("output_tokens") or usage.get("total_output_tokens"))
    total_tokens = _to_int(usage.get("total_tokens"))
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    usage["input_tokens"] = input_tokens
    usage["output_tokens"] = output_tokens
    usage["total_tokens"] = total_tokens
    usage["llm_call_count"] = _to_int(usage.get("llm_call_count"))
    if model and not usage.get("model"):
        usage["model"] = model
    usage["estimated_cost"] = calculate_token_cost(usage, model=model)
    return usage


def aggregate_token_usage(
    usages: list[dict[str, Any] | None],
    *,
    model: str | None = None,
    source: str = "aggregate",
) -> dict[str, Any]:
    input_tokens = sum(_to_int((usage or {}).get("input_tokens") or (usage or {}).get("total_input_tokens")) for usage in usages)
    output_tokens = sum(
        _to_int((usage or {}).get("output_tokens") or (usage or {}).get("total_output_tokens")) for usage in usages
    )
    llm_call_count = sum(_to_int((usage or {}).get("llm_call_count")) for usage in usages)
    counted_records = sum(1 for usage in usages if usage)
    models = sorted({str((usage or {}).get("model")) for usage in usages if (usage or {}).get("model")})
    sources = sorted({str((usage or {}).get("source")) for usage in usages if (usage or {}).get("source")})
    resolved_model = model or (models[0] if len(models) == 1 else None)
    aggregated = with_token_cost(
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "llm_call_count": llm_call_count,
            "record_count": counted_records,
            "model": resolved_model,
            "models": models,
            "sources": sources,
            "source": source,
        },
        model=resolved_model,
    )
    child_costs = [
        (usage or {}).get("estimated_cost")
        for usage in usages
        if isinstance((usage or {}).get("estimated_cost"), dict)
    ]
    if child_costs and (resolved_model is None or len(models) > 1):
        total_usd = sum(float(cost.get("total_usd") or 0.0) for cost in child_costs)
        input_usd = sum(float(cost.get("input_usd") or 0.0) for cost in child_costs)
        output_usd = sum(float(cost.get("output_usd") or 0.0) for cost in child_costs)
        rate = cny_per_usd()
        aggregated["estimated_cost"] = {
            "currency": "USD",
            "model": resolved_model,
            "priced_model": None,
            "pricing_source": "summed_child_costs",
            "input_usd_per_1m_tokens": None,
            "output_usd_per_1m_tokens": None,
            "input_usd": round(input_usd, 8),
            "output_usd": round(output_usd, 8),
            "total_usd": round(total_usd, 8),
            "total_cny": round(total_usd * rate, 6),
            "cny_per_usd": rate,
        }
    return aggregated


def post_trace_webhook(record: dict[str, Any]) -> bool:
    """Best-effort trace upload hook for an external dashboard or log pipeline."""
    url = os.getenv("EVAL_TRACE_WEBHOOK_URL", "").strip()
    if not url:
        return False
    timeout = _to_float(os.getenv("EVAL_TRACE_WEBHOOK_TIMEOUT_S")) or 2.0
    payload = json.dumps(record, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except Exception:
        return False
