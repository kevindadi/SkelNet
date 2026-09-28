"""O3 (miri half): run the program under miri with a fixed multi-seed range.

Only the tool's own diagnostics decide the category, and only when the exit
code is non-zero: a program that merely prints ``panic``/``deadlock`` passes.
"""

from __future__ import annotations

import time
from pathlib import Path

from .base import FAIL, PASS, UNAVAILABLE, UNSUPPORTED, LayerResult
from .runner import ToolRunner
from .seeds import miri_many_seeds_flag


def classify_miri(text: str) -> str | None:
    """Map miri's diagnostic to a category (non-zero exit only)."""
    low = text.lower()
    if "unsupported operation" in low:
        return "unsupported"
    if "error: undefined behavior" in low:
        return "ub"
    if "error: deadlock" in low:
        return "deadlock"
    if "main thread terminated without waiting for all remaining threads" in low:
        return "thread_leak"
    if "panicked at" in low:
        return "panic"
    return None


def evaluate_miri(tools: ToolRunner, project_dir: Path | str, *,
                  seed_start: int, seed_count: int, timeout: float = 600.0,
                  cargo: str = "cargo") -> LayerResult:
    started = time.monotonic()
    flags = miri_many_seeds_flag(seed_start, seed_count)
    call = tools.run([cargo, "miri", "run"], project_dir, timeout=timeout,
                     env_extra={"MIRIFLAGS": flags})
    wall = int((time.monotonic() - started) * 1000)
    if call.error is not None:
        return LayerResult("O3", UNAVAILABLE, "miri_unavailable",
                           f"cargo miri unavailable: {call.error}", wall)
    combined = (call.stderr or "") + (call.stdout or "")
    if "no such command" in combined or "component 'miri'" in combined:
        return LayerResult("O3", UNAVAILABLE, "miri_unavailable",
                           "miri is not installed", wall)
    if call.timed_out:
        return LayerResult("O3", FAIL, "deadlock", "miri timed out", wall)
    if call.returncode == 0:
        return LayerResult("O3", PASS, None, None, wall)
    category = classify_miri(combined)
    if category == "unsupported":
        return LayerResult("O3", UNSUPPORTED, "miri_unsupported",
                           _first_line(combined), wall)
    if category is not None:
        return LayerResult("O3", FAIL, category, _first_line(combined), wall)
    return LayerResult("O3", FAIL, "panic", _first_line(combined), wall)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""
