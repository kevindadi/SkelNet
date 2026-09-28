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


def cache_key(*, model_id: str, system: str, user: str, seed: int | None,
              temperature_policy: str, temperature: float | None,
              max_output_tokens: int, thinking: bool,
              reasoning_effort: str | None) -> str:
    payload = {
        "model_id": model_id,
        "system": system,
        "user": user,
        "seed": seed,
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

    def __getattr__(self, name: str) -> Any:  # forward set_cell/new_session/...
        return getattr(self.inner, name)

    def _key(self, system: str, user: str) -> str:
        seed = None
        if (self.params.seed_policy == "per_cell" and self.params.supports_seed
                and getattr(self.inner, "task_id", None) is not None):
            from .params import seed_for
            seed = seed_for(self.inner.task_id, self.inner.replicate)
        return cache_key(model_id=self.model_id, system=system, user=user, seed=seed,
                         temperature_policy=self.params.temperature_policy,
                         temperature=self.params.temperature,
                         max_output_tokens=self.params.max_output_tokens,
                         thinking=self.params.thinking,
                         reasoning_effort=self.params.reasoning_effort)

    def complete(self, system: str, user: str):
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
        }
        self.cache.put(key, payload)
        return outcome
