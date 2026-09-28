"""Dynamic-analysis feedback for DYNAMIC and DYNAMIC_M (D4-4, D4-8, D4-9).

Reuses the oracle's stress, Shuttle and miri runners, but with the feedback
seed window. Acceptance is separate from the oracle: ``shuttle_unsupported``
and ``miri_unsupported`` do not block, and a Shuttle ``no_concurrency`` result
counts as a pass.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..oracle import SHUTTLE_SHIM_CRATE, cargo_toml
from .base import PASS
from .clippy import relativize
from .miri import evaluate_miri
from .runner import ToolRunner, cleanup_target
from .seeds import feedback_miri_window, feedback_shuttle_seed
from .shuttle import evaluate_shuttle
from .stress import evaluate_o2

FEEDBACK_LIMIT_BYTES = 8192
_TRUNC = "\n[truncated]"


def pack_sections(sections: list[str], *, limit_bytes: int = FEEDBACK_LIMIT_BYTES
                  ) -> tuple[str, bool]:
    """Join sections in order under a UTF-8 budget.

    Each section gets an equal share of the bytes that remain. A section that
    does not use its share hands the leftover to the sections after it. An
    overflowing section keeps its prefix and ends with ``[truncated]``.
    """
    parts = [s for s in sections if s]
    if not parts:
        return "", False
    sep = b"\n"
    sep_cost = len(sep) * (len(parts) - 1)
    remaining = max(0, limit_bytes - sep_cost)
    encoded = [p.encode("utf-8") for p in parts]
    truncated = False
    chunks: list[bytes] = []
    n = len(encoded)
    for index, blob in enumerate(encoded):
        left = n - index
        share = remaining // left if left else 0
        if len(blob) <= share:
            chunks.append(blob)
            remaining -= len(blob)
            continue
        truncated = True
        marker = _TRUNC.encode("utf-8")
        room = share - len(marker)
        if room < 0:
            piece = marker[:share]
        else:
            prefix = blob[:room].decode("utf-8", errors="ignore").encode("utf-8")
            piece = prefix + marker
            if len(piece) > share:
                piece = piece[: max(0, share)]
        chunks.append(piece)
        remaining -= len(piece)
    text = b"\n".join(chunks).decode("utf-8", errors="ignore")
    raw = text.encode("utf-8")
    if len(raw) > limit_bytes:
        trimmed = raw[:limit_bytes].decode("utf-8", errors="ignore")
        if not trimmed.endswith("[truncated]"):
            # Keep the marker inside the budget when possible.
            marker = _TRUNC.encode("utf-8")
            room = max(0, limit_bytes - len(marker))
            trimmed = raw[:room].decode("utf-8", errors="ignore") + _TRUNC
        text = trimmed
        truncated = True
    return text, truncated


@dataclass
class ToolSlice:
    name: str
    status: str
    category: str | None = None
    blocking: bool = False
    text: str = ""
    wall_ms: int = 0
    seeds: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status,
                "category": self.category, "blocking": self.blocking,
                "wall_ms": self.wall_ms, "seeds": self.seeds}


@dataclass
class DynamicResult:
    slices: list[ToolSlice] = field(default_factory=list)
    passed: bool = False
    feedback: str = ""
    truncated: bool = False
    wall_ms: int = 0
    seeds: dict = field(default_factory=dict)

    @property
    def feedback_sha256(self) -> str:
        return hashlib.sha256(self.feedback.encode("utf-8")).hexdigest()

    @property
    def feedback_bytes(self) -> int:
        return len(self.feedback.encode("utf-8"))


def _nonblocking(category: str | None) -> bool:
    return category in ("shuttle_unsupported", "miri_unsupported", "no_concurrency")


def _stress_text(layer, terminal: str | None) -> str:
    failures = (layer.data or {}).get("failures") or []
    if layer.status == PASS:
        return "## stress\nall runs passed"
    if not failures:
        return f"## stress\n{layer.category}: {layer.detail}"
    first = failures[0]
    category = first.get("category")
    detail = first.get("detail")
    lines = [f"## stress", f"category: {category}", f"detail: {detail}"]
    if category == "wrong_output":
        lines.append(f"expected last line: {terminal!r}")
        lines.append(f"actual last line: {detail!r}")
    return "\n".join(lines)


def _shuttle_text(layer, failure_file: Path) -> str:
    raw = ""
    if failure_file.is_file():
        raw = failure_file.read_text(encoding="utf-8", errors="replace")
    schedule = (layer.data or {}).get("schedule")
    if layer.status == PASS and (layer.data or {}).get("no_concurrency"):
        return "## shuttle\nno concurrency to explore (treated as pass)"
    if layer.category == "shuttle_unsupported":
        return f"## shuttle\nshuttle could not run: {layer.detail}"
    if layer.status == PASS:
        return "## shuttle\npassed"
    parts = ["## shuttle", f"category: {layer.category}"]
    if layer.detail:
        parts.append(layer.detail)
    if raw:
        parts.append(raw)
    elif schedule:
        parts.append(f"schedule: {schedule}")
    return "\n".join(parts)


def _miri_text(layer) -> str:
    if layer.category == "miri_unsupported":
        return f"## miri\nmiri could not run this program: {layer.detail}"
    if layer.category == "miri_unavailable":
        return f"## miri\nmiri unavailable: {layer.detail}"
    if layer.status == PASS:
        return "## miri\npassed"
    return f"## miri\ncategory: {layer.category}\n{layer.detail or ''}"


def run_dynamic(tools: ToolRunner, workdir: Path | str, source: str, *,
                terminal: str | None, stress_runs: int = 20,
                stress_timeout: float = 10.0, shuttle_iterations: int = 2000,
                shuttle_depth: int = 3, miri_seed_count: int = 16,
                timeout: float = 300.0, cargo: str = "cargo") -> DynamicResult:
    """Build ``source`` and run stress, Shuttle and miri under feedback seeds."""
    started = time.monotonic()
    workdir = Path(workdir)
    (workdir / "src").mkdir(parents=True, exist_ok=True)
    (workdir / "Cargo.toml").write_text(cargo_toml("dyn_probe"), encoding="utf-8")
    (workdir / "src" / "main.rs").write_text(source, encoding="utf-8")
    miri_start, miri_count = feedback_miri_window(miri_seed_count)
    shuttle_seed = feedback_shuttle_seed()
    seeds = {"shuttle": shuttle_seed, "miri_start": miri_start,
             "miri_count": miri_count}
    build = tools.run([cargo, "build"], workdir, timeout=timeout, offline=True)
    slices: list[ToolSlice] = []
    if build.error is not None or build.timed_out or build.returncode != 0:
        detail = build.error or ("timed out" if build.timed_out else (build.stderr or "")[-400:])
        text = f"## build\n{relativize(detail or 'build failed', workdir)}"
        slices.append(ToolSlice("build", "fail", "build_failed", True, text,
                                build.wall_ms))
        feedback, truncated = pack_sections([text])
        return DynamicResult(slices=slices, passed=False, feedback=feedback,
                             truncated=truncated,
                             wall_ms=int((time.monotonic() - started) * 1000),
                             seeds=seeds)

    binary = workdir / "target" / "debug" / "dyn_probe"
    stress = evaluate_o2(tools, binary, terminal=terminal, runs=stress_runs,
                         run_timeout=stress_timeout, check_terminal=True)
    stress_block = stress.status != PASS
    slices.append(ToolSlice(
        "stress", stress.status, stress.category, stress_block,
        relativize(_stress_text(stress, terminal), workdir),
        stress.wall_ms or 0))

    shuttle = evaluate_shuttle(
        tools, workdir, source, shim_path=SHUTTLE_SHIM_CRATE,
        iterations=shuttle_iterations, depth=shuttle_depth,
        seed=shuttle_seed, timeout=timeout, cargo=cargo)
    shuttle_block = shuttle.status != PASS and not _nonblocking(shuttle.category)
    # no_concurrency is PASS already; unsupported is non-blocking.
    if shuttle.category == "shuttle_unsupported":
        shuttle_block = False
    failure_file = workdir / "shuttle" / "failure.txt"
    shuttle_body = relativize(_shuttle_text(shuttle, failure_file), workdir)
    slices.append(ToolSlice(
        "shuttle", shuttle.status, shuttle.category, shuttle_block, shuttle_body,
        shuttle.wall_ms or 0, seeds={"shuttle": shuttle_seed}))

    miri = evaluate_miri(tools, workdir, seed_start=miri_start,
                         seed_count=miri_count, timeout=timeout, cargo=cargo)
    miri_block = miri.status != PASS and miri.category != "miri_unsupported"
    slices.append(ToolSlice(
        "miri", miri.status, miri.category, miri_block,
        relativize(_miri_text(miri), workdir), miri.wall_ms or 0,
        seeds={"miri_start": miri_start, "miri_count": miri_count}))

    cleanup_target(workdir)
    feedback, truncated = pack_sections([s.text for s in slices])
    passed = not any(s.blocking for s in slices)
    return DynamicResult(slices=slices, passed=passed, feedback=feedback,
                         truncated=truncated,
                         wall_ms=int((time.monotonic() - started) * 1000),
                         seeds=seeds)
