"""T3: ``oracle.o3_tools`` exposes the O3 Shuttle/miri sub-results."""

import copy
import json
from pathlib import Path

from skelnet.oracle import OracleResult, RustOracle, oracle_result_dict
from skelnet.schema import _validate_o3_tools, validate_cell

from round03_helpers import FakeTools

FIXTURE = Path(__file__).parent / "fixtures" / "round03" / "abba_2lock"
TINY_CELL = (Path(__file__).parent / "fixtures" / "round08" / "tiny" /
             "deepseek" / "g0" / "cells" / "lock-order" / "abba_2lock" /
             "0" / "result.json")


def _evaluate(tmp_path, source, tools):
    oracle = RustOracle(terminal="DONE t1=1 t2=1", runner=tools,
                        task_dir=FIXTURE)
    return oracle_result_dict(oracle.evaluate(source, tmp_path))


def test_o3_tools_no_concurrency(tmp_path):
    result = _evaluate(tmp_path, "fn main() {}", FakeTools(
        shuttle_no_concurrency=True))
    assert result["o3_tools"]["no_concurrency"] is True
    assert result["o3_tools"]["shuttle"]["status"] == "pass"
    assert result["o3_tools"]["miri"]["status"] == "pass"


def test_o3_tools_shuttle_unsupported_miri_decides(tmp_path):
    source = "fn main() { std::thread::scope(|s| { s.spawn(|| {}); }); }"
    result = _evaluate(tmp_path, source, FakeTools())
    assert result["o3_tools"]["shuttle"]["status"] == "unsupported"
    assert result["o3_tools"]["shuttle"]["category"] == "shuttle_unsupported"
    assert result["o3_tools"]["miri"]["status"] == "pass"
    assert result["functional_ok"] is True
    assert result["oracle_complete"] is False


def test_o3_tools_both_pass_and_other_keys_unchanged(tmp_path):
    result = _evaluate(tmp_path, "fn main() {}", FakeTools())
    assert result["o3_tools"] == {
        "shuttle": {"status": "pass", "category": None},
        "miri": {"status": "pass", "category": None},
        "no_concurrency": False,
    }
    without = {key: value for key, value in result.items() if key != "o3_tools"}
    assert set(without) == {
        "built", "ran", "run_ok", "functional_ok", "functional_ok_no_o4",
        "terminal_check", "oracle_complete", "layers"}
    assert without["built"] is True and without["ran"] is True
    assert without["run_ok"] is True and without["functional_ok"] is True
    assert without["functional_ok_no_o4"] is True
    assert without["terminal_check"] == "pass"
    assert without["oracle_complete"] is True
    for name in ("O1", "O2", "O3"):
        assert without["layers"][name]["status"] == "pass"
        assert without["layers"][name]["category"] is None


def test_o3_tools_none_without_o3(tmp_path):
    oracle = RustOracle(terminal=None, layers=("O1",),
                        runner=FakeTools(), task_dir=FIXTURE)
    result = oracle_result_dict(oracle.evaluate("fn main() {}", tmp_path))
    assert result["o3_tools"] is None


def test_o3_tools_none_for_empty_result():
    assert oracle_result_dict(OracleResult())["o3_tools"] is None


def test_schema_validates_o3_tools_types():
    assert _validate_o3_tools(None)  # wrong type on purpose
    assert _validate_o3_tools({"shuttle": {"status": "pass"},
                               "miri": {"status": "pass"},
                               "no_concurrency": False})
    assert _validate_o3_tools({"shuttle": {"status": "pass", "category": None},
                               "miri": {"status": None, "category": None},
                               "no_concurrency": True}) == []
    cell = json.loads(TINY_CELL.read_text(encoding="utf-8"))
    cell["oracle"] = dict(cell["oracle"])
    cell["oracle"]["o3_tools"] = {"shuttle": {"status": "pass", "category": None},
                                  "miri": {"status": "pass", "category": None},
                                  "no_concurrency": False}
    assert validate_cell(cell) == []
    bad = copy.deepcopy(cell)
    bad["oracle"]["o3_tools"] = {"shuttle": {"status": 3, "category": None},
                                 "miri": {"status": "pass", "category": None},
                                 "no_concurrency": False}
    assert validate_cell(bad)
    bad["oracle"]["o3_tools"] = {"shuttle": {"status": "pass", "category": None},
                                 "miri": {"status": "pass", "category": None}}
    assert validate_cell(bad)
