"""R9d-P1: the skeleton stage is capped at min(rounds, call_budget - 2).

Real `cmd_run` entry for SKEL and CIR with a scripted client and a fake oracle;
the Rust compile is real (gated on cargo), so a first compile failure forces a
`rust_fix`. Undo the pipeline cap and the call sequence changes.
"""

import json

from skelnet import cli
from skelnet.backend import repo_root
from skelnet.oracle import FakeOracle

from _fake_sdk import ScriptedTransportClient, run_args
from round03_helpers import rust_tools
from test_pipeline_skel import BUGGY, FIXED

TASK = "lock-order/abba_2lock"
RUST_BAD = "```rust\nfn main() { let x = 1 }\n```"
RUST_GOOD = "```rust\nfn main() { println!(\"DONE\"); }\n```"


def _bad_cir() -> str:
    gold = json.loads((repo_root() / "benchmarks/tasks" / TASK / "gold.cir.json"
                       ).read_text())
    for module in gold["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                for stmt in fn["body"]:
                    if stmt.get("kind") in ("mutex_lock", "mutex_unlock"):
                        stmt["resource"] = ("main::b"
                                            if stmt["resource"] == "main::a"
                                            else "main::a")
    return json.dumps(gold)


def _run(tmp_path, arm, texts, *, rounds=4, call_budget=5):
    out = tmp_path / arm.lower()
    args = run_args(arm, out, tasks=TASK, reps=1, rounds=rounds,
                    call_budget=call_budget, hint="h1", stage=0,
                    budget_file=str(tmp_path / "budget.json"))
    rc = cli.cmd_run(args,
                     client_factory=lambda spec, o: ScriptedTransportClient(texts),
                     oracle_factory=lambda td, term: FakeOracle(True))
    assert rc == 0
    cell = json.loads((out / "cells" / TASK / "0" / "result.json").read_text())
    return cell


@rust_tools
def test_skel_skeleton_exhausted_still_gets_rust_fix(tmp_path):
    # 3 failing skeleton attempts, then a Rust program that does not compile,
    # then a compile fix. With call_budget=5 the 5th call must be `rust_fix`.
    texts = ([BUGGY] * 3) + [RUST_BAD, RUST_GOOD]
    cell = _run(tmp_path, "SKEL", texts)
    stages = [call["stage"] for call in cell["calls"]]
    assert stages == ["generate", "feedback", "feedback", "rust", "rust_fix"], stages
    assert cell["rounds_used"] == 3
    assert cell["rust_calls"] == 2
    assert cell["rust_compiled"] is True


@rust_tools
def test_cir_skeleton_exhausted_still_gets_rust_fix(tmp_path):
    cir_bad = "```json\n" + _bad_cir() + "\n```"
    texts = ([cir_bad] * 3) + [RUST_BAD, RUST_GOOD]
    cell = _run(tmp_path, "CIR", texts)
    stages = [call["stage"] for call in cell["calls"]]
    assert stages == ["generate", "feedback", "feedback", "rust", "rust_fix"], stages
    assert cell["rounds_used"] == 3
    assert cell["rust_calls"] == 2


@rust_tools
def test_skel_verified_first_round_uses_remaining_calls_for_rust(tmp_path):
    # The skeleton passes on attempt 1, so the Rust stage gets 4 tries.
    texts = [FIXED] + [RUST_BAD] * 4
    cell = _run(tmp_path, "SKEL", texts)
    stages = [call["stage"] for call in cell["calls"]]
    assert stages == ["generate", "rust", "rust_fix", "rust_fix", "rust_fix"], stages
    assert cell["rounds_used"] == 1
    assert cell["rust_calls"] == 4
