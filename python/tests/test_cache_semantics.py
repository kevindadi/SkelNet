"""M1/M5: cache identity (task/rep/call_index) and replay semantics."""

import json

import pytest

from skelnet import cli
from skelnet.cache import CachedClient, ResponseCache
from skelnet.oracle import FakeOracle
from skelnet.params import RunParams, seed_for
from skelnet.transport import ReplayMiss

from _fake_sdk import (BUGGY, FIXED, RUST, FakeSDK, TransportOutcome,
                       patch_build_client, run_args, sequence_chat_handler,
                       sequence_responses_handler, write_env)


class _Inner:
    def __init__(self, text="reply"):
        self.text = text
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return TransportOutcome(self.text)


def _cells(out):
    for path in sorted((out / "cells").rglob("result.json")):
        yield json.loads(path.read_text())


def test_cache_key_includes_rep_gpt_and_qwen(tmp_path, monkeypatch):
    # GPT (Responses): 3 reps must be 3 real requests.
    gpt_sdk = FakeSDK(responses_handler=sequence_responses_handler([RUST] * 3))
    patch_build_client(monkeypatch, gpt_sdk)
    env = write_env(tmp_path, OPENCODE_API_KEY="k")
    out = tmp_path / "gpt"
    args = run_args("G0", out, reps=3, model="GPT 6 Luna", env_file=str(env),
                    budget_file=str(tmp_path / "budget.json"))
    assert cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    assert len(gpt_sdk.responses.calls) == 3
    cells = list(_cells(out))
    assert len(cells) == 3
    for cell in cells:
        assert cell["calls"][0]["cache_hit"] is False

    # Qwen (Chat): same.
    qwen_sdk = FakeSDK(chat_handler=sequence_chat_handler([RUST] * 3))
    patch_build_client(monkeypatch, qwen_sdk)
    env2 = write_env(tmp_path, DASHSCOPE_API_KEY="k")
    out2 = tmp_path / "qwen"
    args2 = run_args("G0", out2, reps=3, model="Qwen", env_file=str(env2),
                     budget_file=str(tmp_path / "budget.json"))
    assert cli.cmd_run(args2, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    assert len(qwen_sdk.chat.completions.calls) == 3
    for cell in _cells(out2):
        assert cell["calls"][0]["cache_hit"] is False


def _run_skel(tmp_path, monkeypatch, responses, *, name="run", **extra):
    sdk = FakeSDK(chat_handler=sequence_chat_handler(responses))
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, DEEPSEEK_API_KEY="k")
    out = tmp_path / name
    args = run_args("SKEL", out, rounds=4, model="DeepSeek Flash",
                    env_file=str(env), budget_file=str(tmp_path / "budget.json"),
                    **extra)
    rc = cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True))
    return out, sdk, rc


def test_revision_loop_is_not_stuck_by_cache(tmp_path, monkeypatch):
    out, sdk, rc = _run_skel(tmp_path, monkeypatch, [BUGGY, BUGGY, FIXED, RUST])
    assert rc == 0
    assert len(sdk.chat.completions.calls) == 4
    cell = next(_cells(out))
    assert cell["accepted"] is True
    assert all(call["cache_hit"] is False for call in cell["calls"])
    assert cell["calls"][-1]["stage"] == "rust"
    assert (out / "cells" / "lock-order" / "abba_2lock" / "0"
            / "candidate.rs").exists()


def test_cross_arm_sharing_only_for_identical_first_round(tmp_path):
    cache = ResponseCache(tmp_path / "shared")
    params = RunParams()

    first = CachedClient(_Inner("one"), cache=cache, replay=None, model_id="m",
                         params=params)
    first.set_cell("task", 0)
    assert first.complete("s", "u1").text == "one"   # call_index 1, miss
    assert first.complete("s", "u2").text == "one"   # call_index 2, miss

    inner2 = _Inner("two")
    second = CachedClient(inner2, cache=cache, replay=None, model_id="m",
                          params=params)
    second.set_cell("task", 0)
    assert second.complete("s", "u1").text == "one"  # call_index 1, hit
    assert inner2.calls == 0
    assert second.complete("s", "u1").text == "two"  # call_index 2, miss
    assert inner2.calls == 1


def test_replay_from_run_directory_and_rep_miss(tmp_path, monkeypatch):
    out, _sdk, rc = _run_skel(tmp_path, monkeypatch, [BUGGY, BUGGY, FIXED, RUST])
    assert rc == 0

    # Replay the *run directory*; the fake SDK must never be called.
    replay_sdk = FakeSDK(chat_handler=lambda k: (_ for _ in ()).throw(
        AssertionError("network call during replay")))
    patch_build_client(monkeypatch, replay_sdk)
    out2 = tmp_path / "replay"
    args = run_args("SKEL", out2, rounds=4, model="DeepSeek Flash",
                    env_file=str(tmp_path / ".env"),
                    budget_file=str(tmp_path / "budget.json"),
                    replay_from=str(out))
    assert cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    assert len(replay_sdk.chat.completions.calls) == 0
    cell = next(_cells(out2))
    assert cell["status"] == "ok"
    assert all(call["cache_hit"] is True for call in cell["calls"])

    # Replaying a different rep index has no cached entry.
    out3 = tmp_path / "replay2"
    args2 = run_args("SKEL", out3, rounds=4, reps=2, model="DeepSeek Flash",
                     env_file=str(tmp_path / ".env"),
                     budget_file=str(tmp_path / "budget.json"),
                     replay_from=str(out))
    assert cli.cmd_run(args2, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    second_cell = json.loads(
        (out3 / "cells" / "lock-order" / "abba_2lock" / "1" / "result.json").read_text())
    assert second_cell["error"] == "replay_miss"


def test_set_cell_resets_call_index_across_cells(tmp_path, monkeypatch):
    # Two G0 runs share one --cache-dir. The first walks both lock-order tasks
    # (so the second task's cells would carry a non-1 call_index if set_cell did
    # not reset it); the second selects only that second task and must hit the
    # cache with zero SDK requests.
    sdk = FakeSDK(chat_handler=sequence_chat_handler([RUST] * 10))
    patch_build_client(monkeypatch, sdk)
    env = write_env(tmp_path, DEEPSEEK_API_KEY="k")
    cache_dir = tmp_path / "shared-cache"
    budget = tmp_path / "budget.json"

    first = tmp_path / "run_first"
    args = run_args("G0", first, tasks="lock-order/*", reps=2,
                    model="DeepSeek Flash", env_file=str(env),
                    budget_file=str(budget), cache_dir=str(cache_dir))
    assert cli.cmd_run(args, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    assert len(sdk.chat.completions.calls) == 10  # 5 lock-order tasks x 2 reps

    second = tmp_path / "run_second"
    args2 = run_args("G0", second, tasks="lock-order/cross_module_cycle", reps=2,
                     model="DeepSeek Flash", env_file=str(env),
                     budget_file=str(budget), cache_dir=str(cache_dir))
    assert cli.cmd_run(args2, oracle_factory=lambda t, term: FakeOracle(True)) == 0
    assert len(sdk.chat.completions.calls) == 10  # no new requests: all hits
    cells = list(_cells(second))
    assert len(cells) == 2
    for cell in cells:
        assert all(call["cache_hit"] is True for call in cell["calls"])
