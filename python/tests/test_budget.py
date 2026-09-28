"""B2/B3: global ledger and per-cell budgets."""

import json

import pytest

from skelnet import cli
from skelnet.budget import BudgetLedger
from skelnet.oracle import FakeOracle
from skelnet.transport import BudgetExceeded

from _fake_sdk import BUGGY, BUGGY2, FIXED, RUST, ScriptedTransportClient, run_args


def test_ledger_persists_across_instances(tmp_path):
    path = tmp_path / "budget.json"
    first = BudgetLedger(path, stage=0)
    first.reserve()
    first.add_tokens({"input": 10, "output": 5, "reasoning": 2})
    second = BudgetLedger(path, stage=0)
    assert second.snapshot() == {"requests": 1, "input": 10, "output": 5,
                                 "reasoning": 2}
    second.reserve()
    assert BudgetLedger(path, stage=0).snapshot()["requests"] == 2


def test_ledger_limits_stop_further_requests(tmp_path):
    ledger = BudgetLedger(tmp_path / "b.json", stage=0,
                          limits={"0": {"max_requests": 1}})
    ledger.reserve()
    with pytest.raises(BudgetExceeded):
        ledger.reserve()


def test_ledger_counts_stages_separately(tmp_path):
    path = tmp_path / "b.json"
    BudgetLedger(path, stage=0).reserve()
    BudgetLedger(path, stage=1).reserve()
    BudgetLedger(path, stage=1).reserve()
    assert BudgetLedger(path, stage=0).snapshot()["requests"] == 1
    assert BudgetLedger(path, stage=1).snapshot()["requests"] == 2


def _run_skel(tmp_path, client, **extra):
    out = tmp_path / "run"
    args = run_args("SKEL", out, rounds=3, **extra)
    rc = cli.cmd_run(args, client_factory=lambda spec, o: client,
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    return json.loads((out / "cells" / "lock-order" / "abba_2lock" / "0"
                       / "result.json").read_text())


def test_cell_call_budget(tmp_path):
    # With B=2 the skeleton stage gets min(rounds, B-1)=1 call and the Rust
    # stage the remaining 1; the cell uses exactly the budget (no provider
    # exhaustion error is raised).
    client = ScriptedTransportClient([BUGGY, BUGGY2, FIXED, RUST])
    result = _run_skel(tmp_path, client, call_budget=2)
    assert result["budget_used"]["calls"] == 2
    assert result["rust_calls"] == 1


def test_cell_token_budget(tmp_path):
    client = ScriptedTransportClient([BUGGY, BUGGY2, FIXED, RUST],
                                     usage={"prompt_tokens": 100})
    result = _run_skel(tmp_path, client, call_budget=5, token_budget=150)
    assert result["error"] == "cell_budget_exhausted"
    assert result["budget_used"]["calls"] == 2
