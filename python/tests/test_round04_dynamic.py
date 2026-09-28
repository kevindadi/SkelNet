"""T4: dynamic feedback categories, driven by markers in the program source."""

import os
import subprocess
from pathlib import Path

from skelnet.oracle import ORACLE_MIRI_SEED_START, ORACLE_SHUTTLE_SEED, RustOracle
from skelnet.rusttools.dynamic_feedback import pack_sections, run_dynamic
from skelnet.rusttools.runner import ToolRunner
from skelnet.rusttools.seeds import (FEEDBACK_MIRI_SEED_COUNT,
                                     FEEDBACK_MIRI_SEED_DEFAULT_COUNT,
                                     FEEDBACK_MIRI_SEED_START,
                                     FEEDBACK_SHUTTLE_SEED,
                                     feedback_miri_window, feedback_shuttle_seed,
                                     miri_many_seeds_flag)

from round03_helpers import cargo_available, ns, rust_tools

_ABBA = Path(__file__).parent / "fixtures" / "round03" / "abba_2lock" / "rust"
_TERMINAL = "DONE"


def _source_of(cwd: Path) -> str:
    """The probe source. Stress runs with cwd ``<project>/target``."""
    for base in (cwd, *cwd.parents):
        path = base / "src" / "main.rs"
        if path.is_file():
            return path.read_text(encoding="utf-8")
        if base.name in ("tmp", "pytest-of-ubuntu"):
            break
    return ""


def _in_shuttle_project(cwd: Path) -> bool:
    return any(part == "shuttle" for part in cwd.parts[-4:])


def _make_binary(cwd: Path) -> None:
    text = (cwd / "Cargo.toml").read_text(encoding="utf-8") if (cwd / "Cargo.toml").is_file() else ""
    name = "dyn_probe"
    for line in text.splitlines():
        if line.strip().startswith("name"):
            name = line.split("=", 1)[1].strip().strip('"')
            break
    binary = cwd / "target" / "debug" / name
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("", encoding="utf-8")


class MarkerRunner:
    """Outermost subprocess stand-in. Behaviour follows a comment in the source."""

    def __init__(self):
        self.envs: list[dict] = []
        self.argvs: list[list[str]] = []

    def __call__(self, cmd, cwd, timeout, env):
        cmd = [str(c) for c in cmd]
        cwd = Path(cwd)
        self.argvs.append(cmd)
        self.envs.append(dict(env))
        src = _source_of(cwd)
        joined = " ".join(cmd)
        if "clippy" in cmd:
            return ns(0, "", "")
        if "miri" in cmd:
            return self._miri(src)
        if "build" in cmd:
            if "SKELNET_SHUTTLE_UNSUP" in src and _in_shuttle_project(cwd):
                return ns(1, "", "error: shuttle build failed")
            _make_binary(cwd)
            return ns(0, "", "")
        # A built binary.
        if "SKELNET_HANG" in src and not _in_shuttle_project(cwd):
            raise subprocess.TimeoutExpired(cmd, timeout)
        if "SKELNET_WRONG" in src and not _in_shuttle_project(cwd):
            return ns(0, "NOPE\n", "")
        if _in_shuttle_project(cwd) or Path(cmd[0]).name == "shuttle_probe":
            return self._shuttle(src)
        return ns(0, _TERMINAL + "\n", "")

    def _shuttle(self, src: str):
        if "SKELNET_DEADLOCK" in src:
            return ns(1, "",
                      "thread 'main' (4242) panicked at runtime/execution.rs:1:1:\n"
                      "deadlock! blocked tasks: [main, t1, t2]\n"
                      "failing schedule:\n\"\nPCT 1 2 3\n\"\n")
        if "SKELNET_NOCONC" in src:
            return ns(101, "", "test closure did not exercise any concurrency")
        return ns(0, "", "")

    def _miri(self, src: str):
        if "SKELNET_MIRI_UB" in src:
            return ns(1, "", "error: Undefined Behavior: misaligned")
        if "SKELNET_MIRI_LEAK" in src:
            return ns(1, "", "error: the main thread terminated without waiting "
                      "for all remaining threads")
        if "SKELNET_MIRI_UNSUP" in src:
            return ns(1, "", "error: unsupported operation: raw pointer")
        return ns(0, _TERMINAL + "\n", "")


