"""T4 (round 3b): miri classification only on non-zero exit and its diagnostics."""

import subprocess

from skelnet.rusttools.runner import ToolRunner
from skelnet.rusttools.miri import evaluate_miri

from round03_helpers import ns


def _tools(fn):
    return ToolRunner(runner=fn, toolchain=None)


def _run(returncode: int, output: str = ""):
    return evaluate_miri(_tools(lambda *a: ns(returncode, output, output)),
                         "/tmp", seed_start=0, seed_count=2)


def test_exit_zero_with_words_passes():
    assert _run(0, "DONE panic-free deadlock-free\n").status == "pass"


def test_ub():
    result = _run(1, "error: Undefined Behavior: data race detected")
    assert result.status == "fail" and result.category == "ub"


def test_deadlock():
    result = _run(1, "error: deadlock")
    assert result.status == "fail" and result.category == "deadlock"


def test_thread_leak():
    result = _run(1, "the main thread terminated without waiting for all "
                     "remaining threads")
    assert result.status == "fail" and result.category == "thread_leak"


def test_panic():
    result = _run(101, "thread 'main' panicked at x")
    assert result.status == "fail" and result.category == "panic"


def test_unsupported_operation():
    result = _run(1, "error: unsupported operation: can't call foreign function")
    assert result.status == "unsupported"
    assert result.category == "miri_unsupported"


def test_unknown_nonzero_is_panic():
    result = _run(2, "some other miri error")
    assert result.status == "fail" and result.category == "panic"


def test_not_installed():
    result = _run(1, "error: no such command: `miri`")
    assert result.status == "unavailable" and result.category == "miri_unavailable"


def test_timeout_is_deadlock():
    def run(cmd, cwd, timeout, env):
        raise subprocess.TimeoutExpired(cmd, timeout)
    result = evaluate_miri(_tools(run), "/tmp", seed_start=0, seed_count=2)
    assert result.status == "fail" and result.category == "deadlock"
