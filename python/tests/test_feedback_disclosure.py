"""Feedback must never disclose the contract goal; every step has a DSL line."""

import json
from pathlib import Path

from skelnet.backend import Backend, repo_root
from skelnet.prompts import build_explore_feedback, render_feedback

BUGGY = """skeleton abba_bug;
mutex a;
mutex b;
fn main() { scope { spawn t1(); spawn t2(); } }
fn t1() { lock a { lock b { } } }
fn t2() { lock b { lock a { } } }
"""


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
