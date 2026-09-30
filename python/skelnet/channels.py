"""Client factory and audit wrapper that tie a model to its transport."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .audit import AuditLog
from .transport import CHANNELS, ModelSpec, TransportError, verify_identity

_CHANNEL_TIMEOUT = {"dashscope-direct": 300.0, "deepseek-direct": 180.0,
                    "opencode-go": 180.0}


class ChannelUnavailable(TransportError):
    """The model's channel is blocked or has no key; the caller must skip it."""


def build_client(spec: ModelSpec, params: Any, *, budget: Any,
                 evidence_dir: Path | str, api_key: str, timeout: float = 90.0,
                 sdk_client: Any | None = None,
                 reasoning_log: str = "hash",
                 sleep: Callable[[float], None] = time.sleep):
    """Construct the inner client for a model, or raise ChannelUnavailable.

    `params` is a :class:`~skelnet.params.RunParams`. DeepSeek/DashScope send
    their thinking switch through ``extra_body``; Moonshot (Kimi) cannot disable
    thinking, so it sends ``extra_body={"thinking": {"type": "enabled"}}`` and no
    ``reasoning_effort``. The base URL comes from the channel registry.
    """
    if spec.status != "available" or not spec.model_id:
        raise ChannelUnavailable(
            f"{spec.display_name} is {spec.status}: {spec.blocked_reason}")
    timeout = max(timeout, _CHANNEL_TIMEOUT.get(spec.channel, timeout))
    base_url = CHANNELS[spec.channel].base_url or ""
    if spec.channel == "deepseek-direct":
        from .direct import DirectChatClient
        extra_body = {"thinking": {"type": "enabled" if params.thinking else "disabled"}}
        return DirectChatClient(api_key=api_key, base_url=base_url,
                                model=spec.model_id, budget=budget,
                                evidence_dir=evidence_dir, params=params,
                                timeout=timeout, sdk_client=sdk_client,
                                extra_body=extra_body, reasoning_log=reasoning_log,
                                sleep=sleep)
    if spec.channel == "dashscope-direct":
        from .direct import DirectChatClient
        extra_body = {"enable_thinking": bool(params.thinking)}
        return DirectChatClient(api_key=api_key, base_url=base_url,
                                model=spec.model_id, budget=budget,
                                evidence_dir=evidence_dir, params=params,
                                timeout=timeout, sdk_client=sdk_client,
                                extra_body=extra_body, reasoning_log=reasoning_log,
                                sleep=sleep)
    if spec.channel == "moonshot-direct":
        from .direct import DirectChatClient
        # kimi-k2.7-code cannot disable thinking: always send the switch
        # explicitly. The channel has no ``reasoning_effort`` parameter.
        extra_body = {"thinking": {"type": "enabled"}}
        return DirectChatClient(api_key=api_key, base_url=base_url,
                                model=spec.model_id, budget=budget,
                                evidence_dir=evidence_dir, params=params,
                                timeout=timeout, sdk_client=sdk_client,
                                extra_body=extra_body,
                                reasoning_log=reasoning_log,
                                sleep=sleep)
    if spec.channel == "opencode-go":
        from .opencode_go import OpenCodeGoClient, OpenCodeGoResponsesClient
        cls = OpenCodeGoResponsesClient if spec.surface == "responses" else OpenCodeGoClient
        return cls(api_key=api_key, base_url=base_url, model=spec.model_id,
                   budget=budget, evidence_dir=evidence_dir, params=params,
                   timeout=timeout, sdk_client=sdk_client, sleep=sleep)
    raise ChannelUnavailable(f"no client for channel {spec.channel!r}")


