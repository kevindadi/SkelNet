"""Feedback must never disclose the contract goal; every step has a DSL line."""

import json
from pathlib import Path

import pytest

from skelnet.backend import Backend, repo_root
from skelnet.prompts import (PRESERVED_DETAIL, apply_feedback_mode,
                             build_cir_feedback, build_explore_feedback,
                             render_feedback)

BUGGY = """skeleton abba_bug;
mutex a;
mutex b;
fn main() { scope { spawn t1(); spawn t2(); } }
fn t1() { lock a { lock b { } } }
fn t2() { lock b { lock a { } } }
"""

# t2 no longer holds both locks, so the preserved "t2 holds [a,b]" goal fails.
PARTIAL = """skeleton abba_partial;
mutex a;
mutex b;
fn main() { scope { spawn t1(); spawn t2(); } }
fn t1() { lock a { lock b { } } }
fn t2() { lock a { } }
"""


def _assert_no_goal(text: str) -> None:
    for marker in ("holds_all", "completed(", "function_completed", "goal"):
        assert marker not in text, f"leaked {marker!r}: {text}"


def _assert_preserved_fail_sanitized(feedback: dict) -> None:
    preserved = [p for p in feedback["failed_properties"]
                 if str(p.get("id", "")).startswith("preserved:")]
    assert preserved, feedback["failed_properties"]
    for entry in preserved:
        assert entry["outcome"] == "FAIL"
        assert entry["detail"] == PRESERVED_DETAIL
        # The id itself is kept for now (pending decision).
        assert entry["id"].startswith("preserved:")


def test_feedback_has_lines_and_no_goal(tmp_path):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    skel = tmp_path / "buggy.skel"
    skel.write_text(BUGGY, encoding="utf-8")
    verify = Backend().verify(skel, contract)
    assert verify.outcome == "FAIL"
    feedback = build_explore_feedback(verify)
    text = render_feedback(feedback)
    assert "goal" not in text.lower()
    assert "function_completed" not in text
    assert "holds_all" not in text
    assert feedback["counterexamples"], "expected a counterexample"
    for ce in feedback["counterexamples"]:
        assert ce["steps"]
        for step in ce["steps"]:
            assert step["line"] is not None and step["line"] > 0


@pytest.mark.parametrize("mode", ["full", "outcome_only", "nocex", "nomap"])
def test_no_goal_in_all_feedback_modes(tmp_path, mode):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    skel = tmp_path / "buggy.skel"
    skel.write_text(BUGGY, encoding="utf-8")
    skel_feedback = apply_feedback_mode(
        build_explore_feedback(Backend().verify(skel, contract)), mode)
    _assert_no_goal(render_feedback(skel_feedback))

    program = json.loads(
        (root / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json").read_text())
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                fn["body"] = [s for s in fn["body"] if s.get("resource") != "main::b"]
    cir = tmp_path / "partial.cir.json"
    cir.write_text(json.dumps(program), encoding="utf-8")
    cir_feedback = apply_feedback_mode(
        build_cir_feedback(Backend().verify_cir(cir, contract)), mode)
    _assert_no_goal(render_feedback(cir_feedback))


def test_preserved_detail_sanitized_in_both_arms(tmp_path):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"

    # SKEL: t2 holds only a, so a preserved goal fails.
    skel = tmp_path / "partial.skel"
    skel.write_text(PARTIAL, encoding="utf-8")
    skel_result = Backend().verify(skel, contract)
    assert skel_result.outcome == "FAIL"
    skel_feedback = build_explore_feedback(skel_result)
    _assert_preserved_fail_sanitized(skel_feedback)
    _assert_no_goal(render_feedback(skel_feedback))

    # CIR: the same defect expressed in ConcIR.
    program = json.loads(
        (root / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json").read_text())
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                fn["body"] = [s for s in fn["body"] if s.get("resource") != "main::b"]
    cir = tmp_path / "partial.cir.json"
    cir.write_text(json.dumps(program), encoding="utf-8")
    cir_result = Backend().verify_cir(cir, contract)
    cir_feedback = build_cir_feedback(cir_result)
    _assert_preserved_fail_sanitized(cir_feedback)
    _assert_no_goal(render_feedback(cir_feedback))
