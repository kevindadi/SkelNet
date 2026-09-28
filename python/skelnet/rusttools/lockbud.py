"""Lockbud deadlock feedback for the STATIC baseline.

Lockbud is pinned to commit ``cc78cb7`` and ``nightly-2026-02-07`` (K1).
Findings are classified only by JSON ``bug_kind`` records. A summary line that
merely mentions ``conflictlock`` is not a finding (the summary always prints
that word, often with a zero count).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..oracle import CONCIR_SYNC_CRATE, cargo_toml
from .clippy import relativize
from .runner import ToolRunner, cleanup_target

LOCKBUD_COMMIT = "cc78cb7"
LOCKBUD_TOOLCHAIN = "nightly-2026-02-07"
CRATE_NAME = "lockbud_probe"

_BUG_KIND_RE = re.compile(r'"bug_kind"\s*:\s*"([^"]+)"')


def locate_lockbud(root: Path | None = None) -> Path | None:
    """``LOCKBUD_BIN`` or ``tools/lockbud/target/release/lockbud``."""
    env = os.environ.get("LOCKBUD_BIN")
    if env:
        path = Path(env)
        if path.is_file():
            return path
        return None
    if root is None:
        root = Path(__file__).resolve().parents[3]
    candidate = root / "tools" / "lockbud" / "target" / "release" / "lockbud"
    if candidate.is_file():
        return candidate
    return None


@dataclass
class LockbudHit:
    bug_kind: str
    raw: str

    def to_dict(self) -> dict:
        return {"bug_kind": self.bug_kind, "raw": self.raw}


@dataclass
class LockbudResult:
    unavailable: str | None = None
    timed_out: bool = False
    hits: list[LockbudHit] = field(default_factory=list)
    wall_ms: int = 0

    @property
    def blocking(self) -> bool:
        return bool(self.hits)


def _record_slice(text: str, match: re.Match) -> str:
    """The full JSON object that contains this ``bug_kind`` key.

    ``raw_decode`` keeps nested ``diagnosis`` arrays. A record that is not
    valid JSON falls back to the nearest ``{`` through the next ``}``.
    """
    decoder = json.JSONDecoder()
    cursor = match.start()
    while True:
        start = text.rfind("{", 0, cursor)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            cursor = start
            continue
        if (isinstance(obj, dict) and "bug_kind" in obj
                and start <= match.start() < end):
            return text[start:end]
        cursor = start
    start = text.rfind("{", 0, match.start())
    end = text.find("}", match.end())
    if start >= 0 and end >= 0:
        return text[start:end + 1]
    return match.group(0)


def parse_bug_kinds(text: str, workdir: Path | None = None) -> list[LockbudHit]:
    """Classify lockbud output. Summary lines without ``bug_kind`` are ignored."""
    hits: list[LockbudHit] = []
    for match in _BUG_KIND_RE.finditer(text or ""):
        raw = _record_slice(text or "", match)
        if workdir is not None:
            raw = relativize(raw, workdir)
        hits.append(LockbudHit(bug_kind=match.group(1), raw=raw))
    return hits


def _failure_line(stderr: str) -> str:
    """First stderr line that starts with ``error``, else the last non-empty line."""
    nonempty: list[str] = []
    for line in (stderr or "").splitlines():
        stripped = line.strip()
        if stripped:
            nonempty.append(stripped)
    for line in nonempty:
        if line.startswith("error"):
            return line
    if nonempty:
        return nonempty[-1]
    return "nonzero exit"


def run_lockbud(tools: ToolRunner, workdir: Path | str, source: str, *,
                timeout: float = 300.0, cargo: str = "cargo",
                lockbud_bin: Path | str | None = None) -> LockbudResult:
    """Build ``workdir/lockbud-probe`` with lockbud as ``RUSTC_WRAPPER``.

    ``RUSTUP_TOOLCHAIN`` is passed in ``env_extra``, so it overrides the
    runner's repository toolchain.
    """
    started = time.monotonic()
    binary = Path(lockbud_bin) if lockbud_bin else locate_lockbud()
    if binary is None or not Path(binary).is_file():
        return LockbudResult(unavailable="lockbud_unavailable",
                             wall_ms=int((time.monotonic() - started) * 1000))
    project = Path(workdir) / "lockbud-probe"
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "Cargo.toml").write_text(cargo_toml(CRATE_NAME), encoding="utf-8")
    (project / "src" / "main.rs").write_text(source, encoding="utf-8")
    flags = f"-k deadlock -l {CRATE_NAME}"
    call = tools.run(
        [cargo, "build"], project, timeout=timeout, offline=True,
        env_extra={
            "RUSTUP_TOOLCHAIN": LOCKBUD_TOOLCHAIN,
            "RUSTC_WRAPPER": str(binary),
            "LOCKBUD_FLAGS": flags,
            # JSON reports are log::warn!; they stay silent unless this is set.
            "LOCKBUD_LOG": "warn",
        })
    wall = int((time.monotonic() - started) * 1000)
    combined = (call.stdout or "") + "\n" + (call.stderr or "")
    if call.error is not None:
        cleanup_target(project)
        return LockbudResult(unavailable=call.error, wall_ms=wall)
    if call.timed_out:
        cleanup_target(project)
        return LockbudResult(timed_out=True, wall_ms=wall)
    hits = parse_bug_kinds(combined, project)
    # A build failure or crash with no bug_kind record is not "no findings".
    # Records that did parse still block, even when the exit code is non-zero.
    if call.returncode not in (0, None) and not hits:
        line = relativize(_failure_line(call.stderr or ""), project)
        cleanup_target(project)
        return LockbudResult(unavailable=f"lockbud_failed: {line}", hits=[],
                             wall_ms=wall)
    cleanup_target(project)
    return LockbudResult(hits=hits, wall_ms=wall)


def render_lockbud_section(result: LockbudResult) -> str:
    if result.unavailable:
        if result.unavailable.startswith("lockbud_failed:"):
            reason = result.unavailable.split(":", 1)[1].strip()
            return f"## lockbud\nlockbud could not analyze this program: {reason}"
        return f"## lockbud\n{result.unavailable}"
    if result.timed_out:
        return "## lockbud\nlockbud timed out"
    if not result.hits:
        return "## lockbud\nno bug_kind records"
    body = "\n".join(h.raw for h in result.hits)
    return f"## lockbud\n{body}"


def lockbud_commit(root: Path | None = None) -> str | None:
    """HEAD of the local checkout, when ``tools/lockbud`` is a git repo."""
    if root is None:
        root = Path(__file__).resolve().parents[3]
    git_dir = root / "tools" / "lockbud" / ".git"
    if not git_dir.exists():
        return None
    head = root / "tools" / "lockbud" / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.startswith("ref:"):
        ref = text.split(" ", 1)[1].strip()
        ref_path = root / "tools" / "lockbud" / ".git" / ref
        try:
            return ref_path.read_text(encoding="utf-8").strip()[:12]
        except OSError:
            return None
    return text[:12] if text else None
