"""Cursor agent client (Composer 2.5).

Composer runs through the Cursor agent SDK (``cursor_sdk``), not an
OpenAI-compatible chat endpoint: one ``complete`` is one agent turn. A fresh
agent is created per cell (``new_session``) so context does not accumulate
across cells. The SDK is agent/sandbox-based, so token usage is reported by the
server and is *not* directly comparable to a stateless chat call; this is
recorded as a protocol deviation.

The client mirrors the ``complete(system, user)`` surface of
:class:`~skelnet.direct.DirectChatClient`. ``sdk_client`` is injectable so tests
never touch the network.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import normalize_token_usage


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class CursorOutcome:
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
    session: str | None = None
    seed: int | None = None
    truncation_retry: bool = False
    finish_reasons: list[str | None] = field(default_factory=list)
    usage_attempts: list[dict[str, Any]] = field(default_factory=list)
    temperature_sent: float | None = None


def _usage_from_agent(usage: Any) -> dict[str, Any]:
    """Map a ``cursor_sdk`` ``TokenUsage`` (or dict) onto a normalized payload."""
    if usage is None:
        return {}
    if isinstance(usage, dict):
        get = usage.get
    else:
        def get(key: str, default: Any = None) -> Any:
            return getattr(usage, key, default)
    input_tokens = get("input_tokens")
    output_tokens = get("output_tokens")
    reasoning = get("reasoning_tokens")
    cached = get("cache_read_tokens")
    payload: dict[str, Any] = {}
    if input_tokens is not None:
        payload["input_tokens"] = input_tokens
    if output_tokens is not None:
        payload["output_tokens"] = output_tokens
    if reasoning is not None:
        payload["reasoning_tokens"] = reasoning
    if cached is not None:
        payload["cached_tokens"] = cached
    return payload


class CursorAgentClient:
    def __init__(self, *, api_key: str, base_url: str = "", model: str,
                 budget: Any, evidence_dir: Path | str, params: Any,
                 timeout: float = 900.0, sdk_client: Any | None = None,
                 mode: str = "plan", cwd: Path | str | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.budget = budget
        self.params = params
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.evidence_dir / "requests.jsonl"
        self.timeout = float(timeout)
        self.mode = mode
        self.cwd = Path(cwd) if cwd is not None else None
        self.sleep = sleep
        self.task_id: str | None = None
        self.replicate = 0
        self._session_id: str | None = None
        self._agent: Any | None = None
        if sdk_client is not None:
            self._client = sdk_client
        else:
            from cursor_sdk import Client
            self._client = Client(api_key=api_key)

    # ── lifecycle ────────────────────────────────────────────────────
    def set_cell(self, task_id: str, replicate: int) -> None:
        self.task_id = task_id
        self.replicate = replicate

    def new_session(self) -> None:
        """Drop the current agent so the next call starts a fresh context."""
        if self._agent is not None:
            close = getattr(self._agent, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:  # noqa: BLE001 - best effort
                    pass
        self._agent = None
        self._session_id = hashlib.sha256(
            f"{self.task_id}|{self.replicate}|{time.time()}".encode("utf-8")
        ).hexdigest()[:16]

    def _ensure_agent(self) -> Any:
        if self._agent is None:
            options: dict[str, Any] = {}
            if self.mode:
                options["mode"] = self.mode
            kwargs: dict[str, Any] = {"model": self.model, "api_key": self.api_key}
            if self.cwd is not None:
                kwargs["local"] = {"cwd": str(self.cwd)}
            self._agent = self._client.create_agent(options, **kwargs)
        return self._agent

    # ── accounting ───────────────────────────────────────────────────
    def _temperature_sent(self) -> float | None:
        if self.params.temperature_policy == "fixed":
            return self.params.temperature
        return None

    def _add_tokens(self, usage: Any) -> None:
        add = getattr(self.budget, "add_tokens", None)
        if add is not None:
            add(normalize_token_usage(usage))

    def _record(self, record: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def complete(self, system_prompt: str, user_prompt: str) -> CursorOutcome:
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}]
        prompt = system_prompt + "\n\n" + user_prompt
        prompt_sha = _sha(json.dumps(messages, ensure_ascii=False, sort_keys=True))
        started = time.monotonic()
        self.budget.reserve()
        try:
            agent = self._ensure_agent()
            run = agent.send(prompt)
            result = run.wait()
        except Exception as exc:  # noqa: BLE001 - recorded then re-raised
            self._record({"status": "error", "model": self.model,
                          "messages": messages, "prompt_sha256": prompt_sha,
                          "error": str(exc), "error_type": type(exc).__name__,
                          "wall_ms": int((time.monotonic() - started) * 1000)})
            raise
        wall_ms = int((time.monotonic() - started) * 1000)
        status = getattr(result, "status", "finished")
        text = getattr(result, "result", "") or ""
        if status not in ("finished", None):
            self._record({"status": "error", "model": self.model,
                          "messages": messages, "prompt_sha256": prompt_sha,
                          "error": f"agent run status {status}",
                          "error_type": "CursorAgentError", "wall_ms": wall_ms})
            raise RuntimeError(f"cursor agent run ended with status {status!r}")
        usage = _usage_from_agent(getattr(result, "usage", None))
        self._add_tokens(usage)
        finish_reason = "stop"
        self._record({
            "status": "ok", "model": self.model, "session": self._session_id,
            "response_model": None, "request_id": getattr(result, "id", None),
            "messages": messages, "prompt_sha256": prompt_sha, "usage": usage,
            "finish_reason": finish_reason, "content_sha256": _sha(text),
            "content": text, "wall_ms": wall_ms,
        })
        return CursorOutcome(
            text=text, messages=messages, requested_model=self.model,
            response_model=None, request_id=getattr(result, "id", None),
            finish_reason=finish_reason, usage=usage or None, wall_ms=wall_ms,
            transport_attempt=1, prompt_sha256=prompt_sha,
            cost=None, reasoning_content=None, session=self._session_id,
            seed=None, truncation_retry=False, finish_reasons=[finish_reason],
            usage_attempts=[usage], temperature_sent=self._temperature_sent())
