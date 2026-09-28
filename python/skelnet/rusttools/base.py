"""Shared types for the independent oracle tool layers (round 3).

Every layer returns a :class:`LayerResult`; the oracle composes them into the
frozen ``oracle`` result dict. No layer knows about the experimental arms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Layer status vocabulary (kept identical to the cell schema).
PASS = "pass"
FAIL = "fail"
UNSUPPORTED = "unsupported"
UNAVAILABLE = "unavailable"
NOT_RUN = "not_run"

_LAYER_NAMES = ("O1", "O2", "O3", "O4")


@dataclass
class LayerResult:
    """One oracle layer's outcome."""

    name: str
    status: str = NOT_RUN
    category: str | None = None
    detail: str | None = None
    wall_ms: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "category": self.category,
                "detail": self.detail, "wall_ms": self.wall_ms}


@dataclass
class ToolCall:
    """Archived result of one subprocess invocation."""

    cmd: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    wall_ms: int = 0
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None


class ToolUnavailable(RuntimeError):
    """A required external tool could not be located (environment problem)."""
