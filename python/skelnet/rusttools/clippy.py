"""Clippy concurrency-lint feedback for the STATIC baseline.

Runs ``cargo clippy`` with ``-A clippy::all`` and an explicit ``-W`` set, then
splits ``compiler-message`` records into clippy findings and rustc diagnostics.
Paths in rendered text are made relative to the probe project.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..oracle import cargo_toml
from .runner import ToolRunner, cleanup_target

# D4-3. Lints that do not exist on the repository toolchain are dropped after
# ``probe_lints`` and recorded in the round report; the list below is what the
# pinned nightly accepts (see docs/baselines.md).
CONCURRENCY_LINTS: tuple[str, ...] = (
    "clippy::mutex_atomic",
    "clippy::mutex_integer",
    "clippy::significant_drop_in_scrutinee",
    "clippy::significant_drop_tightening",
    "clippy::arc_with_non_send_sync",
    "clippy::readonly_write_lock",
)

# rustc lints that block STATIC acceptance (D4-2). Other rustc warnings are
# reported but do not block.
RUSTC_BLOCKING_LINTS = ("let_underscore_lock", "unused_must_use")


def relativize(text: str, workdir: Path) -> str:
    if not text:
        return text
    for base in {str(workdir), str(workdir.resolve())}:
        text = text.replace(base + "/", "").replace(base, ".")
    return text


@dataclass
class Diagnostic:
    level: str
    code: str | None
    message: str
    rendered: str

    def to_dict(self) -> dict:
        return {"level": self.level, "code": self.code,
                "message": self.message, "rendered": self.rendered}


@dataclass
class ClippyResult:
    unavailable: str | None = None
    timed_out: bool = False
    clippy: list[Diagnostic] = field(default_factory=list)
    rustc_errors: list[Diagnostic] = field(default_factory=list)
    rustc_warnings: list[Diagnostic] = field(default_factory=list)
    wall_ms: int = 0

    @property
    def blocking(self) -> bool:
        """True when STATIC must keep iterating (D4-2)."""
        if self.rustc_errors:
            return True
        if any(d.code in RUSTC_BLOCKING_LINTS for d in self.rustc_warnings):
            return True
        if self.clippy:
            return True
        return False


def _parse(stdout: str, workdir: Path) -> tuple[list[Diagnostic], list[Diagnostic], list[Diagnostic]]:
    clippy: list[Diagnostic] = []
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("reason") != "compiler-message":
            continue
        message = record.get("message") or {}
        level = message.get("level")
        if level not in ("error", "warning"):
            continue
        text = message.get("message") or ""
        if text.startswith("aborting due to"):
            continue
        code = message.get("code")
        if isinstance(code, dict):
            code = code.get("code")
        code_s = code if isinstance(code, str) else None
        diag = Diagnostic(level=level, code=code_s, message=text,
                          rendered=relativize(message.get("rendered") or "", workdir))
        if code_s and code_s.startswith("clippy::"):
            clippy.append(diag)
        elif level == "error":
            errors.append(diag)
        else:
            warnings.append(diag)
    return clippy, errors, warnings


def _unavailable_reason(text: str) -> str | None:
    low = text.lower()
    if "no such command" in low or "no such subcommand" in low:
        return "clippy is not installed"
    if "component" in low and "clippy" in low and "not" in low:
        return "clippy component is not installed"
    return None


def run_clippy(tools: ToolRunner, workdir: Path | str, source: str, *,
               lints: tuple[str, ...] | list[str] | None = None,
               timeout: float = 180.0, cargo: str = "cargo") -> ClippyResult:
    """Write a probe crate and run the concurrency clippy set."""
    workdir = Path(workdir)
    lint_list = tuple(lints) if lints is not None else CONCURRENCY_LINTS
    (workdir / "src").mkdir(parents=True, exist_ok=True)
    (workdir / "Cargo.toml").write_text(cargo_toml("clippy_probe"), encoding="utf-8")
    (workdir / "src" / "main.rs").write_text(source, encoding="utf-8")
    cmd = [cargo, "clippy", "--message-format=json", "--", "-A", "clippy::all"]
    for lint in lint_list:
        cmd.extend(["-W", lint])
    started = time.monotonic()
    call = tools.run(cmd, workdir, timeout=timeout, offline=True)
    wall = int((time.monotonic() - started) * 1000)
    combined = (call.stderr or "") + "\n" + (call.stdout or "")
    if call.error is not None:
        cleanup_target(workdir)
        return ClippyResult(unavailable=call.error, wall_ms=wall)
    if call.timed_out:
        cleanup_target(workdir)
        return ClippyResult(timed_out=True, wall_ms=wall)
    reason = _unavailable_reason(combined)
    clippy, errors, warnings = _parse(call.stdout, workdir)
    if reason and not clippy and not errors and not warnings:
        cleanup_target(workdir)
        return ClippyResult(unavailable=reason, wall_ms=wall)
    cleanup_target(workdir)
    return ClippyResult(clippy=clippy, rustc_errors=errors,
                        rustc_warnings=warnings, wall_ms=wall)


def probe_lints(tools: ToolRunner, workdir: Path | str, *,
                lints: tuple[str, ...] | list[str] | None = None,
                timeout: float = 180.0, cargo: str = "cargo") -> dict[str, bool]:
    """Return whether each lint is known to this toolchain.

    An unknown lint is reported by clippy and dropped from later runs. A missing
    clippy component maps every lint to False.
    """
    lint_list = tuple(lints) if lints is not None else CONCURRENCY_LINTS
    source = "fn main() {}\n"
    result = run_clippy(tools, workdir, source, lints=lint_list,
                        timeout=timeout, cargo=cargo)
    if result.unavailable:
        return {lint: False for lint in lint_list}
    # Re-run is unnecessary: unknown lints show up as rustc errors on the
    # same invocation. ``run_clippy`` already parsed them into rustc_errors.
    unknown = set()
    for diag in result.rustc_errors:
        text = f"{diag.message}\n{diag.rendered}"
        for lint in lint_list:
            if lint in text and "unknown" in text.lower():
                unknown.add(lint)
    return {lint: lint not in unknown for lint in lint_list}


def render_clippy_sections(result: ClippyResult) -> list[str]:
    """Ordered text sections (rustc errors, rustc warnings, clippy)."""
    def block(title: str, items: list[Diagnostic]) -> str:
        if not items:
            return ""
        body = "\n".join(d.rendered or f"{d.level}[{d.code}]: {d.message}" for d in items)
        return f"## {title}\n{body}"

    sections = [
        block("rustc errors", result.rustc_errors),
        block("rustc warnings", result.rustc_warnings),
        block("clippy", result.clippy),
    ]
    if result.unavailable:
        sections.append(f"## clippy\nclippy unavailable: {result.unavailable}")
    if result.timed_out:
        sections.append("## clippy\nclippy timed out")
    return [s for s in sections if s]
