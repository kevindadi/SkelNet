"""M2: the global ledger is enforced and token-accounted on the real path."""

import json

from skelnet import cli
from skelnet.budget import BudgetLedger
from skelnet.models import billable_tokens
from skelnet.oracle import FakeOracle
from skelnet.transport import BudgetExceeded

from _fake_sdk import (RUST, FakeSDK, chat_response, patch_build_client,
                       run_args, sequence_chat_handler, sequence_handler,
                       write_env)


def _args(tmp_path, out, **extra):
    env = write_env(tmp_path, DEEPSEEK_API_KEY="k")
    return run_args("G0", out, model="DeepSeek Flash", env_file=str(env),
                    budget_file=str(tmp_path / "budget.json"), **extra)


def test_ledger_limit_from_file_stops_the_run(tmp_path, monkeypatch):
    (tmp_path / "budget.json").write_text(
        json.dumps({"limits": {"0": {"max_requests": 1}}}), encoding="utf-8")
    sdk = FakeSDK(chat_handler=sequence_chat_handler([RUST] * 3))
    patch_build_client(monkeypatch, sdk)
    out = tmp_path / "run"
    rc = cli.cmd_run(_args(tmp_path, out, reps=3),
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc != 0
    assert len(sdk.chat.completions.calls) == 1
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["status"] == "budget_exhausted"


def test_truncation_retry_counts_in_the_ledger(tmp_path, monkeypatch):
    first_usage = {"prompt_tokens": 10, "completion_tokens": 5,
                   "completion_tokens_details": {"reasoning_tokens": 3}}
    second_usage = {"prompt_tokens": 20, "completion_tokens": 7}
    responses = [
        chat_response("", finish_reason="length", usage=first_usage),
        chat_response(RUST, finish_reason="stop", usage=second_usage),
    ]
    sdk = FakeSDK(chat_handler=sequence_handler(responses))
    patch_build_client(monkeypatch, sdk)
    out = tmp_path / "run"
    rc = cli.cmd_run(_args(tmp_path, out),
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc == 0
    assert len(sdk.chat.completions.calls) == 2
    snapshot = BudgetLedger(tmp_path / "budget.json").snapshot()
    assert snapshot["requests"] == 2
    assert snapshot["input"] == 30
    assert snapshot["output"] == 12
    assert snapshot["reasoning"] == 3
    # Billable tokens are input + output (reasoning is already inside output).
    assert billable_tokens(snapshot) == 42


def test_budget_exceeded_from_sdk_stops_the_run(tmp_path, monkeypatch):
    def handler(_kwargs):
        raise BudgetExceeded("stage 0: request budget exhausted")
    sdk = FakeSDK(chat_handler=handler)
    patch_build_client(monkeypatch, sdk)
    out = tmp_path / "run"
    rc = cli.cmd_run(_args(tmp_path, out, reps=2),
                     oracle_factory=lambda t, term: FakeOracle(True))
    assert rc != 0
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["status"] == "budget_exhausted"
    for path in (out / "cells").rglob("result.json"):
        assert json.loads(path.read_text())["error"] != "BudgetExceeded"
