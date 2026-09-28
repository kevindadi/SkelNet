"""T6: layer composition and the real default oracle path."""

import json
from pathlib import Path

from skelnet import cli
from skelnet.oracle import (_combine_o3, _complete, _conjunction, RustOracle)
from skelnet.rusttools.base import FAIL, PASS, UNAVAILABLE, UNSUPPORTED, LayerResult

from round03_helpers import FakeTools


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
