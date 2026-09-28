"""T6: feedback_mode trims verification feedback (full/outcome_only/nocex/nomap)."""

import json

import pytest

from skelnet import cli, prompts
from skelnet.backend import Backend, repo_root
from skelnet.oracle import FakeOracle
from skelnet.pipeline import run_skel_cell
from skelnet.providers import ScriptedProvider
from skelnet.rusttools.compile import CompileResult

from _fake_sdk import BUGGY, FIXED, RUST, ScriptedTransportClient, run_args
from test_pipeline_skel import BUGGY as SKEL_BUGGY, FIXED as SKEL_FIXED

CONTRACT = repo_root() / "benchmarks/tasks/lock-order/abba_2lock/contract.json"

_MODES = ("full", "outcome_only", "nocex", "nomap")


def _explore_payload() -> dict:
    skel = {"loc": "main::main::s1", "construct": "scope", "line": 5, "col": 13,
            "end_line": 5, "end_col": 46, "reqs": ["R1"]}
    return {
        "outcome": "FAIL", "complete": True,
        "properties": [
            {"id": "no-deadlock", "outcome": "FAIL", "detail": "deadlock",
             "reqs": ["R4"]},
            {"id": "preserved: main::t1 completes", "outcome": "FAIL",
             "detail": "preserved reachability: completed(f1)", "reqs": ["R1"]},
        ],
        "diagnostics": [{"code": "property:no-deadlock", "severity": "info",
                         "message": "reachable global deadlock", "skel": skel,
                         "unmapped": False, "origin": "concir"}],
        "counterexamples": [{"property": "no-deadlock", "reqs": ["R4"],
                             "steps": [{"step": 1, "thread": 0,
                                        "function": "main::main", "skel": skel,
                                        "statement": "fn main() { scope { } }"}],
                             "final_note": "x"}],
        "unmapped": False,
    }


class _Result:
    def __init__(self, payload):
        self.kind = "semantic"
        self.status = "ok"
        self.outcome = payload.get("outcome")
        self.complete = payload.get("complete")
        self.payload = payload
        self.error = None


def _feedback(mode):
    fb = prompts.build_explore_feedback(_Result(_explore_payload()))
    return prompts.apply_feedback_mode(fb, mode)


def test_full_is_unchanged():
    fb = prompts.build_explore_feedback(_Result(_explore_payload()))
    assert prompts.apply_feedback_mode(fb, "full") == fb
    assert fb["counterexamples"][0]["steps"][0]["line"] == 5
    assert fb["diagnostics"][0]["concir_loc"] == "main::main::s1"


def test_outcome_only_keeps_only_ids():
    fb = _feedback("outcome_only")
    assert set(fb) <= {"stage", "outcome", "complete", "failed_properties",
                       "preserved_unmet"}
    assert fb["failed_properties"] == [{"id": "no-deadlock"},
                                       {"id": "preserved: main::t1 completes"}]
    assert "counterexamples" not in fb and "diagnostics" not in fb


def test_nocex_drops_counterexamples():
    fb = _feedback("nocex")
    assert "counterexamples" not in fb
    assert fb["diagnostics"]


def test_nomap_keeps_only_concir_position():
    fb = _feedback("nomap")
    assert "skel" not in fb["diagnostics"][0]
    assert fb["diagnostics"][0]["concir_loc"] == "main::main::s1"
    step = fb["counterexamples"][0]["steps"][0]
    assert "line" not in step and "statement" not in step
    assert step["concir_loc"] == "main::main::s1"


def test_nomap_matches_full_for_cir():
    # CIR feedback is already ConcIR-positioned, so nomap is a no-op there.
    payload = {"outcome": "FAIL", "complete": True, "properties": [],
               "invalid": [{"code": "X", "location": "main::main::s1",
                            "message": "bad"}],
               "diagnostics": [], "unmapped": False}
    fb = prompts.build_cir_feedback(_Result(payload))
    assert prompts.apply_feedback_mode(fb, "nomap") == fb


# ── pipeline integration ─────────────────────────────────────────────
def test_outcome_only_reaches_the_model(tmp_path):
    provider = ScriptedProvider([{"text": SKEL_BUGGY}, {"text": SKEL_FIXED},
                                 {"text": RUST}])
    run_skel_cell(
        task="lock-order/abba_2lock", requirements="r", contract_path=CONTRACT,
        provider=provider, backend=Backend(), oracle=FakeOracle(True),
        workdir=tmp_path, rounds=4, call_budget=5, feedback_mode="outcome_only",
        compile_fn=lambda t, w, s, **k: CompileResult(ok=True))
    feedback = json.loads(provider.calls[1].feedback)
    assert set(feedback) <= {"stage", "outcome", "complete", "failed_properties",
                             "preserved_unmet"}


def test_resume_rejects_changed_feedback_mode(tmp_path):
    out = tmp_path / "run"
    base = dict(rounds=1, budget_file=str(tmp_path / "budget.json"))
    args = run_args("SKEL", out, **base)
    assert cli.cmd_run(args,
                       client_factory=lambda s, o: ScriptedTransportClient([RUST]),
                       oracle_factory=lambda t, term: FakeOracle(True)) == 0
    args2 = run_args("SKEL", out, resume=True, feedback_mode="outcome_only", **base)
    with pytest.raises(SystemExit):
        cli.cmd_run(args2, client_factory=lambda s, o: ScriptedTransportClient([RUST]),
                    oracle_factory=lambda t, term: FakeOracle(True))


def test_method_flags_rejected_for_other_arms(tmp_path):
    out = tmp_path / "g0"
    args = run_args("G0", out, feedback_mode="outcome_only")
    with pytest.raises(SystemExit):
        cli.cmd_run(args, client_factory=lambda s, o: ScriptedTransportClient([RUST]),
                    oracle_factory=lambda t, term: FakeOracle(True))