class AuditedClient:
    """Wrap an inner client and emit one audit event per call."""

    def __init__(self, inner: Any, *, audit: AuditLog, run_id: str, cell_id: str,
                 spec: ModelSpec, arm: str, task_id: str, replicate: int,
                 stage: str = "skel") -> None:
        self.inner = inner
        self.audit = audit
        self.run_id = run_id
        self.cell_id = cell_id
        self.spec = spec
        self.arm = arm
        self.task_id = task_id
        self.replicate = replicate
        self.stage = stage
        # Attempt number of the current request (set by the pipeline). Not
        # reset by `set_stage`: the round belongs to the cell, not the stage.
        self.attempt = 0
        self.system_prompt_assets: list[str] = []
        self.system_sha256: str | None = None

    def set_stage(self, stage: str) -> None:
        self.stage = stage

    def set_cell(self, cell_id: str, task_id: str, replicate: int) -> None:
        """Bind subsequent calls to a real cell (task/replicate).

        Each cell gets a fresh OpenCode session and the client learns the task
        and replicate so it can derive a per-cell seed.
        """
        self.cell_id = cell_id
        self.task_id = task_id
        self.replicate = replicate
        self.attempt = 0
        if hasattr(self.inner, "new_session"):
            self.inner.new_session()
        if hasattr(self.inner, "set_cell"):
            self.inner.set_cell(task_id, replicate)

    def set_attempt(self, attempt: int) -> None:
        """Record the pipeline's attempt number for this request."""
        self.attempt = attempt

    def set_prompt_meta(self, assets, system_sha256: str) -> None:
        """Record which system-prompt templates (and their join hash) were used."""
        self.system_prompt_assets = list(assets)
        self.system_sha256 = system_sha256

    def _temperature_policy(self):
        params = getattr(self.inner, "params", None)
        return getattr(params, "temperature_policy", None)

    def complete(self, system: str, user: str):
        prompt = system.strip() + "\n\n" + user.strip()
        started = time.time()
        attempt_id = f"{self.stage}-{self.attempt}"
        meta = {"system_prompt_assets": list(self.system_prompt_assets),
                "system_sha256": self.system_sha256,
                "temperature_policy": self._temperature_policy()}
        try:
            outcome = self.inner.complete(system, user)
        except Exception as exc:  # noqa: BLE001 - recorded then re-raised
            self.audit.model_call(
                run_id=self.run_id, cell_id=self.cell_id, model=self.spec.display_name,
                provider=self.spec.provider, transport=self.spec.channel,
                arm=self.arm, task_id=self.task_id, replicate=self.replicate,
                stage=self.stage, requested_model=self.spec.model_id or "",
                returned_model=None, usage_raw=None, started_at=started,
                ended_at=time.time(), prompt=prompt, response="",
                candidate_round=self.attempt, attempt_id=attempt_id, status="error",
                cache_hit=False,
                temperature_sent=getattr(exc, "temperature_sent", None),
                truncation_retry=bool(getattr(exc, "truncation_retry", False)),
                finish_reasons=list(getattr(exc, "finish_reasons", []) or []),
                error_type=type(exc).__name__, error=str(exc),
                **meta)
            raise
        ended = time.time()
        returned = getattr(outcome, "response_model", None)
        confirmed = verify_identity(self.spec.model_id or "", returned,
                                    aliases=self.spec.confirmed_response_aliases)
        usage = getattr(outcome, "usage", None)
        seed = getattr(outcome, "seed", None)
        self.audit.model_call(
            run_id=self.run_id, cell_id=self.cell_id, model=self.spec.display_name,
            provider=self.spec.provider, transport=self.spec.channel,
            arm=self.arm, task_id=self.task_id, replicate=self.replicate,
            stage=self.stage, requested_model=self.spec.model_id or "",
            returned_model=returned, usage_raw=usage, started_at=started,
            ended_at=ended, prompt=prompt, response=getattr(outcome, "text", ""),
            candidate_round=self.attempt, attempt_id=attempt_id,
            request_id=getattr(outcome, "request_id", None),
            transport_attempt=getattr(outcome, "transport_attempt", 1),
            cost=getattr(outcome, "cost", None),
            finish_reason=getattr(outcome, "finish_reason", None),
            session=getattr(outcome, "session", None),
            seed=seed, seed_sent=seed is not None,
            cache_hit=bool(getattr(outcome, "cache_hit", False)),
            temperature_sent=getattr(outcome, "temperature_sent", None),
            truncation_retry=bool(getattr(outcome, "truncation_retry", False)),
            finish_reasons=list(getattr(outcome, "finish_reasons", []) or []),
            notes=None if confirmed else "identity unconfirmed (model not reported)",
            **meta)
        return outcome


def key_for(spec: ModelSpec, env: dict[str, str], channel_api_key_env: str) -> str:
    api_key = env.get(channel_api_key_env, "")
    if not api_key:
        raise ChannelUnavailable(
            f"missing {channel_api_key_env} for {spec.display_name}")
    return api_key
