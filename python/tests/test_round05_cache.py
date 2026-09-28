"""T9: cache / revision-loop interaction for SKEL cells with a rust_fix stage."""

import json

from skelnet import cli
from skelnet.transport import TransportError

from _fake_sdk import run_args
from round03_helpers import FakeTools
from test_pipeline_skel import BUGGY as SKEL_BUGGY, FIXED as SKEL_FIXED
from test_round05_budget import (_CompileFailThenOk, _ScriptedChat,
                                 RUST_BAD, RUST_GOOD)


class _NoCallClient:
    def complete(self, system, user):
        raise TransportError("network call during replay/resume")


def _args(out, tmp_path, **extra):
    return run_args("SKEL", out, tasks="lock-order/abba_2lock", rounds=3,
                    call_budget=5, budget_file=str(tmp_path / "budget.json"), **extra)


def _run(tmp_path, out, texts, tools, **extra):
    client = _ScriptedChat(texts)
    return cli.cmd_run(_args(out, tmp_path, **extra),
                       client_factory=lambda s, o: client, oracle_runner=tools)


def _cell(out):
    return json.loads(
        (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").read_text())


def test_call_indices_are_distinct_within_a_cell(tmp_path):
    out = tmp_path / "run"
    tools = _CompileFailThenOk(FakeTools())
    assert _run(tmp_path, out, [SKEL_FIXED, RUST_BAD, RUST_GOOD], tools) == 0
    cell = _cell(out)
    assert [c["stage"] for c in cell["calls"]] == ["generate", "rust", "rust_fix"]
    assert all(c["cache_hit"] is False for c in cell["calls"])
    shas = [c["request_sha256"] for c in cell["calls"]]
    assert len(set(shas)) == len(shas)


def test_replay_from_reproduces_a_rust_fix_cell(tmp_path):
    out = tmp_path / "run"
    tools = _CompileFailThenOk(FakeTools())
    assert _run(tmp_path, out, [SKEL_FIXED, RUST_BAD, RUST_GOOD], tools) == 0
    before = _cell(out)

    out2 = tmp_path / "replay"
    replay_tools = _CompileFailThenOk(FakeTools())
    rc = cli.cmd_run(
        _args(out2, tmp_path, replay_from=str(out)),
        client_factory=lambda s, o: _NoCallClient(), oracle_runner=replay_tools)
    assert rc == 0
    after = _cell(out2)
    assert all(c["cache_hit"] is True for c in after["calls"])
    assert after["rust_calls"] == before["rust_calls"]
    assert after["rust_compiled"] == before["rust_compiled"]


def test_resume_hits_the_cache(tmp_path):
    out = tmp_path / "run"
    tools = _CompileFailThenOk(FakeTools())
    assert _run(tmp_path, out, [SKEL_FIXED, RUST_BAD, RUST_GOOD], tools) == 0
    (out / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").unlink()

    resume_tools = _CompileFailThenOk(FakeTools())
    rc = cli.cmd_run(
        _args(out, tmp_path, resume=True),
        client_factory=lambda s, o: _NoCallClient(), oracle_runner=resume_tools)
    assert rc == 0
    cell = _cell(out)
    assert all(c["cache_hit"] is True for c in cell["calls"])


def test_shared_cache_first_call_hits_across_feedback_modes(tmp_path):
    cache = tmp_path / "shared"
    out1 = tmp_path / "full"
    tools = _CompileFailThenOk(FakeTools())
    assert _run(tmp_path, out1, [SKEL_BUGGY, SKEL_FIXED, RUST_GOOD], tools,
                cache_dir=str(cache)) == 0

    out2 = tmp_path / "outcome"
    tools2 = _CompileFailThenOk(FakeTools())
    assert _run(tmp_path, out2, [SKEL_FIXED, RUST_GOOD], tools2,
                cache_dir=str(cache), feedback_mode="outcome_only") == 0
    cell = _cell(out2)
    assert cell["calls"][0]["cache_hit"] is True   # identical first call
    assert cell["calls"][1]["cache_hit"] is False  # trimmed feedback differs


def test_skel_and_cir_never_share(tmp_path):
    cache = tmp_path / "shared"
    out1 = tmp_path / "skel"
    assert _run(tmp_path, out1, [SKEL_FIXED, RUST_GOOD],
                _CompileFailThenOk(FakeTools()), cache_dir=str(cache)) == 0

    out2 = tmp_path / "cir"
    gold = (__import__("pathlib").Path(__file__).parent.parent.parent
            / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json")
    client = _ScriptedChat([gold.read_text(), RUST_GOOD])
    rc = cli.cmd_run(
        run_args("CIR", out2, tasks="lock-order/abba_2lock", rounds=3,
                 call_budget=5, budget_file=str(tmp_path / "budget.json"),
                 cache_dir=str(cache)),
        client_factory=lambda s, o: client,
        oracle_runner=_CompileFailThenOk(FakeTools()))
    assert rc == 0
    cell = _cell(out2)
    assert all(c["cache_hit"] is False for c in cell["calls"])
