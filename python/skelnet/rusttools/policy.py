"""O1: build the program (std + concir_sync only) and scan its policy.

The policy scan is deliberately conservative: comments and string/char literals
are blanked first, then a small set of forbidden tokens is searched. A hit is a
``policy_violation`` with the rule name and line number.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .base import FAIL, PASS, UNAVAILABLE, LayerResult
from .runner import ToolRunner

ALLOWED_CRATES = {"std", "core", "alloc", "concir_sync", "crate", "self", "super"}

# (rule name, compiled pattern). Patterns run on the stripped source.
_TOKEN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("unsafe", re.compile(r"\bunsafe\b")),
    ("static_mut", re.compile(r"\bstatic\s+mut\b")),
    ("thread_sleep", re.compile(r"\bthread\s*::\s*sleep\b|\bsleep\s*\(")),
    ("yield_now", re.compile(r"\byield_now\b")),
    ("process_exit", re.compile(r"\bprocess\s*::\s*exit\b")),
    ("process_abort", re.compile(r"\bprocess\s*::\s*abort\b")),
    ("extern_crate", re.compile(r"\bextern\s+crate\b")),
    ("feature_gate", re.compile(r"#!\s*\[\s*feature\b")),
]

_USE_RE = re.compile(r"\buse\s+(?:::)?\s*([A-Za-z_][A-Za-z0-9_]*)")
_MOD_RE = re.compile(r"\bmod\s+([A-Za-z_][A-Za-z0-9_]*)")


def strip_comments_and_strings(src: str) -> str:
    """Blank comments and string/char literals, preserving newlines and length."""
    out = list(src)
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if c == "/" and nxt == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                if i + 1 < n:
                    out[i + 1] = " "
                i += 2
            continue
        if c == '"':
            out[i] = " "
            i += 1
            while i < n:
                if src[i] == "\\" and i + 1 < n:
                    out[i] = out[i + 1] = " "
                    i += 2
                    continue
                if src[i] == '"':
                    out[i] = " "
                    i += 1
                    break
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            continue
        if c == "'":
            # char literal or lifetime: only blank a closed char literal.
            j = i + 1
            if j < n and src[j] == "\\":
                j += 2
            else:
                j += 1
            if j < n and src[j] == "'":
                for k in range(i, j + 1):
                    out[k] = " "
                i = j + 1
                continue
            i += 1
            continue
        i += 1
    return "".join(out)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def scan_policy(src: str) -> list[tuple[str, int]]:
    """Return ``(rule, line)`` for every policy violation, in source order."""
    stripped = strip_comments_and_strings(src)
    local_mods = set(_MOD_RE.findall(stripped))
    hits: list[tuple[str, int]] = []
    for rule, pattern in _TOKEN_RULES:
        for match in pattern.finditer(stripped):
            hits.append((rule, _line_of(stripped, match.start())))
    for match in _USE_RE.finditer(stripped):
        crate = match.group(1)
        if crate not in ALLOWED_CRATES and crate not in local_mods:
            hits.append((f"external_crate:{crate}", _line_of(stripped, match.start())))
    hits.sort(key=lambda item: item[1])
    return hits


def evaluate_o1(tools: ToolRunner, project_dir: Path | str, src: str, *,
                timeout: float = 180.0, cargo: str = "cargo") -> LayerResult:
    started = time.monotonic()
    build = tools.run([cargo, "build"], project_dir, timeout=timeout, offline=True)
    wall = int((time.monotonic() - started) * 1000)
    if build.error is not None:
        return LayerResult("O1", UNAVAILABLE, "tool_missing",
                           f"cargo unavailable: {build.error}", wall)
    if build.timed_out:
        return LayerResult("O1", FAIL, "no_build", "cargo build timed out", wall)
    if build.returncode != 0:
        return LayerResult("O1", FAIL, "no_build",
                           _summarize(build.stderr) or "cargo build failed", wall)
    violations = scan_policy(src)
    if violations:
        rule, line = violations[0]
        detail = f"{rule} at line {line}"
        return LayerResult("O1", FAIL, "policy_violation", detail, wall,
                           data={"violations": [{"rule": r, "line": ln}
                                                for r, ln in violations]})
    return LayerResult("O1", PASS, None, None, wall)


def _summarize(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    return text[-limit:]
