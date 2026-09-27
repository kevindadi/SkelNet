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


def normalize_token_usage(usage: dict[str, Any] | None) -> tuple[int, int]:
    """Map provider ``usage`` payloads onto ``(input_tokens, output_tokens)``.

    DeepSeek's Chat Completions endpoint reports ``prompt_tokens`` and
    ``completion_tokens``; Qwen's Responses endpoint reports ``input_tokens``
    and ``output_tokens``. Missing or malformed fields count as zero.
    """

    if not usage:
        return 0, 0
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    return _as_int(input_tokens), _as_int(output_tokens)


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
