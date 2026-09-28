"""T6 (round 3b): layer composition, dependencies and the real default path."""

import json
from pathlib import Path

from skelnet import cli
from skelnet.oracle import (_combine_o3, _complete, _conjunction, RustOracle)
from skelnet.rusttools.base import FAIL, PASS, UNAVAILABLE, UNSUPPORTED, LayerResult
from skelnet.rusttools.seeds import (ORACLE_MIRI_SEED_COUNT, ORACLE_MIRI_SEED_START,
                                     ORACLE_SHUTTLE_SEED, miri_many_seeds_flag)

from round03_helpers import FakeTools

FIXTURE = Path(__file__).parent / "fixtures" / "round03" / "abba_2lock"


def _layer(name, status, category=None):
    return LayerResult(name, status, category)


def test_conjunction_skips_unsupported_and_not_run():
    layers = {"O1": _layer("O1", PASS), "O2": _layer("O2", PASS),
              "O3": _layer("O3", UNSUPPORTED), "O4": _layer("O4", PASS)}
    assert _conjunction(layers, ("O1", "O2", "O3", "O4")) is True


def test_unavailable_makes_conjunction_null():
    layers = {"O1": _layer("O1", PASS), "O2": _layer("O2", UNAVAILABLE)}
    assert _conjunction(layers, ("O1", "O2")) is None


def test_fail_makes_conjunction_false():
    layers = {"O1": _layer("O1", PASS), "O2": _layer("O2", FAIL)}
    assert _conjunction(layers, ("O1", "O2")) is False


def test_complete_requires_every_layer_to_decide():
    layers = {"O1": _layer("O1", PASS), "O2": _layer("O2", PASS),
              "O3": _layer("O3", UNSUPPORTED), "O4": _layer("O4", PASS)}
    assert _complete(layers) is False
    layers["O3"] = _layer("O3", PASS)
    assert _complete(layers) is True


def test_o3_shuttle_unsupported_uses_miri():
    shuttle = LayerResult("O3", UNSUPPORTED, "shuttle_unsupported")
    miri = LayerResult("O3", PASS)
    combined = _combine_o3(shuttle, miri)
    assert combined.status == "pass"
    assert combined.category == "shuttle_unsupported"
    assert combined.data["complete"] is False


def test_o3_both_unavailable():
    combined = _combine_o3(LayerResult("O3", UNAVAILABLE),
                           LayerResult("O3", UNAVAILABLE))
    assert combined.status == "unavailable"


def test_o3_shuttle_deadlock_wins():
    combined = _combine_o3(LayerResult("O3", FAIL, "deadlock"),
                           LayerResult("O3", PASS))
    assert combined.status == "fail" and combined.category == "deadlock"


def test_o3_shuttle_unsupported_and_miri_fail():
    combined = _combine_o3(LayerResult("O3", UNSUPPORTED, "shuttle_unsupported"),
                           LayerResult("O3", FAIL, "ub", "boom"))
    assert combined.status == "fail"
    assert combined.category == "ub"


def test_o3_both_unsupported():
    combined = _combine_o3(LayerResult("O3", UNSUPPORTED, "shuttle_unsupported"),
                           LayerResult("O3", UNSUPPORTED, "miri_unsupported"))
    assert combined.status == "unsupported"
    assert combined.data["complete"] is False


def test_o2_hang_skips_o4(tmp_path):
    tools = FakeTools(o2_hang=True)
    oracle = RustOracle(terminal="DONE t1=1 t2=1", runner=tools, task_dir=FIXTURE)
    result = oracle.evaluate("fn main() {}", tmp_path)
    assert result.layers["O2"].category == "hang"
    assert result.layers["O4"].status == "not_run"
    assert result.layers["O4"].detail == "O2 hang"
    names = [Path(c[0]).name for c in tools.calls]
    assert "concir-instrument" not in names
    assert "concir-backend" not in names


def test_o2_wrong_output_still_runs_o4(tmp_path):
    tools = FakeTools(o2_stdout="wrong\n")
    oracle = RustOracle(terminal="DONE t1=1 t2=1", runner=tools, task_dir=FIXTURE)
    result = oracle.evaluate("fn main() {}", tmp_path)
    assert result.layers["O2"].category == "wrong_output"
    assert result.layers["O4"].status != "not_run"
    assert any(Path(c[0]).name == "concir-instrument" for c in tools.calls)


