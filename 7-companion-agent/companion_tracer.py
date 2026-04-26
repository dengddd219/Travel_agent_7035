from __future__ import annotations

import json
import os
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TRUTHY = {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    return (
        os.getenv("TRACE_AGENT", "").strip().lower() in _TRUTHY
        or os.getenv("DEBUG_AGENT", "").strip().lower() in _TRUTHY
    )


def preview_chars() -> int:
    raw = os.getenv("TRACE_PREVIEW_CHARS", "").strip()
    if not raw:
        return 1600
    try:
        return max(0, int(raw))
    except ValueError:
        return 1600


def trace_full() -> bool:
    return os.getenv("TRACE_FULL", "").strip().lower() in _TRUTHY


_C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "red": "\033[31m",
    "white": "\033[97m",
}


def _c(text: str, *codes: str) -> str:
    if not is_enabled():
        return text
    return "".join(_C.get(code, "") for code in codes) + text + _C["reset"]


def _short_json(value: Any, limit: int | None = None) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        text = str(value)
    if trace_full():
        return text
    limit = preview_chars() if limit is None else limit
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _jsonl_path() -> Path | None:
    raw = os.getenv("TRACE_JSONL_PATH", "").strip()
    return Path(raw) if raw else None


def _write_event(event: str, payload: dict[str, Any]) -> None:
    path = _jsonl_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": "companion",
            "event": event,
            **payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def header(title: str, color: str = "cyan") -> None:
    if not is_enabled():
        return
    print()
    print(_c("=" * 78, color))
    print(_c(title, "bold", color))
    print(_c("-" * 78, "dim"))


def kv(key: str, value: Any, *, indent: int = 2, limit: int | None = None) -> None:
    if not is_enabled():
        return
    pad = " " * indent
    text = value if isinstance(value, str) else _short_json(value, limit=limit)
    wrapped = textwrap.fill(str(text), width=108, subsequent_indent=pad + "  ")
    print(f"{pad}{_c(key + ':', 'bold', 'white')} {_c(wrapped, 'dim')}")


def event(title: str, payload: dict[str, Any] | None = None, *, color: str = "cyan") -> None:
    payload = payload or {}
    if is_enabled():
        header(title, color=color)
        for key, value in payload.items():
            kv(key, value)
    _write_event(title, payload)


def tool_start(tool_name: str, arguments: dict[str, Any]) -> None:
    event(
        f"Companion tool start | {tool_name}",
        {"arguments": arguments},
        color="magenta",
    )


def tool_finish(tool_name: str, arguments: dict[str, Any], output: Any, elapsed_ms: int) -> None:
    payload: dict[str, Any] = {
        "elapsed_ms": elapsed_ms,
        "arguments": arguments,
        "output": output,
    }
    event(
        f"Companion tool done | {tool_name}",
        payload,
        color="green",
    )


def tool_error(tool_name: str, arguments: dict[str, Any], error: Exception, elapsed_ms: int) -> None:
    event(
        f"Companion tool error | {tool_name}",
        {
            "elapsed_ms": elapsed_ms,
            "arguments": arguments,
            "error": f"{type(error).__name__}: {error}",
        },
        color="red",
    )

