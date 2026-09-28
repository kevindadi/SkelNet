"""Small protocol types shared by the Python orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for one OpenAI-compatible model endpoint."""

    name: str
    provider: str
    model_id: str
    api_key_env: str
    base_url: str
    reasoning_effort: str | None = None
    thinking_enabled: bool = False


def normalize_token_usage(usage: dict[str, Any] | None) -> dict[str, int | None]:
    """Map a provider ``usage`` payload onto explicit token buckets.

    Chat Completions reports ``prompt_tokens`` / ``completion_tokens`` and the
    nested ``*_tokens_details``; Responses reports ``input_tokens`` /
    ``output_tokens`` with ``input_tokens_details`` / ``output_tokens_details``.
    A missing or malformed field is recorded as ``None`` (never coerced to 0).
    """

    if not usage or not isinstance(usage, dict):
        return {"input": None, "output": None, "reasoning": None, "cached": None}
    reasoning = usage.get("reasoning_tokens")
    if reasoning is None:
        reasoning = _nested(usage, "completion_tokens_details", "reasoning_tokens")
    if reasoning is None:
        reasoning = _nested(usage, "output_tokens_details", "reasoning_tokens")
    cached = usage.get("cached_tokens")
    if cached is None:
        cached = _nested(usage, "prompt_tokens_details", "cached_tokens")
    if cached is None:
        cached = _nested(usage, "input_tokens_details", "cached_tokens")
    return {
        "input": _as_int_or_none(usage.get("input_tokens", usage.get("prompt_tokens"))),
        "output": _as_int_or_none(usage.get("output_tokens", usage.get("completion_tokens"))),
        "reasoning": _as_int_or_none(reasoning),
        "cached": _as_int_or_none(cached),
    }


def billable_tokens(tokens: dict[str, Any] | None) -> int:
    """Tokens counted against a budget.

    Chat ``completion_tokens`` and Responses ``output_tokens`` already include
    reasoning tokens, so the total is ``input + output``; ``reasoning`` is only
    used when ``output`` is missing. ``reasoning`` is still recorded separately.
    """
    if not tokens:
        return 0
    inp = tokens.get("input")
    out = tokens.get("output")
    reasoning = tokens.get("reasoning")
    base = inp if isinstance(inp, int) else 0
    if isinstance(out, int):
        return base + out
    if isinstance(reasoning, int):
        return base + reasoning
    return base


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None
