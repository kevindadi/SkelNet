"""T2/F5: terminal-line extraction and the oracle's terminal/run outcome.

Rewritten for the round-3 four-layer oracle: the fake runner stubs only the
outermost subprocesses, and the layer logic is exercised for real.
"""

import subprocess
from pathlib import Path

from skelnet.backend import repo_root
from skelnet.cli import read_terminal
from skelnet.oracle import RustOracle, repo_toolchain_channel

from round03_helpers import FakeTools


def _expected_toolchain_channel() -> str:
    """Independent expectation: read rust-toolchain.toml with tomllib."""
    import tomllib
    with (repo_root() / "rust-toolchain.toml").open("rb") as handle:
        return tomllib.load(handle)["toolchain"]["channel"]


def test_read_terminal_from_requirements():
    root = repo_root()
    assert read_terminal(root / "benchmarks/tasks/lock-order/abba_2lock") == "DONE t1=1 t2=1"
    assert read_terminal(root / "benchmarks/tasks/semaphore/permit_leak") == "DONE permits=1"


def test_read_terminal_absent_for_boundary_tasks():
    root = repo_root()
    assert read_terminal(root / "benchmarks/tasks/boundary/rwlock_unsupported") is None
    assert read_terminal(root / "benchmarks/tasks/boundary/unbounded_int_unknown") is None


def test_terminal_correct(tmp_path):
    oracle = RustOracle(terminal="DONE x", runner=FakeTools(terminal="DONE x"))
    result = oracle.evaluate("fn main() {}", tmp_path)
    assert result.built and result.ran
    assert result.terminal_check == "pass"
    assert result.functional_ok


def test_terminal_wrong(tmp_path):
    oracle = RustOracle(terminal="DONE x", runner=FakeTools(terminal="DONE x",
                                                            o2_stdout="nope\n"))
    result = oracle.evaluate("fn main() {}", tmp_path)
    assert result.terminal_check == "fail"
    assert not result.functional_ok


def test_terminal_absent_is_not_a_pass(tmp_path):
    oracle = RustOracle(terminal=None, runner=FakeTools(terminal="DONE x"))
    result = oracle.evaluate("fn main() {}", tmp_path)
    assert result.terminal_check == "absent"
    assert not result.functional_ok


def test_terminal_not_applicable_when_not_checked(tmp_path):
    oracle = RustOracle(terminal="DONE x", runner=FakeTools(terminal="DONE x"))
    result = oracle.evaluate("fn main() {}", tmp_path, check_terminal=False)
    assert result.terminal_check == "not_applicable"
    assert result.functional_ok is None
    assert result.run_ok is True


def test_terminal_not_run_on_build_failure(tmp_path):
    result = RustOracle(terminal="DONE x",
                        runner=FakeTools(build_ok=False)).evaluate("fn main() {}", tmp_path)
    assert result.terminal_check == "not_run"
    assert result.run_ok is False
    assert not result.built


def test_oracle_pins_rustup_toolchain(tmp_path):
    tools = FakeTools()
    RustOracle(terminal=None, runner=tools).evaluate("fn main() {}", tmp_path)
    expected = _expected_toolchain_channel()
    assert expected, "expected a channel in rust-toolchain.toml"
    assert repo_toolchain_channel() == expected
    assert tools.envs and tools.envs[0].get("RUSTUP_TOOLCHAIN") == expected


def test_terminal_not_run_on_timeout(tmp_path):
    def runner(cmd, cwd, timeout, env):
        raise subprocess.TimeoutExpired(cmd, timeout)
    result = RustOracle(terminal="DONE x", runner=runner).evaluate("fn main() {}", tmp_path)
    assert result.terminal_check == "not_run"
    assert result.run_ok is False
