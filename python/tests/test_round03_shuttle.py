"""T4 (round 3b): Shuttle classification, no-concurrency and failure capture."""

import subprocess
from pathlib import Path

from skelnet.rusttools.runner import ToolRunner
from skelnet.rusttools.seeds import (FEEDBACK_MIRI_SEED_START,
                                     FEEDBACK_SHUTTLE_SEED, ORACLE_MIRI_SEED_START,
                                     ORACLE_SHUTTLE_SEED, feedback_miri_seeds,
                                     oracle_miri_seeds)
from skelnet.rusttools.shuttle import evaluate_shuttle, parse_schedule

from round03_helpers import ns

SRC = "fn main() { std::thread::spawn(|| {}); }\n"

FAILURE_OUTPUT = """\
thread 'main' panicked at runtime/execution.rs:203:17:
deadlock! blocked tasks: [main, t1, t2]
failing schedule:
"
PCT 3 1 2
"
pass that string to `shuttle::replay` to replay the failure
"""


def _tools(fn):
    return ToolRunner(runner=fn, toolchain=None)


def test_seed_ranges_are_disjoint():
    assert set(oracle_miri_seeds()).isdisjoint(feedback_miri_seeds())
    assert ORACLE_SHUTTLE_SEED != FEEDBACK_SHUTTLE_SEED
    assert ORACLE_MIRI_SEED_START != FEEDBACK_MIRI_SEED_START


def test_shuttle_unsupported_on_build_failure(tmp_path):
    tools = _tools(lambda cmd, cwd, timeout, env:
                   ns(1, "", "error: thread::scope not supported") if "build" in cmd
                   else ns(0, "", ""))
    result = evaluate_shuttle(tools, tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "unsupported"
    assert result.category == "shuttle_unsupported"


def test_shuttle_detects_deadlock(tmp_path):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return ns(0, "", "")
        return ns(1, "", FAILURE_OUTPUT)
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "fail" and result.category == "deadlock"
    assert "deadlock!" in result.detail


def test_shuttle_panic(tmp_path):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return ns(0, "", "")
        return ns(101, "", "thread 'main' panicked at x")
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "fail" and result.category == "panic"


def test_shuttle_exit_zero_with_deadlock_text_passes(tmp_path):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return ns(0, "", "")
        return ns(0, "DONE panic-free deadlock-free\n", "")
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "pass"


def test_shuttle_timeout_is_deadlock(tmp_path):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return ns(0, "", "")
        raise subprocess.TimeoutExpired(cmd, timeout)
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "fail" and result.category == "deadlock"


def test_shuttle_no_concurrency_is_pass(tmp_path):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return ns(0, "", "")
        return ns(101, "", "test closure did not exercise any concurrency")
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "pass"
    assert result.data.get("no_concurrency") is True
    assert result.detail == "no concurrency to explore"


def test_shuttle_saves_failure_and_schedule(tmp_path):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return ns(0, "", "")
        return ns(1, "", FAILURE_OUTPUT)
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    failure = tmp_path / "shuttle" / "failure.txt"
    assert failure.exists()
    assert "deadlock!" in failure.read_text()
    assert result.data["schedule"] == "PCT 3 1 2"
    assert parse_schedule(FAILURE_OUTPUT) == "PCT 3 1 2"


def test_shuttle_pass(tmp_path):
    def run(cmd, cwd, timeout, env):
        return ns(0, "", "")
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "pass"
