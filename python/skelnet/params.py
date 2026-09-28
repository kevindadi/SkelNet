"""Per-run model parameters (frozen for a run and recorded in the MANIFEST).

The four experimental models all run with thinking enabled; GPT and Kimi use
``reasoning_effort="medium"``; no temperature is sent (``provider_default``);
each cell is capped at 5 calls / 200k tokens; a single output is capped at
32768 tokens.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

TEMPERATURE_PROVIDER_DEFAULT = "provider_default"
TEMPERATURE_FIXED = "fixed"
SEED_PER_CELL = "per_cell"
SEED_NONE = "none"

DEFAULT_MAX_OUTPUT_TOKENS = 32768
DEFAULT_MAX_OUTPUT_TOKENS_CAP = 65536
DEFAULT_CALL_BUDGET = 5
DEFAULT_TOKEN_BUDGET = 200_000


def seed_for(task: str, rep: int) -> int:
    """Deterministic per-cell seed."""
    digest = hashlib.sha256(f"{task}|{rep}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


@dataclass
class RunParams:
    temperature_policy: str = TEMPERATURE_PROVIDER_DEFAULT
    temperature: float | None = None
    seed_policy: str = SEED_PER_CELL
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    call_budget: int = DEFAULT_CALL_BUDGET
    token_budget: int = DEFAULT_TOKEN_BUDGET
    hint: str = "h0"
    # SKEL/CIR method knobs (round 5). Other arms reject non-default values.
    feedback_mode: str = "full"
    rust_when_unverified: str = "last"
    property_ids: str = "keep"
    # Resolved from the model registry.
    thinking: bool = True
    reasoning_effort: str | None = None
    stream: bool = False
    max_output_tokens_cap: int = DEFAULT_MAX_OUTPUT_TOKENS_CAP
    supports_seed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def params_for_model(spec, **overrides: Any) -> RunParams:
    """Build the run parameters, taking model-specific policy from `spec`."""
    values: dict[str, Any] = {
        "thinking": getattr(spec, "thinking", True),
        "reasoning_effort": getattr(spec, "reasoning_effort", None),
        "stream": getattr(spec, "stream", False),
        "max_output_tokens": getattr(spec, "max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS),
        "max_output_tokens_cap": getattr(spec, "max_output_tokens_cap",
                                         DEFAULT_MAX_OUTPUT_TOKENS_CAP),
        "supports_seed": getattr(spec, "supports_seed", False),
    }
    values.update(overrides)
    return RunParams(**values)
