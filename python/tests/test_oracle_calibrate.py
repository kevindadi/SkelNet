"""T8 (round 3b): the calibration CLI and the fixture end-to-end (fake + real)."""

import json
from pathlib import Path

from skelnet import cli
from skelnet.oracle import OracleResult, RustOracle
from skelnet.oracle_cli import _first_fail_layer, _matches, cmd_calibrate
from skelnet.rusttools.base import FAIL, NOT_RUN, PASS, LayerResult
from skelnet.rusttools.mutants import generate_mutants

from round03_helpers import FakeTools, rust_tools

FIXTURE = Path(__file__).parent / "fixtures" / "round03"


def _args(tmp_path, *extra):
    argv = ["oracle", "calibrate", "--fixtures", str(FIXTURE),
            "--out", str(tmp_path / "cal"), *extra]
    return cli.build_parser().parse_args(argv)


def _document(tmp_path):
    return json.loads((tmp_path / "cal" / "CALIBRATION.json").read_text())


def _program(document, name):
    for task in document["tasks"]:
        for program in task["programs"]:
            if program["program"] == name:
                return program
    raise KeyError(name)


def test_calibrate_reports_structure_and_exit_code(tmp_path):
    args = _args(tmp_path, "--mutants")
    rc = cmd_calibrate(args, runner=FakeTools())
    document = _document(tmp_path)
    assert document["summary"]["total"] >= 2
    assert document["summary"]["mismatched"] >= 1
    assert rc == 1
    assert (tmp_path / "cal" / "CALIBRATION.md").read_text().startswith("# Oracle calibration")


def test_calibrate_report_only_exits_zero(tmp_path):
    args = _args(tmp_path, "--report-only")
    assert cmd_calibrate(args, runner=FakeTools()) == 0


def test_calibration_records_first_fail_layer(tmp_path):
    cmd_calibrate(_args(tmp_path, "--mutants"), runner=FakeTools())
    document = _document(tmp_path)
    for task in document["tasks"]:
        for program in task["programs"]:
            assert "first_fail_layer" in program
    markdown = (tmp_path / "cal" / "CALIBRATION.md").read_text()
    assert "first_fail" in markdown


def test_calibrate_passes_terminal_to_o2(tmp_path):
    cmd_calibrate(_args(tmp_path, "--report-only"),
                  runner=FakeTools(o2_stdout="DONE t1=1 t2=1\n"))
    fixed = _program(_document(tmp_path), "fixed.rs")
    assert fixed["layers"]["O2"]["status"] == "pass"


def test_calibrate_flags_passing_mutants_as_mismatch(tmp_path):
    cmd_calibrate(_args(tmp_path, "--mutants"), runner=FakeTools())
    document = _document(tmp_path)
    mutants = [p for task in document["tasks"] for p in task["programs"]
               if p["program"].startswith("mutant:")]
    assert len(mutants) == 3
    for program in mutants:
        assert program["expect"]["functional"] is False
        assert program["matched"] is False


def test_first_fail_layer_helper():
    result = OracleResult(layers={
        "O1": LayerResult("O1", PASS), "O2": LayerResult("O2", FAIL, "hang"),
        "O3": LayerResult("O3", PASS), "O4": LayerResult("O4", NOT_RUN)})
    assert _first_fail_layer(result) == "O2"
    assert _first_fail_layer(OracleResult(layers={})) is None


def test_matches_semantics():
    result = OracleResult(functional_ok=False, layers={
        "O2": LayerResult("O2", FAIL, "hang"),
        "O3": LayerResult("O3", FAIL, "deadlock")})
    # The expected layer need not be the first to fail.
    assert _matches(result, {"functional": False, "layer": "O3",
                             "category": "deadlock"}) is True
    assert _matches(result, {"functional": False, "layer": "O2",
                             "category": "deadlock"}) is False
    assert _matches(result, {"functional": False, "layer": "O1"}) is False
    assert _matches(result, {"functional": True}) is False


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
                        stress_runs=20, stress_timeout=5.0, monitor_runs=1)
    result = oracle.evaluate(buggy, tmp_path / "buggy")
    assert result.layers["O3"].status == "fail"
    assert result.layers["O3"].category == "deadlock"
    # If O2 observed the hang, O4 must be skipped; first_fail_layer is then O2.
    if result.layers["O2"].category in ("hang", "crash"):
        assert result.layers["O4"].status == "not_run"
        assert _first_fail_layer(result) == "O2"


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
        assert result.oracle_complete is True, name
        assert result.layers["O4"].category == "design_loss", name


@rust_tools
def test_fixture_scope_and_push_are_instrument_unsupported(tmp_path):
    terminal = cli.read_terminal(FIXTURE / "abba_2lock")
    for name in ("scope.rs", "push_spawn.rs"):
        source = (FIXTURE / "abba_2lock" / "rust" / name).read_text(encoding="utf-8")
        oracle = RustOracle(terminal=terminal, task_dir=FIXTURE / "abba_2lock",
                            stress_runs=2, monitor_runs=1)
        result = oracle.evaluate(source, tmp_path / name)
        assert result.layers["O4"].status == "unsupported", name
        assert result.layers["O4"].category == "instrument_unsupported", name
        assert result.functional_ok is True, name
        assert result.oracle_complete is False, name


@rust_tools
def test_fixture_channel_passes(tmp_path):
    source = (FIXTURE / "abba_2lock" / "rust" / "fixed_channel.rs").read_text(encoding="utf-8")
    terminal = cli.read_terminal(FIXTURE / "abba_2lock")
    oracle = RustOracle(terminal=terminal, task_dir=FIXTURE / "abba_2lock",
                        stress_runs=2, monitor_runs=1)
    result = oracle.evaluate(source, tmp_path / "channel")
    assert result.functional_ok is True, {n: l.to_dict() for n, l in result.layers.items()}


@rust_tools
def test_panic_words_program_passes_o3(tmp_path):
    source = (FIXTURE / "abba_2lock" / "rust" / "panic_words.rs").read_text(encoding="utf-8")
    oracle = RustOracle(terminal="DONE panic-free deadlock-free",
                        task_dir=FIXTURE / "abba_2lock", stress_runs=2, monitor_runs=1)
    result = oracle.evaluate(source, tmp_path / "panic_words")
    assert result.layers["O3"].status == "pass", result.layers["O3"].to_dict()
