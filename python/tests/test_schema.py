"""D1: the frozen cell schema validates real runs and rejects bad layers."""

import json

from skelnet import cli
from skelnet.oracle import FakeOracle
from skelnet.schema import validate_cell

from _fake_sdk import RUST, ScriptedTransportClient, run_args


def _valid_cell():
    return {
        "schema_version": "skelnet-cell-v1", "arm": "G0", "model": "m",
        "model_id": "m1", "task": "t", "tier": None, "hint": "h0", "rep": 0,
        "seed": 1, "status": "ok", "skip_reason": None, "error": None,
        "accepted": False, "parse_ok": True, "check_ok": True, "rounds_used": 1,
        "history": [], "ledger": {}, "evidence_sufficient": False,
        "rust_mode": "llm",
        "calls": [{"attempt": 1, "stage": "generate", "system_sha256": "a",
                   "request_sha256": "b", "cache_hit": False,
                   "transport_attempt": 1, "truncation_retry": False,
                   "finish_reason": "stop", "finish_reasons": ["stop"],
                   "usage": {"input": 1, "output": 2, "reasoning": None,
                             "cached": None}, "wall_ms": 5}],
        "budget_used": {"calls": 1, "tokens": 3},
        "oracle": {"built": True, "ran": True, "run_ok": True,
                   "functional_ok": True, "terminal_check": "pass"},
    }


def test_valid_cell_passes():
    assert validate_cell(_valid_cell()) == []


def test_bad_layer_status_and_key_fail():
    cell = _valid_cell()
    cell["oracle"]["layers"] = {"O1": {"status": "bogus", "category": None,
                                       "detail": None, "wall_ms": None}}
    assert validate_cell(cell)

    cell2 = _valid_cell()
    cell2["oracle"]["layers"] = {"O9": {"status": "pass", "category": None,
                                        "detail": None, "wall_ms": None}}
    assert validate_cell(cell2)


def test_valid_layers_pass():
    cell = _valid_cell()
    cell["oracle"]["layers"] = {
        "O1": {"status": "pass", "category": None, "detail": None, "wall_ms": 12},
        "O4": {"status": "unavailable", "category": "no-monitor", "detail": "x",
               "wall_ms": None},
    }
    assert validate_cell(cell) == []


def test_cmd_run_cells_validate(tmp_path):
    out = tmp_path / "run"
    args = run_args("G0", out)
    rc = cli.cmd_run(args, client_factory=lambda spec, o: ScriptedTransportClient([RUST]),
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    for path in (out / "cells").rglob("result.json"):
        assert validate_cell(json.loads(path.read_text())) == []
