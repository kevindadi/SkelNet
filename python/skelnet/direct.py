"""Direct OpenAI-compatible Chat client (DeepSeek and DashScope/Qwen).

The client is parameterised by :class:`~skelnet.params.RunParams`: thinking is
sent through ``extra_body`` (per channel), temperature is omitted under
``provider_default``, per-cell seeds are sent only when the model supports them,
and a truncated/empty reply is retried once with a larger output cap.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .params import seed_for
from .transport import TemperatureRejected, TransportTruncated, create_with_retries


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class DirectOutcome:
    text: str
    messages: list[dict[str, str]]
    requested_model: str
    response_model: str | None
    request_id: str | None
    finish_reason: str | None
    usage: dict[str, Any] | None
    wall_ms: int
    transport_attempt: int
    prompt_sha256: str
    cost: float | None = None
    reasoning_content: str | None = None
    seed: int | None = None


class DirectChatClient:
    def __init__(self, *, api_key: str, base_url: str, model: str, budget: Any,
                 evidence_dir: Path | str, params: Any, timeout: float = 90.0,
                 sdk_client: Any | None = None,
                 extra_body: dict[str, Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.model = model
        self.base_url = base_url
        self.budget = budget
        self.params = params
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.evidence_dir / "requests.jsonl"
        self.timeout = float(timeout)
        self.extra_body = extra_body or {}
        self.sleep = sleep
        self.stream = bool(getattr(params, "stream", False))
        self.task_id: str | None = None
        self.replicate = 0
        if sdk_client is not None:
            self._client = sdk_client
        else:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, base_url=base_url,
                                  timeout=timeout, max_retries=0)

    def set_cell(self, task_id: str, replicate: int) -> None:
        self.task_id = task_id
        self.replicate = replicate

    def _seed(self) -> int | None:
        if (self.params.seed_policy == "per_cell" and self.params.supports_seed
                and self.task_id is not None):
            return seed_for(self.task_id, self.replicate)
        return None

    def _record(self, record: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _kwargs(self, messages: list, max_tokens: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages,
                                  "max_tokens": max_tokens}
        if self.params.temperature_policy == "fixed":
            kwargs["temperature"] = self.params.temperature
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        seed = self._seed()
        if seed is not None:
            kwargs["seed"] = seed
        return kwargs

    def _create(self, kwargs: dict) -> Any:
        if self.stream:
            return self._client.chat.completions.create(
                **kwargs, stream=True, stream_options={"include_usage": True})
        return self._client.chat.completions.create(**kwargs)

    def _parse(self, response: Any) -> dict[str, Any]:
        if self.stream:
            return self._parse_stream(response)
        choice = (getattr(response, "choices", None) or [None])[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) or ""
        reasoning = getattr(message, "reasoning_content", None)
        usage = _as_dict(getattr(response, "usage", None))
        return {"text": content, "reasoning": reasoning,
                "finish_reason": getattr(choice, "finish_reason", None),
                "usage": usage, "response_model": getattr(response, "model", None),
                "request_id": getattr(response, "id", None),
                "cost": getattr(response, "cost", None)}

    def _parse_stream(self, stream: Any) -> dict[str, Any]:
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason = None
        usage: dict[str, Any] = {}
        response_model = None
        request_id = None
        for chunk in stream:
            response_model = getattr(chunk, "model", None) or response_model
            request_id = getattr(chunk, "id", None) or request_id
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = _as_dict(chunk_usage)
            for choice in getattr(chunk, "choices", None) or []:
                delta = getattr(choice, "delta", None)
                if delta is not None:
                    piece = getattr(delta, "content", None)
                    if piece:
                        text_parts.append(piece)
                    reason_piece = getattr(delta, "reasoning_content", None)
                    if reason_piece:
                        reasoning_parts.append(reason_piece)
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason
        return {"text": "".join(text_parts),
                "reasoning": "".join(reasoning_parts) or None,
                "finish_reason": finish_reason, "usage": usage,
                "response_model": response_model, "request_id": request_id,
                "cost": None}

    def _truncated(self, text: str, finish_reason: str | None) -> bool:
        return finish_reason == "length" or not text.strip()

    def complete(self, system_prompt: str, user_prompt: str) -> DirectOutcome:
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}]
        prompt_sha = _sha(json.dumps(messages, ensure_ascii=False, sort_keys=True))
        self.budget.reserve()
        started = time.monotonic()
        max_tokens = self.params.max_output_tokens
        truncation_retry = False
        transport_attempt = 1
        parsed: dict[str, Any] = {}
        for attempt_index in range(2):
            kwargs = self._kwargs(messages, max_tokens)
            try:
                response, transport_attempt = create_with_retries(
                    lambda: self._create(kwargs), sleep=self.sleep)
            except Exception as exc:  # noqa: BLE001
                if "temperature" in str(exc).lower():
                    self._record_error(messages, prompt_sha, exc, started, kwargs)
                    raise TemperatureRejected(str(exc)) from exc
                self._record_error(messages, prompt_sha, exc, started, kwargs)
                raise
            parsed = self._parse(response)
            if not self._truncated(parsed["text"], parsed["finish_reason"]):
                break
            if attempt_index == 0:
                truncation_retry = True
                max_tokens = min(2 * max_tokens,
                                 getattr(self.params, "max_output_tokens_cap", 65536))
                continue
            wall_ms = int((time.monotonic() - started) * 1000)
            self._record({"status": "error", "model": self.model, "base_url": self.base_url,
                          "messages": messages, "prompt_sha256": prompt_sha,
                          "finish_reason": parsed["finish_reason"], "usage": parsed["usage"],
                          "truncation_retry": truncation_retry,
                          "error": "transport_truncated", "wall_ms": wall_ms})
            raise TransportTruncated()
        wall_ms = int((time.monotonic() - started) * 1000)
        self._record({
            "status": "ok", "model": self.model, "base_url": self.base_url,
            "response_model": parsed["response_model"], "request_id": parsed["request_id"],
            "messages": messages, "prompt_sha256": prompt_sha, "usage": parsed["usage"],
            "finish_reason": parsed["finish_reason"], "stream": self.stream,
            "seed": self._seed(), "truncation_retry": truncation_retry,
            "reasoning_content": parsed["reasoning"],
            "content_sha256": _sha(parsed["text"]), "content": parsed["text"],
            "wall_ms": wall_ms,
        })
        return DirectOutcome(
            text=parsed["text"], messages=messages, requested_model=self.model,
            response_model=parsed["response_model"], request_id=parsed["request_id"],
            finish_reason=parsed["finish_reason"], usage=parsed["usage"] or None,
            wall_ms=wall_ms, transport_attempt=transport_attempt, prompt_sha256=prompt_sha,
            cost=parsed["cost"], reasoning_content=parsed["reasoning"],
            seed=self._seed())

    def _record_error(self, messages, prompt_sha, exc, started, kwargs) -> None:
        self._record({"status": "error", "model": self.model, "base_url": self.base_url,
                      "messages": messages, "prompt_sha256": prompt_sha,
                      "error": str(exc), "error_type": type(exc).__name__,
                      "wall_ms": int((time.monotonic() - started) * 1000)})


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}
