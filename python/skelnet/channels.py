"""Client factory and audit wrapper that tie a model to its transport."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .transport import CHANNELS, ModelSpec, TransportError, verify_identity

_CHANNEL_TIMEOUT = {"dashscope-direct": 300.0, "deepseek-direct": 180.0,
                    "opencode-go": 180.0}


class ChannelUnavailable(TransportError):
    """The model's channel is blocked or has no key; the caller must skip it."""


def build_client(spec: ModelSpec, *, budget: Any, evidence_dir: Path | str,
                 api_key: str, timeout: float = 90.0, max_tokens: int = 4096,
                 temperature: float = 0.0):
    """Construct the inner client for a model, or raise ChannelUnavailable."""

    if spec.status != "available" or not spec.model_id:
        raise ChannelUnavailable(
            f"{spec.display_name} is {spec.status}: {spec.blocked_reason}")
    timeout = max(timeout, _CHANNEL_TIMEOUT.get(spec.channel, timeout))
    if spec.channel == "deepseek-direct":
        from .direct import DirectChatClient
        return DirectChatClient(api_key=api_key,
                                base_url=CHANNELS[spec.channel].base_url or "",
                                model=spec.model_id, budget=budget,
                                evidence_dir=evidence_dir, timeout=timeout,
                                max_tokens=max_tokens, temperature=temperature,
                                extra_body={"thinking": {"type": "disabled"}})
    if spec.channel == "dashscope-direct":
        from .direct import DirectChatClient
        return DirectChatClient(api_key=api_key,
                                base_url=CHANNELS[spec.channel].base_url or "",
                                model=spec.model_id, budget=budget,
                                evidence_dir=evidence_dir, timeout=timeout,
                                max_tokens=max_tokens, temperature=temperature,
                                extra_body={"enable_thinking": False})
    if spec.channel == "opencode-go":
        from .opencode_go import OpenCodeGoClient, OpenCodeGoResponsesClient
        cls = OpenCodeGoResponsesClient if spec.surface == "responses" else OpenCodeGoClient
        return cls(api_key=api_key, budget=budget,
                   evidence_dir=evidence_dir, model=spec.model_id,
                   timeout=timeout, max_tokens=max_tokens,
                   temperature=temperature)
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
        """Bind subsequent calls to a real cell (task/replicate)."""
        self.cell_id = cell_id
        self.task_id = task_id
        self.replicate = replicate
        self.attempt = 0

    def set_attempt(self, attempt: int) -> None:
        """Record the pipeline's attempt number for this request."""
        self.attempt = attempt

    def set_prompt_meta(self, assets, system_sha256: str) -> None:
        """Record which system-prompt templates (and their join hash) were used."""
        self.system_prompt_assets = list(assets)
        self.system_sha256 = system_sha256

    def complete(self, system: str, user: str):
        prompt = system.strip() + "\n\n" + user.strip()
        started = time.time()
        attempt_id = f"{self.stage}-{self.attempt}"
        meta = {"system_prompt_assets": list(self.system_prompt_assets),
                "system_sha256": self.system_sha256}
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
                error_type=type(exc).__name__, error=str(exc), **meta)
            raise
        ended = time.time()
        returned = getattr(outcome, "response_model", None)
        confirmed = verify_identity(self.spec.model_id or "", returned)
        usage = getattr(outcome, "usage", None)
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
            notes=None if confirmed else "identity unconfirmed (model not reported)",
            **meta)
        return outcome


def key_for(spec: ModelSpec, env: dict[str, str], channel_api_key_env: str) -> str:
    api_key = env.get(channel_api_key_env, "")
    if not api_key:
        raise ChannelUnavailable(
            f"missing {channel_api_key_env} for {spec.display_name}")
    return api_key
