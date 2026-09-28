"""Compile a single-file Rust program and report rustc diagnostics.

This is the shared Rust-stage compile check used by SKEL/CIR (round 5) and the
baseline arms (round 4). The compile error text is what every group's
``rust_fix`` feedback is built from, so the interface is frozen:

``compile_rust(tools, workdir, source, *, timeout=180.0, cargo="cargo")`` writes
``Cargo.toml`` (via :func:`oracle.cargo_toml`) and ``src/main.rs`` under
``workdir``, runs ``cargo build --message-format=json`` offline, and returns a
:class:`CompileResult`. ``render_compile_errors`` is the only thing that should
be sent back to the model.

Diagnostics never leak an absolute path: the workdir, the repository root and
the rustc sysroot source prefix are rewritten, and any remaining absolute
``-->``/``:::` position is replaced by ``<abs>/<filename>``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..backend import repo_root
from ..oracle import cargo_toml
from .runner import ToolRunner, cleanup_target

_POSITION_RE = re.compile(r"^(\s*(?:-->|:::)\s*)(/.*)$")


@dataclass
class CompileResult:
    ok: bool = False
    unavailable: str | None = None
    timed_out: bool = False
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    wall_ms: int = 0


_SYSROOT: str | None | bool = False  # False = not looked up yet


def _lookup_sysroot() -> str | None:
    try:
        proc = subprocess.run(["rustc", "--print", "sysroot"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _sysroot() -> str | None:
    global _SYSROOT
    if _SYSROOT is False:
        _SYSROOT = _lookup_sysroot()
    return _SYSROOT  # type: ignore[return-value]


def _relativize(text: str, workdir: Path) -> str:
    """Rewrite every absolute path in a diagnostic to a relative form."""
    if not text:
        return text
    for base in {str(workdir), str(workdir.resolve()), str(repo_root())}:
        text = text.replace(base + "/", "").replace(base, ".")
    sysroot = _sysroot()
    if sysroot:
        for base in {sysroot, os.path.realpath(sysroot)}:
            text = text.replace(base + "/lib/rustlib/src/rust/", "<rust>/")
    lines = []
    for line in text.splitlines():
        match = _POSITION_RE.match(line)
        if match:
            line = match.group(1) + "<abs>/" + match.group(2).rsplit("/", 1)[-1]
        lines.append(line)
    return "\n".join(lines)


def _first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _parse_messages(stdout: str, workdir: Path) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    warnings: list[dict] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
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
        # Drop rustc's "aborting due to N previous errors" summary lines.
        if text.startswith("aborting due to"):
            continue
        code = message.get("code")
        if isinstance(code, dict):
            code = code.get("code")
        diagnostic = {
            "level": level,
            "code": code if isinstance(code, str) else None,
            "message": _relativize(text, workdir),
            "rendered": _relativize(message.get("rendered") or "", workdir),
        }
        (errors if level == "error" else warnings).append(diagnostic)
    return errors, warnings


def compile_rust(tools: ToolRunner, workdir: Path | str, source: str, *,
                 timeout: float = 180.0, cargo: str = "cargo") -> CompileResult:
    workdir = Path(workdir)
    (workdir / "src").mkdir(parents=True, exist_ok=True)
    (workdir / "Cargo.toml").write_text(cargo_toml("probe"), encoding="utf-8")
    (workdir / "src" / "main.rs").write_text(source, encoding="utf-8")
    call = tools.run([cargo, "build", "--message-format=json"], workdir,
                     timeout=timeout, offline=True)
    if call.error is not None:
        return CompileResult(unavailable=call.error, wall_ms=call.wall_ms)
    if call.timed_out:
        cleanup_target(workdir)
        return CompileResult(timed_out=True, wall_ms=call.wall_ms)
    errors, warnings = _parse_messages(call.stdout, workdir)
    result = CompileResult(errors=errors, warnings=warnings, wall_ms=call.wall_ms)
    if call.returncode == 0:
        result.ok = not errors
    elif errors:
        result.ok = False
    else:
        # A non-zero exit with no compiler error is an environment problem, not
        # a program defect: report it as unavailable so the pipeline stops.
        stderr = _relativize(_first_nonempty_line(call.stderr or ""), workdir)
        result.unavailable = (f"cargo exited {call.returncode} without compiler "
                              f"errors: {stderr}")
    cleanup_target(workdir)
    return result


def render_compile_errors(result: CompileResult, *, limit_bytes: int = 8192) -> str:
    """Concatenate the rendered errors in order, truncated at a UTF-8 boundary."""
    text = "\n".join(e.get("rendered") or "" for e in result.errors)
    encoded = text.encode("utf-8")
    if len(encoded) > limit_bytes:
        text = encoded[:limit_bytes].decode("utf-8", errors="ignore") + "\n[truncated]"
    return text
