"""O3 (miri half): run the program under miri with a fixed multi-seed range."""

from __future__ import annotations

import time
from pathlib import Path

from .base import FAIL, PASS, UNAVAILABLE, LayerResult
from .runner import ToolRunner
from .seeds import miri_many_seeds_flag


def _classify(text: str) -> str | None:
    low = text.lower()
    if "undefined behavior" in low or "unsupported operation: " in low:
        return "ub"
    if "deadlock" in low:
        return "deadlock"
    if "main thread terminated without waiting for all remaining threads" in low:
        return "thread_leak"
    if "panicked at" in low or "panic" in low:
        return "panic"
    return None


def evaluate_miri(tools: ToolRunner, project_dir: Path | str, *,
                  seed_start: int, seed_count: int, timeout: float = 600.0,
                  cargo: str = "cargo") -> LayerResult:
    started = time.monotonic()
    flags = miri_many_seeds_flag(seed_start, seed_count)
    call = tools.run([cargo, "miri", "run"], project_dir, timeout=timeout,
                     env_extra={"MIRIFLAGS": flags, "MIRI_FORCE_ALL_SYSROOTS": "1"})
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
    category = _classify(combined)
    if category is not None:
        return LayerResult("O3", FAIL, category, _first_line(combined), wall)
    if call.returncode != 0:
        return LayerResult("O3", FAIL, "panic", _first_line(combined), wall)
    return LayerResult("O3", PASS, None, None, wall)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""
