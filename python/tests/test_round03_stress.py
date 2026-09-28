"""T3: O2 requires the last non-empty line to equal the terminal line exactly."""

import subprocess

from skelnet.rusttools.runner import ToolRunner
from skelnet.rusttools.stress import evaluate_o2, last_nonempty_line

from round03_helpers import ns


def _binary(tmp_path):
    binary = tmp_path / "target" / "debug" / "probe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("x", encoding="utf-8")
    return binary


def _tools(fn):
    return ToolRunner(runner=fn, toolchain=None)


def test_exact_match_rejects_superstring(tmp_path):
    binary = _binary(tmp_path)
    tools = _tools(lambda *a: ns(0, "DONE done=10\n", ""))
    result = evaluate_o2(tools, binary, terminal="DONE done=1", runs=3)
    assert result.status == "fail" and result.category == "wrong_output"


def test_exact_match_accepts_exact_line(tmp_path):
    binary = _binary(tmp_path)
    tools = _tools(lambda *a: ns(0, "DONE done=1\n", ""))
    result = evaluate_o2(tools, binary, terminal="DONE done=1", runs=3)
    assert result.status == "pass"
    assert result.data["terminal_check"] == "pass"


def test_trailing_blank_lines_still_pass(tmp_path):
    binary = _binary(tmp_path)
    tools = _tools(lambda *a: ns(0, "DONE done=1\n\n\n", ""))
    result = evaluate_o2(tools, binary, terminal="DONE done=1", runs=2)
    assert result.status == "pass"
    assert last_nonempty_line("DONE done=1\n\n\n") == "DONE done=1"


def test_seventh_run_timeout_is_hang(tmp_path):
    binary = _binary(tmp_path)
    state = {"n": 0}

    def run(cmd, cwd, timeout, env):
        state["n"] += 1
        if state["n"] == 7:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return ns(0, "DONE done=1\n", "")
    result = evaluate_o2(_tools(run), binary, terminal="DONE done=1", runs=20)
    assert result.status == "fail" and result.category == "hang"
    assert result.data["failures"][0]["run"] == 7


def test_crash_and_no_output(tmp_path):
    binary = _binary(tmp_path)
    crash = evaluate_o2(_tools(lambda *a: ns(101, "", "panicked at x")),
                        binary, terminal="DONE", runs=1)
    assert crash.category == "crash"
    empty = evaluate_o2(_tools(lambda *a: ns(0, "\n\n", "")), binary,
                        terminal="DONE", runs=1)
    assert empty.category == "no_output"


def test_absent_terminal_fails(tmp_path):
    binary = _binary(tmp_path)
    result = evaluate_o2(_tools(lambda *a: ns(0, "anything\n", "")), binary,
                         terminal=None, runs=1)
    assert result.status == "fail"
    assert result.data["terminal_check"] == "absent"


def test_not_checked_still_runs(tmp_path):
    binary = _binary(tmp_path)
    result = evaluate_o2(_tools(lambda *a: ns(0, "anything\n", "")), binary,
                         terminal=None, runs=1, check_terminal=False)
    assert result.status == "pass"
    assert result.data["terminal_check"] == "not_applicable"
