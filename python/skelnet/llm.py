"""Shared LLM protocol types.

The concrete clients live in ``direct.py`` (Chat) and ``opencode_go.py`` (Chat
and Responses); this module keeps only the small common surface they share.
"""

from __future__ import annotations

from typing import Any, Protocol


class LlmError(RuntimeError):
    """A model request failed or returned an unusable response."""


class LlmClient(Protocol):
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[str, dict[str, Any]]:
        """Return assistant text and provider usage metadata."""