def _run(tmp_path, marker: str, **kwargs):
    source = f"fn main() {{ println!(\"{_TERMINAL}\"); }} // {marker}\n"
    runner = MarkerRunner()
    result = run_dynamic(
        ToolRunner(runner=runner, toolchain="nightly-test"),
        tmp_path, source, terminal=_TERMINAL, stress_runs=2,
        stress_timeout=1.0, shuttle_iterations=10, shuttle_depth=2,
        miri_seed_count=2, timeout=5, **kwargs)
    return result, runner


def test_dynamic_all_pass(tmp_path):
    result, _ = _run(tmp_path, "SKELNET_OK")
    assert result.passed
    assert {s.name: s.category for s in result.slices}["stress"] is None


def test_dynamic_hang(tmp_path):
    result, _ = _run(tmp_path, "SKELNET_HANG")
    stress = next(s for s in result.slices if s.name == "stress")
    assert stress.category == "hang" and stress.blocking
    assert not result.passed


def test_dynamic_wrong_output_names_both_lines(tmp_path):
    result, _ = _run(tmp_path, "SKELNET_WRONG")
    assert "expected last line:" in result.feedback
    assert "NOPE" in result.feedback
    assert _TERMINAL in result.feedback
    assert not result.passed


def test_dynamic_shuttle_deadlock_includes_failure_text(tmp_path):
    result, _ = _run(tmp_path, "SKELNET_DEADLOCK")
    shuttle = next(s for s in result.slices if s.name == "shuttle")
    assert shuttle.category == "deadlock" and shuttle.blocking
    assert "deadlock! blocked tasks" in result.feedback
    assert "(4242)" not in result.feedback
    saved = (tmp_path / "shuttle" / "failure.txt").read_text(encoding="utf-8")
    assert "deadlock! blocked tasks" in saved
    assert "PCT 1 2 3" in result.feedback


def test_dynamic_no_concurrency_passes(tmp_path):
    result, _ = _run(tmp_path, "SKELNET_NOCONC")
    shuttle = next(s for s in result.slices if s.name == "shuttle")
    assert shuttle.category is None or shuttle.status == "pass"
    assert not shuttle.blocking
    assert result.passed
    assert "treated as pass" in result.feedback


def test_dynamic_shuttle_unsupported_does_not_block(tmp_path):
    result, _ = _run(tmp_path, "SKELNET_SHUTTLE_UNSUP")
    shuttle = next(s for s in result.slices if s.name == "shuttle")
    assert shuttle.category == "shuttle_unsupported"
    assert not shuttle.blocking
    assert result.passed
    assert "could not run" in result.feedback


def test_dynamic_miri_ub_and_thread_leak(tmp_path):
    ub, _ = _run(tmp_path / "ub", "SKELNET_MIRI_UB")
    leak, _ = _run(tmp_path / "leak", "SKELNET_MIRI_LEAK")
    assert next(s for s in ub.slices if s.name == "miri").category == "ub"
    assert not ub.passed
    assert next(s for s in leak.slices if s.name == "miri").category == "thread_leak"
    assert not leak.passed


def test_dynamic_miri_unsupported_does_not_block(tmp_path):
    result, _ = _run(tmp_path, "SKELNET_MIRI_UNSUP")
    miri = next(s for s in result.slices if s.name == "miri")
    assert miri.category == "miri_unsupported" and not miri.blocking
    assert result.passed


def test_pack_sections_rolls_unused_budget_forward():
    text, truncated = pack_sections(["aa", "b" * 100], limit_bytes=30)
    assert truncated
    assert text.startswith("aa\n")
    assert text.endswith("[truncated]")
    assert len(text.encode("utf-8")) <= 30


