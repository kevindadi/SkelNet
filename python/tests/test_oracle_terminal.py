"""T2/F5: terminal-line extraction and oracle terminal/run outcome handling."""

import subprocess
from types import SimpleNamespace

from skelnet.backend import repo_root
from skelnet.cli import read_terminal
from skelnet.oracle import RustOracle, repo_toolchain_channel


def test_read_terminal_from_requirements():
    root = repo_root()
    assert read_terminal(root / "benchmarks/tasks/lock-order/abba_2lock") == "DONE t1=1 t2=1"
    assert read_terminal(root / "benchmarks/tasks/semaphore/permit_leak") == "DONE permits=1"


def test_read_terminal_absent_for_boundary_tasks():
    root = repo_root()
    assert read_terminal(root / "benchmarks/tasks/boundary/rwlock_unsupported") is None
    assert read_terminal(root / "benchmarks/tasks/boundary/unbounded_int_unknown") is None


def _runner(stdout: str, run_rc: int = 0):
    def run(cmd, cwd, timeout, env):
        if "build" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=run_rc, stdout=stdout, stderr="")
    return run


def test_terminal_correct(tmp_path):
    oracle = RustOracle(terminal="DONE x", runner=_runner("DONE x\n"))
    result = oracle.evaluate("fn main() {}", tmp_path)
    assert result.built and result.ran
    assert result.terminal_check == "pass"
    assert result.functional_ok


def test_terminal_wrong(tmp_path):
    oracle = RustOracle(terminal="DONE x", runner=_runner("nope\n"))
    result = oracle.evaluate("fn main() {}", tmp_path)
    assert result.terminal_check == "fail"
    assert not result.functional_ok


def test_terminal_absent_is_not_a_pass(tmp_path):
    oracle = RustOracle(terminal=None, runner=_runner("DONE x\n"))
    result = oracle.evaluate("fn main() {}", tmp_path)
    assert result.terminal_check == "absent"
    assert not result.functional_ok


def test_terminal_not_applicable_when_not_checked(tmp_path):
    oracle = RustOracle(terminal="DONE x", runner=_runner("DONE x\n"))
    result = oracle.evaluate("fn main() {}", tmp_path, check_terminal=False)
    assert result.terminal_check == "not_applicable"
    assert result.functional_ok is None
    assert result.run_ok is True


def test_terminal_not_run_on_build_failure(tmp_path):
    def runner(cmd, cwd, timeout, env):
        if "build" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    result = RustOracle(terminal="DONE x", runner=runner).evaluate("fn main() {}", tmp_path)
    assert result.terminal_check == "not_run"
    assert result.run_ok is False
    assert not result.built


def test_oracle_pins_rustup_toolchain(tmp_path):
    seen: dict = {}

    def runner(cmd, cwd, timeout, env):
        seen["env"] = env
        if "build" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    RustOracle(terminal=None, runner=runner).evaluate("fn main() {}", tmp_path)
    channel = repo_toolchain_channel()
    assert channel, "expected a channel in rust-toolchain.toml"
    assert seen["env"].get("RUSTUP_TOOLCHAIN") == channel


def test_terminal_not_run_on_timeout(tmp_path):
    def runner(cmd, cwd, timeout, env):
        raise subprocess.TimeoutExpired(cmd, timeout)
    result = RustOracle(terminal="DONE x", runner=runner).evaluate("fn main() {}", tmp_path)
    assert result.terminal_check == "not_run"
    assert result.run_ok is False
