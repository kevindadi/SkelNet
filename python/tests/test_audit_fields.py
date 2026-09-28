"""M6: audit events carry cache/temperature/truncation fields."""

import json

from skelnet import cli
from skelnet.budget import BudgetLedger
from skelnet.oracle import FakeOracle

from _fake_sdk import (BUGGY, FIXED, RUST, FakeSDK, patch_build_client,
                       run_args, sequence_chat_handler, write_env)


def _events(out):
    return [json.loads(line) for line in
            (out / "audit.jsonl").read_text().splitlines() if line.strip()]


def test_audit_fields_and_replay(tmp_path, monkeypatch):
    sdk = FakeSDK(chat_handler=sequence_chat_handler([BUGGY, BUGGY, FIXED, RUST]))
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, DEEPSEEK_API_KEY="k")
    budget = tmp_path / "budget.json"
    out = tmp_path / "run"
    args = run_args("SKEL", out, rounds=4, model="DeepSeek Flash",
                    env_file=str(env), budget_file=str(budget))
    assert cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True)) == 0

    events = _events(out)
    requests = BudgetLedger(budget).snapshot()["requests"]
    assert sum(1 for e in events if e["cache_hit"] is False) == requests
    for event in events:
        assert event["temperature_policy"] == "provider_default"
        assert event["temperature_sent"] is None
        assert "truncation_retry" in event
        assert "finish_reasons" in event

    # Replay: every event is a cache hit.
    replay_sdk = FakeSDK(chat_handler=lambda k: (_ for _ in ()).throw(
        AssertionError("network during replay")))
    patch_build_client(monkeypatch, replay_sdk)
    out2 = tmp_path / "replay"
    args2 = run_args("SKEL", out2, rounds=4, model="DeepSeek Flash",
                     env_file=str(env), budget_file=str(budget),
                     replay_from=str(out))
    assert cli.cmd_run(args2, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    replay_events = _events(out2)
    assert replay_events
    assert all(e["cache_hit"] is True for e in replay_events)


def test_audit_temperature_sent_fixed(tmp_path, monkeypatch):
    sdk = FakeSDK(chat_handler=sequence_chat_handler([RUST]))
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, DEEPSEEK_API_KEY="k")
    out = tmp_path / "run_fixed"
    args = run_args("G0", out, model="DeepSeek Flash", env_file=str(env),
                    budget_file=str(tmp_path / "budget.json"),
                    temperature_policy="fixed", temperature=0.3)
    assert cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    events = _events(out)
    assert events and all(e["temperature_sent"] == 0.3 for e in events)
