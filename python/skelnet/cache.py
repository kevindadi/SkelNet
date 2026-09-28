"""Response cache and offline replay.

The cache key is the sha256 of a canonical JSON of everything that can change
a reply. ``CachedClient`` wraps any inner ``complete(system, user)`` client;
under replay it never calls the inner client and raises ``ReplayMiss`` on a
miss.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .transport import ReplayMiss


def cache_key(*, model_id: str, system: str, user: str, task: str | None,
              rep: int, seed: int | None, call_index: int,
              temperature_policy: str, temperature: float | None,
              max_output_tokens: int, thinking: bool,
              reasoning_effort: str | None) -> str:
    """Cache key = sha256 of the canonical request identity.

    Includes the cell identity (`task`, `rep`, the always-computed
    `seed_for(task, rep)`) and the per-cell logical `call_index`, so distinct
    reps and repeated identical requests within a cell never share a reply.
    Deliberately **excludes** arm and stage: a byte-identical first-round
    request (call_index 1) still hits across arms when a shared ``--cache-dir``
    is used.
    """
    payload = {
        "model_id": model_id,
        "system": system,
        "user": user,
        "task": task,
        "rep": rep,
        "seed": seed,
        "call_index": call_index,
        "temperature_policy": temperature_policy,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "thinking": thinking,
        "reasoning_effort": reasoning_effort,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class CachedOutcome:
    text: str
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    response_model: str | None = None
    request_id: str | None = None
    cost: float | None = None
    reasoning_content: str | None = None
    session: str | None = None
    seed: int | None = None
    wall_ms: int = 0
    transport_attempt: int = 1
    prompt_sha256: str = ""
    messages: list = field(default_factory=list)
    requested_model: str = ""
    cache_hit: bool = True
    truncation_retry: bool = False
    finish_reasons: list = field(default_factory=list)
    usage_attempts: list = field(default_factory=list)
    temperature_sent: float | None = None


class ResponseCache:
    def __init__(self, directory: Path | str | None) -> None:
        self.directory = Path(directory) if directory else None
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path | None:
        return self.directory / f"{key}.json" if self.directory else None

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.path_for(key)
        if path is None or not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def put(self, key: str, payload: dict[str, Any]) -> None:
        path = self.path_for(key)
        if path is None:
            return
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")


class CachedClient:
    """Wrap a client; store responses and replay them offline."""

    def __init__(self, inner: Any, *, cache: ResponseCache, replay: ResponseCache | None,
                 model_id: str, params: Any) -> None:
        self.inner = inner
        self.cache = cache
        self.replay = replay
        self.model_id = model_id
        self.params = params
        self.cache_hit = False
        self.task_id: str | None = None
        self.replicate = 0
        self.call_index = 0

    def __getattr__(self, name: str) -> Any:  # forward new_session/set_stage/...
        return getattr(self.inner, name)

    def set_cell(self, task_id: str, replicate: int) -> None:
        """Bind the cache to a cell: reset the call counter, forward to inner."""
        self.task_id = task_id
        self.replicate = replicate
        self.call_index = 0
        if hasattr(self.inner, "set_cell"):
            self.inner.set_cell(task_id, replicate)

    def _key(self, system: str, user: str) -> str:
        from .params import seed_for
        seed = seed_for(self.task_id, self.replicate) if self.task_id is not None else None
        return cache_key(model_id=self.model_id, system=system, user=user,
                         task=self.task_id, rep=self.replicate, seed=seed,
                         call_index=self.call_index,
                         temperature_policy=self.params.temperature_policy,
                         temperature=self.params.temperature,
                         max_output_tokens=self.params.max_output_tokens,
                         thinking=self.params.thinking,
                         reasoning_effort=self.params.reasoning_effort)

    def complete(self, system: str, user: str):
        self.call_index += 1
        key = self._key(system, user)
        if self.replay is not None:
            cached = self.replay.get(key)
            if cached is None:
                raise ReplayMiss("replay_miss")
            self.cache_hit = True
            return CachedOutcome(**cached)
        cached = self.cache.get(key)
        if cached is not None:
            self.cache_hit = True
            return CachedOutcome(**cached)
        self.cache_hit = False
        outcome = self.inner.complete(system, user)
        payload = {
            "text": getattr(outcome, "text", ""),
            "usage": getattr(outcome, "usage", None),
            "finish_reason": getattr(outcome, "finish_reason", None),
            "response_model": getattr(outcome, "response_model", None),
            "request_id": getattr(outcome, "request_id", None),
            "cost": getattr(outcome, "cost", None),
            "reasoning_content": getattr(outcome, "reasoning_content", None),
            "session": getattr(outcome, "session", None),
            "seed": getattr(outcome, "seed", None),
            "wall_ms": getattr(outcome, "wall_ms", 0),
            "transport_attempt": getattr(outcome, "transport_attempt", 1),
            "prompt_sha256": getattr(outcome, "prompt_sha256", ""),
            "messages": getattr(outcome, "messages", []),
            "requested_model": getattr(outcome, "requested_model", ""),
            "truncation_retry": bool(getattr(outcome, "truncation_retry", False)),
            "finish_reasons": list(getattr(outcome, "finish_reasons", []) or []),
            "usage_attempts": list(getattr(outcome, "usage_attempts", []) or []),
            "temperature_sent": getattr(outcome, "temperature_sent", None),
        }
        self.cache.put(key, payload)
        return outcome