def test_shuttle_and_miri_env(tmp_path):
    tools = FakeTools()
    oracle = RustOracle(terminal="DONE t1=1 t2=1", runner=tools, task_dir=FIXTURE)
    oracle.evaluate("fn main() {}", tmp_path)
    shuttle_env = next(env for cmd, env in zip(tools.calls, tools.envs)
                       if Path(cmd[0]).name.endswith("shuttle_probe"))
    assert shuttle_env["SHUTTLE_RANDOM_SEED"] == str(ORACLE_SHUTTLE_SEED)
    miri_env = next(env for cmd, env in zip(tools.calls, tools.envs)
                    if "miri" in cmd)
    assert miri_env["MIRIFLAGS"] == miri_many_seeds_flag(
        ORACLE_MIRI_SEED_START, ORACLE_MIRI_SEED_COUNT)


def test_cleanup_removes_targets_unless_keep(tmp_path, monkeypatch):
    tools = FakeTools()
    oracle = RustOracle(terminal="DONE t1=1 t2=1", runner=tools, task_dir=FIXTURE)
    workdir = tmp_path / "cell"
    oracle.evaluate("fn main() {}", workdir)
    assert not (workdir / "target").exists()
    assert not (workdir / "shuttle" / "target").exists()
    assert not (workdir / "o4" / "project" / "target").exists()

    monkeypatch.setenv("SKELNET_KEEP_TARGET", "1")
    tools2 = FakeTools()
    oracle2 = RustOracle(terminal="DONE t1=1 t2=1", runner=tools2, task_dir=FIXTURE)
    workdir2 = tmp_path / "cell_keep"
    oracle2.evaluate("fn main() {}", workdir2)
    assert (workdir2 / "target").exists()
    assert (workdir2 / "shuttle" / "target").exists()
    assert (workdir2 / "o4" / "project" / "target").exists()


def test_o1_failure_marks_rest_not_run(tmp_path):
    result = RustOracle(terminal=None,
                        runner=FakeTools(build_ok=False)).evaluate("fn main() {}", tmp_path)
    assert result.layers["O1"].category == "no_build"
    for name in ("O2", "O3", "O4"):
        assert result.layers[name].status == "not_run"


def test_default_path_records_four_layers(tmp_path):
    out = tmp_path / "run"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "lock-order/abba_2lock", "--reps", "1",
        "--rounds", "1", "--out", str(out)])
    tools = FakeTools()
    from test_run_cli import RecordingClient, RUST
    rc = cli.cmd_run(args, client_factory=lambda spec, o: RecordingClient([RUST]),
                     oracle_runner=tools)
    assert rc == 0
    result = json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())
    oracle = result["oracle"]
    assert set(oracle["layers"]) == {"O1", "O2", "O3", "O4"}
    assert oracle["functional_ok"] is True
    assert oracle["oracle_complete"] is True
    # The default factory must pass the task directory to O4.
    monitor = [c for c in tools.calls if Path(c[0]).name == "concir-backend"]
    assert monitor, tools.calls
    contract = monitor[0][monitor[0].index("--contract") + 1]
    assert contract.endswith("lock-order/abba_2lock/contract.json")


def test_cmd_eval_records_four_layers(tmp_path):
    out = tmp_path / "run_eval"
    args = cli.build_parser().parse_args([
        "run", "--arm", "G0", "--tasks", "lock-order/abba_2lock", "--reps", "1",
        "--rounds", "1", "--out", str(out)])
    from test_run_cli import RecordingClient, RUST
    assert cli.cmd_run(args, client_factory=lambda spec, o: RecordingClient([RUST]),
                       oracle_runner=FakeTools()) == 0
    rc = cli.cmd_eval(cli.build_parser().parse_args(["eval", str(out)]),
                      runner=FakeTools())
    assert rc == 0
    result = json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())
    assert set(result["oracle"]["layers"]) == {"O1", "O2", "O3", "O4"}
