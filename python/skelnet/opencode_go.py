"""OpenCode Go clients (Chat Completions and Responses).

Both mirror ``DirectChatClient``'s ``complete(system, user)`` surface. The
session header is refreshed per cell (``new_session``), retries are bounded, and
truncated/empty replies are retried once with a larger cap. Every real request
(including the truncation retry) reserves global budget and records its usage.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import normalize_token_usage
from .params import seed_for
from .transport import TemperatureRejected, TransportTruncated, create_with_retries

OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


@dataclass
class OpenCodeOutcome:
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
    session: str | None = None
    seed: int | None = None
    truncation_retry: bool = False
    finish_reasons: list[str | None] = field(default_factory=list)
    usage_attempts: list[dict[str, Any]] = field(default_factory=list)
    temperature_sent: float | None = None
    # Probe-only observations. Experiment calls leave these unset.
    responses_reasoning_echo: Any = None
    responses_reasoning_items: int | None = None
    responses_output_tokens_details: Any = None
    responses_reasoning_summary_present: bool | None = None


class _OpenCodeBase:
    def __init__(self, *, api_key: str, base_url: str, model: str, budget: Any,
                 evidence_dir: Path | str, params: Any, timeout: float = 90.0,
                 sdk_client: Any | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.model = model
        self.base_url = base_url or OPENCODE_GO_BASE_URL
        self.budget = budget
        self.params = params
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.evidence_dir / "requests.jsonl"
        self.timeout = float(timeout)
        self.sleep = sleep
        self.task_id: str | None = None
        self.replicate = 0
        self.session = str(uuid.uuid4())
        # Set only by the model probe. Experiment runs leave this None, so
        # ``reasoning.summary`` is never sent.
        self.reasoning_summary: str | None = None
        if sdk_client is not None:
            self._client = sdk_client
        else:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, base_url=self.base_url,
                                  timeout=timeout, max_retries=0)

    def new_session(self) -> None:
        self.session = str(uuid.uuid4())

    def set_cell(self, task_id: str, replicate: int) -> None:
        self.task_id = task_id
        self.replicate = replicate

    def _seed(self) -> int | None:
        if (self.params.seed_policy == "per_cell" and self.params.supports_seed
                and self.task_id is not None):
            return seed_for(self.task_id, self.replicate)
        return None

    def _temperature_sent(self) -> float | None:
        if self.params.temperature_policy == "fixed":
            return self.params.temperature
        return None

    def _add_tokens(self, usage: Any) -> None:
        add = getattr(self.budget, "add_tokens", None)
        if add is not None:
            add(normalize_token_usage(usage))

    def _reserve_and_create(self, kwargs: dict) -> Any:
        self.budget.reserve()
        return self._create(kwargs)

    def _record(self, record: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _truncated(self, text: str, finish_reason: str | None) -> bool:
        return finish_reason == "length" or not text.strip()

    def _next_cap(self, current: int) -> int:
        return min(2 * current, getattr(self.params, "max_output_tokens_cap", 65536))


class OpenCodeGoClient(_OpenCodeBase):
    """OpenCode Go via ``/chat/completions`` (e.g. Kimi)."""

    def _kwargs(self, messages: list, max_tokens: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages,
                                  "max_tokens": max_tokens,
                                  "extra_headers": {"x-opencode-session": self.session}}
        if self.params.temperature_policy == "fixed":
            kwargs["temperature"] = self.params.temperature
        if self.params.reasoning_effort:
            kwargs["reasoning_effort"] = self.params.reasoning_effort
        seed = self._seed()
        if seed is not None:
            kwargs["seed"] = seed
        return kwargs

    def _create(self, kwargs: dict) -> Any:
        return self._client.chat.completions.create(**kwargs)

    def complete(self, system_prompt: str, user_prompt: str) -> OpenCodeOutcome:
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}]
        prompt_sha = _sha(json.dumps(messages, ensure_ascii=False, sort_keys=True))
        started = time.monotonic()
        max_tokens = self.params.max_output_tokens
        truncation_retry = False
        transport_attempt = 1
        finish_reasons: list[str | None] = []
        usage_attempts: list[dict[str, Any]] = []
        content = ""
        finish_reason = None
        usage: dict[str, Any] = {}
        response = None
        for attempt_index in range(2):
            kwargs = self._kwargs(messages, max_tokens)
            try:
                response, transport_attempt = create_with_retries(
                    lambda: self._reserve_and_create(kwargs), sleep=self.sleep)
            except Exception as exc:  # noqa: BLE001
                if "temperature" in str(exc).lower():
                    self._record_error(messages, prompt_sha, exc, started, kwargs)
                    raise TemperatureRejected(str(exc)) from exc
                self._record_error(messages, prompt_sha, exc, started, kwargs)
                raise
            choice = (getattr(response, "choices", None) or [None])[0]
            message = getattr(choice, "message", None)
            content = getattr(message, "content", None) or ""
            finish_reason = getattr(choice, "finish_reason", None)
            usage = _as_dict(getattr(response, "usage", None))
            finish_reasons.append(finish_reason)
            usage_attempts.append(usage)
            self._add_tokens(usage)
            truncated = self._truncated(content, finish_reason)
            self._record({"status": "truncated" if truncated else "ok",
                          "model": self.model, "session": self.session,
                          "response_model": getattr(response, "model", None),
                          "request_id": getattr(response, "id", None),
                          "messages": messages, "prompt_sha256": prompt_sha,
                          "usage": usage, "cost": getattr(response, "cost", None),
                          "max_tokens": max_tokens, "finish_reason": finish_reason,
                          "seed": self._seed(), "truncation_retry": truncation_retry,
                          "content_sha256": _sha(content), "content": content,
                          "wall_ms": int((time.monotonic() - started) * 1000)})
            if not truncated:
                break
            if attempt_index == 0:
                truncation_retry = True
                max_tokens = self._next_cap(max_tokens)
                continue
            raise TransportTruncated(
                truncation_retry=truncation_retry,
                finish_reasons=finish_reasons,
                usage_attempts=usage_attempts)
        wall_ms = int((time.monotonic() - started) * 1000)
        return OpenCodeOutcome(
            text=content, messages=messages, requested_model=self.model,
            response_model=getattr(response, "model", None),
            request_id=getattr(response, "id", None), finish_reason=finish_reason,
            usage=usage or None, wall_ms=wall_ms, transport_attempt=transport_attempt,
            prompt_sha256=prompt_sha, cost=getattr(response, "cost", None),
            session=self.session, seed=self._seed(), truncation_retry=truncation_retry,
            finish_reasons=finish_reasons, usage_attempts=usage_attempts,
            temperature_sent=self._temperature_sent())

    def _record_error(self, messages, prompt_sha, exc, started, kwargs) -> None:
        self._record({"status": "error", "model": self.model, "session": self.session,
                      "messages": messages, "prompt_sha256": prompt_sha,
                      "max_tokens": kwargs.get("max_tokens"), "finish_reason": None,
                      "error": str(exc), "error_type": type(exc).__name__,
                      "wall_ms": int((time.monotonic() - started) * 1000)})


class OpenCodeGoResponsesClient(_OpenCodeBase):
    """OpenCode Go via ``/responses`` (e.g. GPT 6 Luna)."""

    def _kwargs(self, system_prompt: str, user_prompt: str,
                max_tokens: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model, "instructions": system_prompt,
            "input": user_prompt, "max_output_tokens": max_tokens,
            "extra_headers": {"x-opencode-session": self.session},
        }
        if self.params.temperature_policy == "fixed":
            kwargs["temperature"] = self.params.temperature
        if self.params.reasoning_effort:
            reasoning: dict[str, Any] = {"effort": self.params.reasoning_effort}
            if self.reasoning_summary:
                reasoning["summary"] = self.reasoning_summary
            kwargs["reasoning"] = reasoning
        return kwargs

    def _create(self, kwargs: dict) -> Any:
        return self._client.responses.create(**kwargs)

    def _parse(self, response: Any) -> dict[str, Any]:
        echo = _plain(getattr(response, "reasoning", None))
        return {"text": getattr(response, "output_text", None) or "",
                "finish_reason": _responses_finish_reason(response),
                "usage": _as_dict(getattr(response, "usage", None)),
                "response_model": getattr(response, "model", None),
                "request_id": getattr(response, "id", None),
                "cost": getattr(response, "cost", None),
                "responses_reasoning_echo": echo if isinstance(echo, dict) else None,
                "responses_reasoning_items": _reasoning_item_count(response),
                "responses_output_tokens_details": _output_token_details(response),
                "responses_reasoning_summary_present": _summary_present(response, echo)}

    def complete(self, system_prompt: str, user_prompt: str) -> OpenCodeOutcome:
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}]
        prompt_sha = _sha(json.dumps(messages, ensure_ascii=False, sort_keys=True))
        started = time.monotonic()
        max_tokens = self.params.max_output_tokens
        truncation_retry = False
        transport_attempt = 1
        finish_reasons: list[str | None] = []
        usage_attempts: list[dict[str, Any]] = []
        parsed: dict[str, Any] = {}
        for attempt_index in range(2):
            kwargs = self._kwargs(system_prompt, user_prompt, max_tokens)
            try:
                response, transport_attempt = create_with_retries(
                    lambda: self._reserve_and_create(kwargs), sleep=self.sleep)
            except Exception as exc:  # noqa: BLE001
                if "temperature" in str(exc).lower():
                    self._record_error(messages, prompt_sha, exc, started, kwargs)
                    raise TemperatureRejected(str(exc)) from exc
                self._record_error(messages, prompt_sha, exc, started, kwargs)
                raise
            parsed = self._parse(response)
            finish_reasons.append(parsed["finish_reason"])
            usage_attempts.append(parsed["usage"])
            self._add_tokens(parsed["usage"])
            truncated = self._truncated(parsed["text"], parsed["finish_reason"])
            self._record({"status": "truncated" if truncated else "ok",
                          "model": self.model, "surface": "responses",
                          "session": self.session,
                          "response_model": parsed["response_model"],
                          "request_id": parsed["request_id"], "messages": messages,
                          "prompt_sha256": prompt_sha, "usage": parsed["usage"],
                          "cost": parsed["cost"], "max_output_tokens": max_tokens,
                          "finish_reason": parsed["finish_reason"],
                          "truncation_retry": truncation_retry,
                          "content_sha256": _sha(parsed["text"]),
                          "content": parsed["text"],
                          "wall_ms": int((time.monotonic() - started) * 1000)})
            if not truncated:
                break
            if attempt_index == 0:
                truncation_retry = True
                max_tokens = self._next_cap(max_tokens)
                continue
            raise TransportTruncated(
                truncation_retry=truncation_retry,
                finish_reasons=finish_reasons,
                usage_attempts=usage_attempts)
        wall_ms = int((time.monotonic() - started) * 1000)
        return OpenCodeOutcome(
            text=parsed["text"], messages=messages, requested_model=self.model,
            response_model=parsed["response_model"], request_id=parsed["request_id"],
            finish_reason=parsed["finish_reason"], usage=parsed["usage"] or None,
            wall_ms=wall_ms, transport_attempt=transport_attempt, prompt_sha256=prompt_sha,
            cost=parsed["cost"], session=self.session, truncation_retry=truncation_retry,
            finish_reasons=finish_reasons, usage_attempts=usage_attempts,
            temperature_sent=self._temperature_sent(),
            responses_reasoning_echo=parsed.get("responses_reasoning_echo"),
            responses_reasoning_items=parsed.get("responses_reasoning_items"),
            responses_output_tokens_details=parsed.get("responses_output_tokens_details"),
            responses_reasoning_summary_present=parsed.get(
                "responses_reasoning_summary_present"))

    def _record_error(self, messages, prompt_sha, exc, started, kwargs) -> None:
        self._record({"status": "error", "model": self.model, "surface": "responses",
                      "session": self.session, "messages": messages,
                      "prompt_sha256": prompt_sha,
                      "max_output_tokens": kwargs.get("max_output_tokens"),
                      "finish_reason": None, "error": str(exc),
                      "error_type": type(exc).__name__,
                      "wall_ms": int((time.monotonic() - started) * 1000)})


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return _plain(dumped)
    if hasattr(value, "__dict__"):
        return {key: _plain(item) for key, item in vars(value).items()
                if not str(key).startswith("_")}
    return None


def _reasoning_item_count(response: Any) -> int:
    output = getattr(response, "output", None)
    if output is None and isinstance(response, dict):
        output = response.get("output")
    count = 0
    for item in output or []:
        kind = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        if kind == "reasoning":
            count += 1
    return count


def _output_token_details(response: Any) -> Any:
    usage = getattr(response, "usage", None)
    if isinstance(usage, dict):
        return _plain(usage.get("output_tokens_details"))
    if usage is None:
        return None
    return _plain(getattr(usage, "output_tokens_details", None))


def _summary_present(response: Any, echo: Any) -> bool:
    if isinstance(echo, dict):
        summary = echo.get("summary")
        if isinstance(summary, str) and summary.strip():
            return True
        if isinstance(summary, (list, dict)) and summary:
            return True
    output = getattr(response, "output", None) or []
    for item in output:
        kind = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        summary = item.get("summary") if isinstance(item, dict) else getattr(item, "summary", None)
        if kind == "reasoning" and summary:
            return True
    return False


def _responses_finish_reason(response: Any) -> str | None:
    status = getattr(response, "status", None)
    if status == "completed":
        return "stop"
    if status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None)
        if reason is None and isinstance(details, dict):
            reason = details.get("reason")
        return "length" if reason == "max_output_tokens" else reason
    return status


def list_models(api_key: str, *, base_url: str = OPENCODE_GO_BASE_URL,
                timeout: float = 30.0) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    models = client.models.list()
    return models.model_dump() if hasattr(models, "model_dump") else {"data": []}
