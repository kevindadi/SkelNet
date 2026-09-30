"""T1: guards that previously had no failing test on revert."""

import pytest

from skelnet import cli
from skelnet.direct import DirectChatClient
from skelnet.opencode_go import OpenCodeGoResponsesClient
from skelnet.oracle import FakeOracle
from skelnet.params import RunParams, seed_for

from _fake_sdk import (APIConnectionError, RUST, FakeSDK, chat_response,
                       patch_build_client, responses_response, run_args,
                       sequence_chat_handler, sequence_responses_handler,
                       write_env)


class _Budget:
    def reserve(self):
        return None


def _params():
    return RunParams()


# ── A4: retries for Direct and Responses ─────────────────────────────
def test_direct_retry_attempts(tmp_path):
    state = {"n": 0}

    def handler(_k):
        state["n"] += 1
        if state["n"] <= 2:
            raise APIConnectionError("boom")
        return chat_response("OK")
    sdk = FakeSDK(chat_handler=handler)
    client = DirectChatClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(), sdk_client=sdk,
                              sleep=lambda _s: None)
    outcome = client.complete("s", "u")
    assert outcome.transport_attempt == 3
    assert len(sdk.chat.completions.calls) == 3


def test_responses_retry_attempts(tmp_path):
    state = {"n": 0}

    def handler(_k):
        state["n"] += 1
        if state["n"] <= 2:
            raise APIConnectionError("boom")
        return responses_response("OK")
    sdk = FakeSDK(responses_handler=handler)
    client = OpenCodeGoResponsesClient(api_key="x", base_url="http://x", model="m",
                                       budget=_Budget(), evidence_dir=tmp_path,
                                       params=_params(), sdk_client=sdk,
                                       sleep=lambda _s: None)
    outcome = client.complete("s", "u")
    assert outcome.transport_attempt == 3
    assert len(sdk.responses.calls) == 3


def test_direct_non_retryable_once(tmp_path):
    sdk = FakeSDK(chat_handler=lambda _k: (_ for _ in ()).throw(ValueError("nope")))
    client = DirectChatClient(api_key="x", base_url="http://x", model="m",
                              budget=_Budget(), evidence_dir=tmp_path,
                              params=_params(), sdk_client=sdk,
                              sleep=lambda _s: None)
    with pytest.raises(ValueError):
        client.complete("s", "u")
    assert len(sdk.chat.completions.calls) == 1


def test_responses_non_retryable_once(tmp_path):
    sdk = FakeSDK(responses_handler=lambda _k: (_ for _ in ()).throw(ValueError("nope")))
    client = OpenCodeGoResponsesClient(api_key="x", base_url="http://x", model="m",
                                       budget=_Budget(), evidence_dir=tmp_path,
                                       params=_params(), sdk_client=sdk,
                                       sleep=lambda _s: None)
    with pytest.raises(ValueError):
        client.complete("s", "u")
    assert len(sdk.responses.calls) == 1


# ── B1: seeds on the real path ───────────────────────────────────────
def test_seed_sent_per_cell_real_path(tmp_path, monkeypatch):
    sdk = FakeSDK(chat_handler=sequence_chat_handler([RUST, RUST]))
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, DEEPSEEK_API_KEY="k")
    out = tmp_path / "run"
    args = run_args("G0", out, reps=2, model="DeepSeek Flash", env_file=str(env),
                    budget_file=str(tmp_path / "budget.json"))
    assert cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    seeds = [call["seed"] for call in sdk.chat.completions.calls]
    assert seeds == [seed_for("lock-order/abba_2lock", 0),
                     seed_for("lock-order/abba_2lock", 1)]

    # Responses never send a seed.
    gpt_sdk = FakeSDK(responses_handler=sequence_responses_handler([RUST, RUST]))
    patch_build_client(monkeypatch, gpt_sdk)
    env2 = write_env(tmp_path, OPENCODE_API_KEY="k")
    out2 = tmp_path / "run_gpt"
    args2 = run_args("G0", out2, reps=2, model="GPT 6 Luna", env_file=str(env2),
                     budget_file=str(tmp_path / "budget.json"))
    assert cli.cmd_run(args2, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    assert all("seed" not in call for call in gpt_sdk.responses.calls)


# ── B5: resume rejects changed RunParams ─────────────────────────────
def _g0(tmp_path, **extra):
    env = write_env(tmp_path, DEEPSEEK_API_KEY="k")
    return run_args("G0", tmp_path / "run", model="DeepSeek Flash",
                    env_file=str(env), budget_file=str(tmp_path / "budget.json"),
                    **extra)


def test_resume_rejects_changed_call_budget(tmp_path):
    from _fake_sdk import ScriptedTransportClient
    assert cli.cmd_run(_g0(tmp_path), client_factory=lambda s, o: ScriptedTransportClient([RUST]),
                       oracle_factory=lambda t, term: FakeOracle(True)) == 0
    with pytest.raises(SystemExit):
        cli.cmd_run(_g0(tmp_path, resume=True, call_budget=9),
                    client_factory=lambda s, o: ScriptedTransportClient([RUST]),
                    oracle_factory=lambda t, term: FakeOracle(True))


def test_resume_rejects_changed_hint(tmp_path):
    from _fake_sdk import ScriptedTransportClient
    assert cli.cmd_run(_g0(tmp_path), client_factory=lambda s, o: ScriptedTransportClient([RUST]),
                       oracle_factory=lambda t, term: FakeOracle(True)) == 0
    with pytest.raises(SystemExit):
        cli.cmd_run(_g0(tmp_path, resume=True, hint="h0"),
                    client_factory=lambda s, o: ScriptedTransportClient([RUST]),
                    oracle_factory=lambda t, term: FakeOracle(True))
