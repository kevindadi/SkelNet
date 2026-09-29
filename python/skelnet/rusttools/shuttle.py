"""O3 (Shuttle half): rewrite std concurrency to Shuttle and explore schedules.

The rewrite is textual and conservative: ``std::sync`` -> ``shuttle::sync``,
``std::thread`` -> ``shuttle::thread``, ``fn main`` -> ``fn __skelnet_body``,
and an appended ``main`` that runs PCT then random. A program that fails to
compile after the rewrite is reported ``shuttle_unsupported`` (with the compile
error), never silently treated as a defect.

PCT runs through ``shuttle::Runner`` with ``MaxSteps::ContinueAfter(10_000)``:
PCT is deliberately unfair, so an iteration that exceeds the bound only shows
the scheduler starved a thread (for example a correct busy-wait) and is
abandoned without a verdict. Random keeps Shuttle's default
``FailAfter(1_000_000)``; exceeding it under a probabilistically fair scheduler
is reported as ``livelock``.

With a terminal line (round 9b), each explored schedule prints a marker line
after the program body, and the last non-empty line of every completed
schedule must equal the terminal line, as in O2. A mismatch is
``wrong_output``. Program output is only ever compared exactly with the
terminal line; it is never searched for keywords.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .base import FAIL, PASS, UNSUPPORTED, LayerResult
from .runner import ToolRunner
from .stress import last_nonempty_line

PCT_MARKER = "__SKELNET_SHUTTLE_END_PCT__"
RANDOM_MARKER = "__SKELNET_SHUTTLE_END_RANDOM__"
PCT_MAX_STEPS = 10_000
_MARKERS = {PCT_MARKER: "pct", RANDOM_MARKER: "random"}
_EVIDENCE_LINES = 40

# Constructs Shuttle cannot model: their presence is a *definite* unsupported.
_UNSUPPORTED_PATTERNS = [
    (re.compile(r"\bthread\s*::\s*scope\b"), "thread::scope"),
    (re.compile(r"\bOnceLock\b"), "OnceLock"),
    (re.compile(r"\bLazyLock\b"), "LazyLock"),
    (re.compile(r"\bBarrier\b"), "Barrier"),
    (re.compile(r"\bstd\s*::\s*process\b"), "std::process"),
]

_MAIN_RE = re.compile(r"\bfn\s+main\s*\(([^)]*)\)\s*(->[^{]*)?\{")


def _closure(marker: str | None) -> str:
    if marker is None:
        return "|| { __skelnet_body(); }"
    return f'|| {{ __skelnet_body(); println!("\\n{marker}"); }}'


def transform_source(src: str, *, iterations: int = 2000, depth: int = 3,
                     markers: bool = False) -> tuple[str | None, str | None]:
    """Return ``(transformed, unsupported_reason)``.

    ``markers=True`` makes every completed schedule print ``PCT_MARKER`` or
    ``RANDOM_MARKER`` on its own line after the program body.
    """
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
    pct = _closure(PCT_MARKER if markers else None)
    random = _closure(RANDOM_MARKER if markers else None)
    appended = (
        "\nfn main() {\n"
        "    let mut __skelnet_pct_config = shuttle::Config::new();\n"
        "    __skelnet_pct_config.max_steps = "
        f"shuttle::MaxSteps::ContinueAfter({PCT_MAX_STEPS});\n"
        "    shuttle::Runner::new(\n"
        f"        shuttle::scheduler::PctScheduler::new({depth}, {iterations}),\n"
        "        __skelnet_pct_config,\n"
        f"    ).run({pct});\n"
        f"    shuttle::check_random({random}, {iterations});\n"
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


_MAX_STEPS_NEEDLE = "exceeded max_steps bound"


def _diagnostic_line(text: str) -> str:
    """The `deadlock!` line, else the step-bound line, else the `panicked`
    line, else the first line.

    The step-bound message follows Shuttle's own `panicked at <registry path>`
    line, so it must be found before the `panicked` fallback.
    """
    for needle in ("deadlock!", _MAX_STEPS_NEEDLE, "panicked"):
        for line in text.splitlines():
            if needle in line:
                return line.strip()[:200]
    return _first_line(text)


def _split_schedules(stdout: str) -> list[tuple[str, list[str]]]:
    """Completed schedules as ``(scheduler, lines)`` in output order.

    A schedule is the text before a line that equals a marker; the scheduler
    is named by that marker. The empty line the marker's own ``\\n`` adds is
    dropped. Text after the last marker (an unfinished or abandoned schedule)
    is not a completed schedule.
    """
    schedules: list[tuple[str, list[str]]] = []
    current: list[str] = []
    for line in stdout.splitlines():
        scheduler = _MARKERS.get(line)
        if scheduler is None:
            current.append(line)
            continue
        if current and current[-1] == "":
            current.pop()
        schedules.append((scheduler, current))
        current = []
    return schedules


def _strip_markers(stdout: str) -> str:
    """``stdout`` without the marker lines (and the empty line each adds)."""
    kept: list[str] = []
    for line in stdout.splitlines():
        if line in _MARKERS:
            if kept and kept[-1] == "":
                kept.pop()
            continue
        kept.append(line)
    return "\n".join(kept) + ("\n" if kept else "")


def _counts(schedules, iterations: int, *, no_concurrency: bool) -> dict:
    """D9b-12. ``pct_abandoned`` is known only once PCT finished, i.e. once a
    random schedule completed; otherwise (and for no concurrency) it is None."""
    pct = sum(1 for scheduler, _ in schedules if scheduler == "pct")
    random = sum(1 for scheduler, _ in schedules if scheduler == "random")
    abandoned = None
    if not no_concurrency and random > 0:
        abandoned = iterations - pct
    return {"pct_completed": pct, "random_completed": random,
            "pct_abandoned": abandoned}


def _wrong_schedules(schedules, terminal: str) -> list[tuple[int, str, str, list[str]]]:
    wrong = []
    for index, (scheduler, lines) in enumerate(schedules, start=1):
        line = last_nonempty_line("\n".join(lines))
        if line != terminal:
            wrong.append((index, scheduler, line, lines))
    return wrong


def _save_failure(project_dir: Path, output: str) -> None:
    """Persist the full Shuttle output next to the project (kept on cleanup)."""
    (project_dir / "failure.txt").write_text(output, encoding="utf-8")


def _save_output_mismatch(project_dir: Path, index: int, total: int,
                          scheduler: str, terminal: str, line: str,
                          lines: list[str]) -> None:
    body = [
        f"output mismatch in schedule {index}/{total} ({scheduler})",
        f"expected last line: {terminal!r}",
        f"observed last line: {line!r}",
        f"output of that schedule (first {_EVIDENCE_LINES} lines):",
        *lines[:_EVIDENCE_LINES],
    ]
    _save_failure(project_dir, "\n".join(body) + "\n")


def evaluate_shuttle(tools: ToolRunner, workdir: Path | str, src: str, *,
                     shim_path: Path | str, iterations: int = 2000, depth: int = 3,
                     seed: int = 0, timeout: float = 300.0,
                     cargo: str = "cargo",
                     terminal: str | None = None) -> LayerResult:
    """Explore ``src`` under Shuttle PCT then random.

    Exit code 0 (or PCT's no-concurrency assertion) passes unless, with a
    ``terminal`` line, some completed schedule's last non-empty stdout line
    differs from it (``wrong_output``). A non-zero exit keeps its tool-derived
    category: ``deadlock!`` -> deadlock, step bound -> livelock, else panic.
    """
    started = time.monotonic()
    transformed, reason = transform_source(src, iterations=iterations, depth=depth,
                                           markers=True)
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
    stdout = run.stdout or ""
    combined = (run.stderr or "") + stdout
    evidence = (run.stderr or "") + _strip_markers(stdout)
    schedules = _split_schedules(stdout)
    no_concurrency = (not run.timed_out and run.returncode != 0
                      and "did not exercise any concurrency" in combined)
    data: dict = _counts(schedules, iterations, no_concurrency=no_concurrency)
    wrong = _wrong_schedules(schedules, terminal) if terminal is not None else []

    if run.timed_out or (run.returncode != 0 and not no_concurrency):
        # D9b-6: the tool's exit code and diagnostics decide the category;
        # wrong schedules seen before the failure are recorded only.
        _save_failure(project_dir, evidence)
        data["schedule"] = parse_schedule(combined)
        if terminal is None:
            data["output_check"] = "not_run"
        else:
            data["schedules_checked"] = len(schedules)
            data["schedules_wrong"] = len(wrong)
        if run.timed_out:
            return LayerResult("O3", FAIL, "deadlock", "shuttle timed out", wall,
                               data=data)
        if "deadlock! blocked tasks" in combined:
            category = "deadlock"
        elif _MAX_STEPS_NEEDLE in combined:
            category = "livelock"
        else:
            category = "panic"
        return LayerResult("O3", FAIL, category, _diagnostic_line(combined),
                           wall, data=data)

    # Exit code 0, or PCT asserted after one complete execution that there
    # was nothing to schedule. The output check applies to both (D9b-4).
    detail = None
    if no_concurrency:
        detail = "no concurrency to explore"
        data["no_concurrency"] = True
    if terminal is None:
        data["output_check"] = "not_run"
    elif not schedules:
        data["output_check"] = "no_schedules"
    else:
        data["schedules_checked"] = len(schedules)
        data["schedules_wrong"] = len(wrong)
        if not wrong:
            data["output_check"] = "pass"
        else:
            index, scheduler, line, lines = wrong[0]
            total = len(schedules)
            _save_output_mismatch(project_dir, index, total, scheduler,
                                  terminal, line, lines)
            data["output_check"] = "fail"
            data["first_wrong"] = {"index": index, "scheduler": scheduler,
                                   "line": line[:200]}
            data["schedule"] = None
            shown = line[:200] if line else "(no non-empty stdout line)"
            return LayerResult("O3", FAIL, "wrong_output",
                               f"schedule {index}/{total} ({scheduler}): {shown}",
                               wall, data=data)
    return LayerResult("O3", PASS, None, detail, wall, data=data)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""