def test_feedback_seeds_flow_through_dynamic_then_oracle(tmp_path):
    """Real tool path: feedback MIRIFLAGS / Shuttle seed, then the oracle's."""
    runner = MarkerRunner()
    tools = ToolRunner(runner=runner, toolchain="nightly-test")
    source = f"fn main() {{ println!(\"{_TERMINAL}\"); }}\n"
    run_dynamic(tools, tmp_path / "feedback", source, terminal=_TERMINAL,
                stress_runs=1, stress_timeout=1.0, shuttle_iterations=4,
                shuttle_depth=1, miri_seed_count=FEEDBACK_MIRI_SEED_DEFAULT_COUNT,
                timeout=5)
    oracle = RustOracle(terminal=_TERMINAL, timeout=5, runner=runner,
                        toolchain="nightly-test", stress_runs=1,
                        stress_timeout=1.0, shuttle_iterations=4, shuttle_depth=1,
                        task_dir=None)
    oracle.evaluate(source, tmp_path / "oracle")
    shuttle_seeds = [env.get("SHUTTLE_RANDOM_SEED") for env in runner.envs
                     if env.get("SHUTTLE_RANDOM_SEED")]
    miri_flags = [env.get("MIRIFLAGS") for env in runner.envs if env.get("MIRIFLAGS")]
    assert shuttle_seeds[0] == str(FEEDBACK_SHUTTLE_SEED)
    assert shuttle_seeds[0] == str(feedback_shuttle_seed())
    assert shuttle_seeds[-1] == str(ORACLE_SHUTTLE_SEED)
    start, count = feedback_miri_window(FEEDBACK_MIRI_SEED_DEFAULT_COUNT)
    assert miri_flags[0] == miri_many_seeds_flag(start, count)
    assert miri_flags[-1] == miri_many_seeds_flag(
        ORACLE_MIRI_SEED_START, 16)
    used = list(range(start, start + count))
    assert all(FEEDBACK_MIRI_SEED_START <= s < FEEDBACK_MIRI_SEED_START + FEEDBACK_MIRI_SEED_COUNT
               for s in used)
    oracle_seeds = set(range(ORACLE_MIRI_SEED_START, ORACLE_MIRI_SEED_START + 16))
    assert oracle_seeds.isdisjoint(used)


def test_dynamic_feedback_relativizes_absolute_paths(tmp_path, monkeypatch):
    """N3: workdir, repo, sysroot, cargo registry, and other absolute paths."""
    import skelnet.rusttools.compile as compile_mod
    from skelnet.backend import repo_root

    sysroot = "/opt/fake-sysroot-n3"
    monkeypatch.setattr(compile_mod, "_sysroot", lambda: sysroot)
    cargo_home = os.environ.get("CARGO_HOME") or str(Path.home() / ".cargo")
    root = str(repo_root())
    work = str(tmp_path)
    registry = (f"{cargo_home}/registry/src/index.crates.io-xxx/"
                "shuttle-0.8.1/src/runtime/execution.rs:203:17")
    unrelated = "/opt/unrelated/data/secret.txt"
    failure = (
        f"thread 'main' panicked at {registry}:\n"
        f"note: built in {work}/src/main.rs\n"
        f"see {root}/runtime/concir_sync/src/lib.rs:1:1\n"
        f"and {sysroot}/lib/rustlib/src/rust/library/std/src/panicking.rs:10:1\n"
        f"leaked {unrelated}\n"
        "deadlock! blocked tasks: [main, t1]\n"
    )

    def run(cmd, cwd, timeout, env):
        cmd = [str(c) for c in cmd]
        cwd = Path(cwd)
        if "build" in cmd:
            _make_binary(cwd)
            return ns(0, "", "")
        if _in_shuttle_project(cwd) or Path(cmd[0]).name == "shuttle_probe":
            return ns(1, "", failure)
        if "miri" in cmd:
            return ns(0, _TERMINAL + "\n", "")
        return ns(0, _TERMINAL + "\n", "")

    result = run_dynamic(
        ToolRunner(runner=run, toolchain="nightly-test"),
        tmp_path, f'fn main() {{ println!("{_TERMINAL}"); }}\n',
        terminal=_TERMINAL, stress_runs=1, stress_timeout=1.0,
        shuttle_iterations=4, shuttle_depth=1, miri_seed_count=1, timeout=5)
    text = result.feedback
    saved = (tmp_path / "shuttle" / "failure.txt").read_text(encoding="utf-8")
    assert registry in saved
    for prefix in (work, root, sysroot, f"{cargo_home}/registry/src/",
                   "/opt/unrelated"):
        assert prefix not in text, prefix
    assert "<cargo>/registry/" in text
    assert "execution.rs:203:17" in text
    assert "<abs>/secret.txt" in text
    assert "<rust>/library/std/src/panicking.rs" in text


