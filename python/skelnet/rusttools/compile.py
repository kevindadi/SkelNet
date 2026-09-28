"""Compile a single-file Rust program and report rustc diagnostics.

This is the shared Rust-stage compile check used by SKEL/CIR (round 5) and the
baseline arms (round 4). The compile error text is what every group's
``rust_fix`` feedback is built from, so the interface is frozen:

``compile_rust(tools, workdir, source, *, timeout=180.0, cargo="cargo")`` writes
``Cargo.toml`` (via :func:`oracle.cargo_toml`) and ``src/main.rs`` under
``workdir``, runs ``cargo build --message-format=json`` offline, and returns a
:class:`CompileResult`. ``render_compile_errors`` is the only thing that should
be sent back to the model.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..oracle import cargo_toml
from .runner import ToolRunner, cleanup_target


@dataclass
class CompileResult:
    ok: bool = False
    unavailable: str | None = None
    timed_out: bool = False
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    wall_ms: int = 0


def _relativize(text: str, workdir: Path) -> str:
    """Replace the absolute project path with a relative one."""
    if not text:
        return text
    for base in {str(workdir), str(workdir.resolve())}:
        text = text.replace(base + "/", "").replace(base, ".")
    return text


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
            "message": text,
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
        return CompileResult(timed_out=True, wall_ms=call.wall_ms)
    errors, warnings = _parse_messages(call.stdout, workdir)
    result = CompileResult(ok=call.returncode == 0 and not errors,
                           errors=errors, warnings=warnings, wall_ms=call.wall_ms)
    cleanup_target(workdir)
    return result


def render_compile_errors(result: CompileResult, *, limit_bytes: int = 8192) -> str:
    """Concatenate the rendered errors in order, truncated at a UTF-8 boundary."""
    text = "\n".join(e.get("rendered") or "" for e in result.errors)
    encoded = text.encode("utf-8")
    if len(encoded) > limit_bytes:
        text = encoded[:limit_bytes].decode("utf-8", errors="ignore") + "\n[truncated]"
    return text
