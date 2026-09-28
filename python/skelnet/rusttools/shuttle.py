"""O3 (Shuttle half): rewrite std concurrency to Shuttle and explore schedules.

The rewrite is textual and conservative: ``std::sync`` -> ``shuttle::sync``,
``std::thread`` -> ``shuttle::thread``, ``fn main`` -> ``fn __skelnet_body``,
and an appended ``main`` that runs PCT then random. A program that fails to
compile after the rewrite is reported ``shuttle_unsupported`` (with the compile
error), never silently treated as a defect.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .base import FAIL, PASS, UNSUPPORTED, LayerResult
from .runner import ToolRunner

# Constructs Shuttle cannot model: their presence is a *definite* unsupported.
_UNSUPPORTED_PATTERNS = [
    (re.compile(r"\bthread\s*::\s*scope\b"), "thread::scope"),
    (re.compile(r"\bOnceLock\b"), "OnceLock"),
    (re.compile(r"\bLazyLock\b"), "LazyLock"),
    (re.compile(r"\bBarrier\b"), "Barrier"),
    (re.compile(r"\bstd\s*::\s*process\b"), "std::process"),
]

_MAIN_RE = re.compile(r"\bfn\s+main\s*\(([^)]*)\)\s*(->[^{]*)?\{")


def transform_source(src: str, *, iterations: int = 2000, depth: int = 3) -> tuple[str | None, str | None]:
    """Return ``(transformed, unsupported_reason)``."""
    for pattern, name in _UNSUPPORTED_PATTERNS:
        if pattern.search(src):
            return None, name
    match = _MAIN_RE.search(src)
    if match is None:
        return None, "no `fn main`"
    if match.group(2):
        return None, "`fn main` returns a value"
    transformed = src.replace("std::sync", "shuttle::sync")
    transformed = transformed.replace("std :: sync", "shuttle::sync")
    transformed = transformed.replace("std::thread", "shuttle::thread")
    transformed = transformed.replace("std :: thread", "shuttle::thread")
    # Rename the program entry point; re-search because the replacements above
    # changed the string length.
    renamed_match = _MAIN_RE.search(transformed)
    if renamed_match is None:  # pragma: no cover - structure preserved above
        return None, "no `fn main`"
    start, end = renamed_match.span()
    renamed = (transformed[:start]
               + renamed_match.group(0).replace("main", "__skelnet_body", 1)
               + transformed[end:])
    appended = (
        "\nfn main() {\n"
        f"    shuttle::check_pct(|| {{ __skelnet_body(); }}, {iterations}, {depth});\n"
        f"    shuttle::check_random(|| {{ __skelnet_body(); }}, {iterations});\n"
        "}\n"
    )
    return renamed + appended, None


def shuttle_cargo_toml(shim_path: Path | str, *, name: str = "shuttle_probe") -> str:
    return f"""[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "{name}"
path = "src/main.rs"

[dependencies]
concir_sync = {{ package = "concir_sync_shuttle", path = "{shim_path}" }}
shuttle = "=0.8.1"

[workspace]
"""


def write_shuttle_project(project_dir: Path | str, transformed: str,
                          shim_path: Path | str, *,
                          name: str = "shuttle_probe") -> Path:
    project_dir = Path(project_dir)
    src = project_dir / "src"
    src.mkdir(parents=True, exist_ok=True)
    (project_dir / "Cargo.toml").write_text(
        shuttle_cargo_toml(shim_path, name=name), encoding="utf-8")
    (src / "main.rs").write_text(transformed, encoding="utf-8")
    return project_dir / "target" / "debug" / name


_SCHEDULE_RE = re.compile(r"failing schedule:\s*\n\"\n(.*?)\n\"", re.S)


def parse_schedule(text: str) -> str | None:
    """The serialized Shuttle schedule from a failure message, if present."""
    match = _SCHEDULE_RE.search(text)
    return match.group(1) if match else None


def _diagnostic_line(text: str) -> str:
    """The `deadlock!` line, else the `panicked` line, else the first line."""
    for needle in ("deadlock!", "panicked"):
        for line in text.splitlines():
            if needle in line:
                return line.strip()[:200]
    return _first_line(text)


def _save_failure(project_dir: Path, output: str) -> None:
    """Persist the full Shuttle output next to the project (kept on cleanup)."""
    (project_dir / "failure.txt").write_text(output, encoding="utf-8")


def evaluate_shuttle(tools: ToolRunner, workdir: Path | str, src: str, *,
                     shim_path: Path | str, iterations: int = 2000, depth: int = 3,
                     seed: int = 0, timeout: float = 300.0,
                     cargo: str = "cargo") -> LayerResult:
    started = time.monotonic()
    transformed, reason = transform_source(src, iterations=iterations, depth=depth)
    if transformed is None:
        return LayerResult("O3", UNSUPPORTED, "shuttle_unsupported",
                           f"unsupported construct: {reason}",
                           int((time.monotonic() - started) * 1000))
    project_dir = Path(workdir) / "shuttle"
    binary = write_shuttle_project(project_dir, transformed, shim_path)
    build = tools.run([cargo, "build"], project_dir, timeout=timeout, offline=True)
    if build.error is not None:
        return LayerResult("O3", UNSUPPORTED, "shuttle_unsupported",
                           f"shuttle build unavailable: {build.error}",
                           int((time.monotonic() - started) * 1000))
    if build.returncode != 0 or build.timed_out:
        detail = (build.stderr or "").strip()[-200:]
        return LayerResult("O3", UNSUPPORTED, "shuttle_unsupported",
                           f"shuttle build failed: {detail}",
                           int((time.monotonic() - started) * 1000))
    run = tools.run([str(binary)], project_dir, timeout=timeout,
                    env_extra={"SHUTTLE_RANDOM_SEED": str(seed)})
    wall = int((time.monotonic() - started) * 1000)
    if run.error is not None:
        return LayerResult("O3", UNSUPPORTED, "shuttle_unsupported",
                           f"shuttle run unavailable: {run.error}", wall)
    combined = (run.stderr or "") + (run.stdout or "")
    if run.timed_out:
        _save_failure(project_dir, combined)
        return LayerResult("O3", FAIL, "deadlock", "shuttle timed out", wall,
                           data={"schedule": parse_schedule(combined)})
    # The tool's own exit code decides; program output never does.
    if run.returncode == 0:
        return LayerResult("O3", PASS, None, None, wall)
    if "did not exercise any concurrency" in combined:
        # PCT only asserts this after a complete first execution with no
        # scheduling points: nothing to explore, not a defect.
        return LayerResult("O3", PASS, None, "no concurrency to explore", wall,
                           data={"no_concurrency": True})
    _save_failure(project_dir, combined)
    schedule = parse_schedule(combined)
    if "deadlock! blocked tasks" in combined:
        return LayerResult("O3", FAIL, "deadlock", _diagnostic_line(combined),
                           wall, data={"schedule": schedule})
    return LayerResult("O3", FAIL, "panic", _diagnostic_line(combined), wall,
                       data={"schedule": schedule})


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""
