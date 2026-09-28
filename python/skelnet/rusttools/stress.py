"""O2: run the built program R times and check termination + exact output.

Unlike the round-1 oracle (which matched the terminal line as a substring of a
single ``cargo run``), this runs the binary directly, R times, and requires the
*last non-empty line* to equal the expected terminal line exactly.
"""

from __future__ import annotations

import time
from pathlib import Path

from .base import FAIL, PASS, LayerResult
from .runner import ToolRunner

HANG = "hang"
CRASH = "crash"
NO_OUTPUT = "no_output"
WRONG_OUTPUT = "wrong_output"


def last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""


def evaluate_o2(tools: ToolRunner, binary: Path | str, *,
                terminal: str | None, runs: int = 20, run_timeout: float = 10.0,
                check_terminal: bool = True,
                timeout: float | None = None) -> LayerResult:
    binary = Path(binary)
    started = time.monotonic()
    if not binary.exists():
        return LayerResult("O2", FAIL, NO_OUTPUT,
                           f"binary not found: {binary}",
                           int((time.monotonic() - started) * 1000),
                           data={"terminal_check": "not_run", "ran": False,
                                 "run_ok": False, "failures": []})
    failures: list[dict] = []
    observed = 0
    for index in range(runs):
        call = tools.run([str(binary)], binary.parent.parent,
                         timeout=run_timeout)
        observed += 1
        if call.error is not None:
            failures.append({"run": index + 1, "category": CRASH,
                             "detail": call.error})
            break
        if call.timed_out:
            failures.append({"run": index + 1, "category": HANG,
                             "detail": f"run {index + 1} timed out"})
            break
        if call.returncode != 0 or "panicked" in (call.stderr or ""):
            failures.append({"run": index + 1, "category": CRASH,
                             "detail": last_nonempty_line(call.stderr or "")})
            break
        line = last_nonempty_line(call.stdout or "")
        if not line:
            failures.append({"run": index + 1, "category": NO_OUTPUT,
                             "detail": "no non-empty stdout line"})
            break
        if check_terminal and terminal is not None and line != terminal:
            failures.append({"run": index + 1, "category": WRONG_OUTPUT,
                             "detail": line[:200]})
            break
    wall = int((time.monotonic() - started) * 1000)

    if not check_terminal:
        terminal_check = "not_applicable"
    elif terminal is None:
        terminal_check = "absent"
        if not failures:
            failures.append({"run": 0, "category": WRONG_OUTPUT,
                             "detail": "task has no expected terminal line"})
    else:
        terminal_check = "pass" if not failures else "fail"

    if failures:
        first = failures[0]
        run_ok = not any(f["category"] in (HANG, CRASH) for f in failures)
        return LayerResult("O2", FAIL, first["category"],
                           f"run {first['run']}/{runs}: {first['detail']}", wall,
                           data={"terminal_check": terminal_check,
                                 "failures": failures, "ran": True,
                                 "run_ok": run_ok})
    return LayerResult("O2", PASS, None, None, wall,
                       data={"terminal_check": terminal_check, "failures": [],
                             "ran": True, "run_ok": True})
