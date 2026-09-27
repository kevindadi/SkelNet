"""Official OpenAI SDK clients for the Python ConcIR workflow.

DeepSeek and Qwen expose different OpenAI-compatible surfaces in this
project: DeepSeek uses Chat Completions while Qwen uses Responses. The
workflow only consumes the small common ``chat`` method below, so prompting
and repair logic stay provider-neutral.
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

from .models import ModelConfig


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


class _OpenAIClientBase:
    """Shared API-key, retry, and SDK-client construction behavior."""

    def __init__(
        self,
        model: ModelConfig,
        *,
        timeout: float = 180.0,
        max_retries: int = 3,
        sdk_client: Any | None = None,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.client = sdk_client or _build_openai_client(model, timeout)

    def _call_with_retries(self, request: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(min(2 ** (attempt - 1), 8))
            try:
                return request()
            except Exception as error:  # SDK exceptions vary by provider/version.
                last_error = error
                if attempt >= self.max_retries:
                    break
        raise LlmError(str(last_error or "LLM request failed"))


class DeepSeekClient(_OpenAIClientBase):
    """DeepSeek Chat Completions client."""

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[str, dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model": self.model.model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if self.model.reasoning_effort:
            kwargs["reasoning_effort"] = self.model.reasoning_effort
        if self.model.thinking_enabled:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        response = self._call_with_retries(
            lambda: self.client.chat.completions.create(**kwargs)
        )
        try:
            message = response.choices[0].message
            content = getattr(message, "content", None)
            usage = _as_dict(getattr(response, "usage", None))
        except (AttributeError, IndexError, TypeError) as error:
            raise LlmError(f"invalid DeepSeek response: {error}") from error
        return _require_text(content, "DeepSeek"), usage


class QwenClient(_OpenAIClientBase):
    """Qwen Responses API client."""

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[str, dict[str, Any]]:
        # Qwen's compatible Responses endpoint accepts a string input. Keeping
        # the system prompt in that input works across workspace and public
        # DashScope endpoints, which do not all expose identical parameters.
        prompt = (
            "[SYSTEM INSTRUCTIONS]\n"
            f"{system_prompt}\n\n"
            "[USER REQUEST]\n"
            f"{user_prompt}"
        )
        # Keep this call compatible with the documented Qwen Responses form:
        # ``responses.create(model=..., input=...)``. Unlike Chat Completions,
        # workspace Responses endpoints do not consistently accept temperature,
        # max-token, or thinking extension fields.
        kwargs: dict[str, Any] = {"model": self.model.model_id, "input": prompt}

        response = self._call_with_retries(
            lambda: self.client.responses.create(**kwargs)
        )
        content = getattr(response, "output_text", None)
        if not content:
            content = _responses_output_text(response)
        usage = _as_dict(getattr(response, "usage", None))
        return _require_text(content, "Qwen"), usage


def create_llm_client(
    model: ModelConfig,
    *,
    timeout: float = 180.0,
    max_retries: int = 3,
    sdk_client: Any | None = None,
) -> LlmClient:
    """Construct the provider-specific client selected by ``model.provider``."""

    provider = model.provider.strip().lower()
    if provider in {"deepseek", "deepseek-chat"}:
        return DeepSeekClient(
            model,
            timeout=timeout,
            max_retries=max_retries,
            sdk_client=sdk_client,
        )
    if provider in {"qwen", "dashscope", "qwen-responses"}:
        return QwenClient(
            model,
            timeout=timeout,
            max_retries=max_retries,
            sdk_client=sdk_client,
        )
    raise ValueError(
        f"unsupported LLM provider {model.provider!r}; expected deepseek or qwen"
    )


def default_base_url(provider: str) -> str:
    """Return the documented endpoint default for a provider."""

    normalized = provider.strip().lower()
    if normalized in {"deepseek", "deepseek-chat"}:
        return os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    if normalized in {"qwen", "dashscope", "qwen-responses"}:
        return os.environ.get(
            "QWEN_BASE_URL",
            os.environ.get(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    raise ValueError(f"unsupported LLM provider {provider!r}")


def _build_openai_client(model: ModelConfig, timeout: float) -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise LlmError(
            "The Python OpenAI SDK is required. Install dependencies with "
            "python -m pip install -r python/requirements.txt"
        ) from error

    api_key = os.environ.get(model.api_key_env, "")
    if not api_key:
        raise LlmError(f"missing API key: set env var {model.api_key_env}")
    return OpenAI(
        api_key=api_key,
        base_url=model.base_url,
        timeout=timeout,
        max_retries=0,
    )


def _require_text(value: Any, provider: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise LlmError(f"{provider} response did not contain assistant text")


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _responses_output_text(response: Any) -> str | None:
    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        item_content = (
            item.get("content", [])
            if isinstance(item, dict)
            else getattr(item, "content", [])
        )
        for content in item_content or []:
            text = (
                content.get("text")
                if isinstance(content, dict)
                else getattr(content, "text", None)
            )
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts) or None
