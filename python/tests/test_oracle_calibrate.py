"""T8: the calibration CLI and the fixture end-to-end (fake + real tools)."""

import json
from pathlib import Path

from skelnet import cli
from skelnet.oracle import RustOracle
from skelnet.oracle_cli import cmd_calibrate
from skelnet.rusttools.mutants import generate_mutants

from round03_helpers import FakeTools, rust_tools

FIXTURE = Path(__file__).parent / "fixtures" / "round03"


def _args(tmp_path, *extra):
    argv = ["oracle", "calibrate", "--fixtures", str(FIXTURE),
            "--out", str(tmp_path / "cal"), *extra]
    return cli.build_parser().parse_args(argv)


def test_calibrate_reports_structure_and_exit_code(tmp_path):
    args = _args(tmp_path, "--mutants")
    rc = cmd_calibrate(args, runner=FakeTools())
    document = json.loads((tmp_path / "cal" / "CALIBRATION.json").read_text())
    assert document["summary"]["total"] >= 2
    # Fixed matches; buggy is expected to fail O3 but the fake passes it.
    assert document["summary"]["mismatched"] >= 1
    assert rc == 1
    assert (tmp_path / "cal" / "CALIBRATION.md").read_text().startswith("# Oracle calibration")


def test_calibrate_report_only_exits_zero(tmp_path):
    args = _args(tmp_path, "--report-only")
    assert cmd_calibrate(args, runner=FakeTools()) == 0


@rust_tools
def test_fixture_fixed_passes_all_layers(tmp_path):
    fixed = (FIXTURE / "abba_2lock" / "rust" / "fixed.rs").read_text(encoding="utf-8")
    terminal = cli.read_terminal(FIXTURE / "abba_2lock")
    oracle = RustOracle(terminal=terminal, task_dir=FIXTURE / "abba_2lock",
                        stress_runs=2, monitor_runs=1)
    result = oracle.evaluate(fixed, tmp_path / "fixed")
    assert result.functional_ok is True, {n: l.to_dict() for n, l in result.layers.items()}
    assert all(result.layers[n].status == "pass" for n in ("O1", "O2", "O3", "O4"))


@rust_tools
def test_fixture_buggy_deadlock_in_o3(tmp_path):
    buggy = (FIXTURE / "abba_2lock" / "rust" / "buggy.rs").read_text(encoding="utf-8")
    terminal = cli.read_terminal(FIXTURE / "abba_2lock")
    oracle = RustOracle(terminal=terminal, task_dir=FIXTURE / "abba_2lock",
                        stress_runs=1, stress_timeout=5.0, monitor_runs=1)
    result = oracle.evaluate(buggy, tmp_path / "buggy")
    assert result.layers["O3"].status == "fail"
    assert result.layers["O3"].category == "deadlock"


@rust_tools
def test_fixture_mutants_fail(tmp_path):
    fixed = (FIXTURE / "abba_2lock" / "rust" / "fixed.rs").read_text(encoding="utf-8")
    terminal = cli.read_terminal(FIXTURE / "abba_2lock")
    mutants = generate_mutants(fixed, terminal=terminal)
    for name, spec in mutants.items():
        assert spec["source"] is not None, name
        oracle = RustOracle(terminal=terminal, task_dir=FIXTURE / "abba_2lock",
                            stress_runs=2, monitor_runs=1)
        result = oracle.evaluate(spec["source"], tmp_path / name)
        assert result.functional_ok is False, name
