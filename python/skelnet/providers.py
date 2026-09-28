"""Candidate providers for the offline workflow.

A provider proposes *CIR candidates* only. It never validates, translates,
verifies, repairs or accepts — those are the Rust backend's job. Real LLM
providers are represented by :class:`LlmCandidateProvider` but are not enabled
for network use in this round; the offline workflow uses :class:`ScriptedProvider`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .llm import LlmClient
from .models import ModelConfig, normalize_token_usage


@dataclass
class CandidateRequest:
    requirements: str
    contract: dict[str, Any]
    feedback: str | None
    attempt: int
    previous_candidate: str | None = None
    current_program: str | None = None
    # "skel" | "cir" | "rust" (SkelNet arms); defaults to the skeleton stage.
    stage: str = "skel"


@dataclass
class CandidateResponse:
    text: str
    source: str
    provider: str
    model_id: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    wall_ms: int = 0

    @classmethod
    def from_usage(cls, text: str, source: str, provider: str, *, model_id: str | None,
                   usage: dict[str, Any] | None) -> "CandidateResponse":
        # Missing usage is recorded as unknown (None), never coerced to zero.
        tokens = normalize_token_usage(usage)
        return cls(text=text, source=source, provider=provider, model_id=model_id,
                   usage=usage, input_tokens=tokens["input"],
                   output_tokens=tokens["output"],
                   reasoning_tokens=tokens["reasoning"],
                   cached_tokens=tokens["cached"])


class CandidateProvider(Protocol):
    name: str

    def propose(self, request: CandidateRequest) -> CandidateResponse: ...


class ScriptedProvider:
    """Deterministic provider replaying a fixed list of responses.

    Each scripted entry is a dict ``{"text": str}`` or ``{"error": str}``. The
    provider records every request it receives so a test can assert that
    feedback retries actually happened.
    """

    name = "scripted"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[CandidateRequest] = []
        self._cursor = 0

    def propose(self, request: CandidateRequest) -> CandidateResponse:
        self.calls.append(request)
        if self._cursor >= len(self._responses):
            return CandidateResponse(
                text="", source="scripted", provider=self.name,
                error="scripted provider exhausted",
            )
        entry = self._responses[self._cursor]
        self._cursor += 1
        if "error" in entry:
            return CandidateResponse(
                text="", source="scripted", provider=self.name, error=str(entry["error"]),
            )
        return CandidateResponse(
            text=str(entry.get("text", "")), source="scripted", provider=self.name,
        )


class LlmCandidateProvider:
    """Real LLM provider adapter (interface only for now; no network in tests)."""

    name = "llm"

    def __init__(self, client: LlmClient, model: ModelConfig, *, system_prompt: str,
                 user_prompt_builder) -> None:
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.user_prompt_builder = user_prompt_builder

    def propose(self, request: CandidateRequest) -> CandidateResponse:
        user_prompt = self.user_prompt_builder(request)
        try:
            text, usage = self.client.chat(self.system_prompt, user_prompt, temperature=0.0)
        except Exception as exc:  # provider errors are candidate errors, not workflow crashes
            return CandidateResponse(text="", source="llm", provider=self.model.provider,
                                     error=str(exc))
        return CandidateResponse.from_usage(
            text, "llm", self.model.provider, model_id=self.model.model_id, usage=usage,
        )


@dataclass
class PatchRequest:
    context: dict[str, Any]
    attempt: int
    feedback: str | None = None
    previous_candidate: str | None = None


@dataclass
class PatchResponse:
    text: str
    source: str
    provider: str
    model_id: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    wall_ms: int = 0


class PatchCandidateProvider(Protocol):
    name: str

    def propose_patch(self, request: PatchRequest) -> PatchResponse: ...


class ScriptedPatchProvider:
    """Deterministic patch provider replaying a fixed list of responses.

    Each entry is ``{"text": str}`` or ``{"error": str}``. Requests are recorded
    so tests can assert the rejection feedback was actually passed back.
    """

    name = "scripted"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[PatchRequest] = []
        self._cursor = 0

    def propose_patch(self, request: PatchRequest) -> PatchResponse:
        self.calls.append(request)
        if self._cursor >= len(self._responses):
            return PatchResponse(text="", source="scripted", provider=self.name,
                                 error="scripted patch provider exhausted")
        entry = self._responses[self._cursor]
        self._cursor += 1
        if "error" in entry:
            return PatchResponse(text="", source="scripted", provider=self.name,
                                 error=str(entry["error"]))
        return PatchResponse(text=str(entry.get("text", "")), source="scripted",
                             provider=self.name)