def _assert_feedback_has_no_machine_paths(text: str, workdir: Path) -> None:
    from skelnet.backend import repo_root
    cargo_home = os.environ.get("CARGO_HOME") or str(Path.home() / ".cargo")
    for prefix in (str(Path.home()), cargo_home, str(repo_root()), "/usr/",
                   str(workdir)):
        assert prefix not in text, prefix


@rust_tools
def test_real_abba_feedback_paths_are_stable(tmp_path):
    """N3: real Shuttle feedback has no machine paths and does not depend on workdir."""
    if not cargo_available():
        import pytest
        pytest.skip("cargo is not available")
    buggy = (_ABBA / "buggy.rs").read_text(encoding="utf-8")
    tools = ToolRunner()
    kwargs = dict(terminal="DONE t1=1 t2=1", stress_runs=1, stress_timeout=2.0,
                  shuttle_iterations=200, shuttle_depth=3, miri_seed_count=1,
                  timeout=300)
    first = run_dynamic(tools, tmp_path / "one", buggy, **kwargs)
    second = run_dynamic(tools, tmp_path / "two", buggy, **kwargs)
    sections = []
    for result, directory in ((first, tmp_path / "one"), (second, tmp_path / "two")):
        _assert_feedback_has_no_machine_paths(result.feedback, directory)
        shuttle = next(s for s in result.slices if s.name == "shuttle")
        sections.append(shuttle.text)
        assert "<cargo>/registry/" in shuttle.text
        assert "execution.rs:203:17" in shuttle.text
        assert "<abs>/execution.rs" not in shuttle.text
    assert sections[0] == sections[1]


@rust_tools
def test_real_abba_feedback_shuttle_deadlock_and_fixed_passes(tmp_path):
    if not cargo_available():
        import pytest
        pytest.skip("cargo is not available")
    buggy = (_ABBA / "buggy.rs").read_text(encoding="utf-8")
    fixed = (_ABBA / "fixed.rs").read_text(encoding="utf-8")
    tools = ToolRunner()
    # Shuttle-only budget: the full miri window is covered by the oracle suite.
    buggy_result = run_dynamic(
        tools, tmp_path / "buggy", buggy, terminal="DONE t1=1 t2=1",
        stress_runs=1, stress_timeout=2.0, shuttle_iterations=200,
        shuttle_depth=3, miri_seed_count=1, timeout=300)
    shuttle = next(s for s in buggy_result.slices if s.name == "shuttle")
    assert shuttle.category == "deadlock"
    fixed_result = run_dynamic(
        tools, tmp_path / "fixed", fixed, terminal="DONE t1=1 t2=1",
        stress_runs=2, stress_timeout=5.0, shuttle_iterations=50,
        shuttle_depth=3, miri_seed_count=1, timeout=300)
    assert fixed_result.passed, [(s.name, s.status, s.category) for s in fixed_result.slices]
