"""T4: Shuttle/miri layer behaviour and the disjoint seed ranges."""

from pathlib import Path

from skelnet.rusttools.runner import ToolRunner
from skelnet.rusttools.seeds import (FEEDBACK_MIRI_SEED_START,
                                     FEEDBACK_SHUTTLE_SEED, ORACLE_MIRI_SEED_START,
                                     ORACLE_SHUTTLE_SEED, feedback_miri_seeds,
                                     oracle_miri_seeds)
from skelnet.rusttools.shuttle import evaluate_shuttle

from round03_helpers import ns

SRC = "fn main() { std::thread::spawn(|| {}); }\n"


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
        return ns(1, "", "deadlock! blocked tasks: [main, t1, t2]")
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "fail" and result.category == "deadlock"


def test_shuttle_panic(tmp_path):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return ns(0, "", "")
        return ns(101, "", "thread 'main' panicked at x")
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "fail" and result.category == "panic"


def test_shuttle_pass(tmp_path):
    def run(cmd, cwd, timeout, env):
        return ns(0, "", "")
    result = evaluate_shuttle(_tools(run), tmp_path, SRC, shim_path=tmp_path / "shim")
    assert result.status == "pass"
