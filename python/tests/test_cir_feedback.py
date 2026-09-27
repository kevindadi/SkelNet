"""F3: CIR-arm feedback matches the ConcIR explore output and never leaks goals."""

import json

from skelnet.backend import Backend, repo_root
from skelnet.prompts import (PRESERVED_DETAIL, build_cir_feedback,
                             render_feedback)

TASK = "lock-order/abba_2lock"


def _gold() -> dict:
    return json.loads(
        (repo_root() / "benchmarks" / "tasks" / TASK / "gold.cir.json").read_text())


def _contract():
    return repo_root() / "benchmarks" / "tasks" / TASK / "contract.json"


def _feedback(tmp_path, program: dict):
    path = tmp_path / "candidate.cir.json"
    path.write_text(json.dumps(program), encoding="utf-8")
    return build_cir_feedback(Backend().verify_cir(path, _contract()))


def _assert_no_leak(feedback: dict) -> None:
    text = render_feedback(feedback)
    for marker in ("holds_all", "completed(", "function_completed", "goal"):
        assert marker not in text, f"leaked {marker!r}: {text}"


def test_cir_feedback_non_json_process_error(tmp_path):
    path = tmp_path / "bad.cir.json"
    path.write_text("not json", encoding="utf-8")
    result = Backend().verify_cir(path, _contract())
    feedback = build_cir_feedback(result)
    assert feedback["process_error"]
    assert feedback["process_error"].startswith("JSON parse error: ")
    assert str(path) not in feedback["process_error"]
    assert str(tmp_path) not in feedback["process_error"]
    _assert_no_leak(feedback)


def test_cir_feedback_invalid_lists_e501(tmp_path):
    program = _gold()
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t1":
                fn["body"] = [s for s in fn["body"]
                              if not (s.get("kind") == "mutex_unlock"
                                      and s.get("resource") == "main::b")]
    feedback = _feedback(tmp_path, program)
    assert feedback["outcome"] == "INVALID"
    assert any(d["code"] == "E501" for d in feedback["diagnostics"])
    assert feedback["process_error"] is None
    _assert_no_leak(feedback)


def test_cir_feedback_counterexample_and_final_state(tmp_path):
    program = _gold()
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                for stmt in fn["body"]:
                    if stmt.get("kind") in ("mutex_lock", "mutex_unlock"):
                        stmt["resource"] = ("main::b" if stmt["resource"] == "main::a"
                                            else "main::a")
    feedback = _feedback(tmp_path, program)
    assert feedback["outcome"] == "FAIL"
    assert feedback["counterexamples"], feedback
    ce = feedback["counterexamples"][0]
    assert ce["steps"], ce
    final = json.dumps(ce["final_state"])
    assert "main::a" in final and "main::b" in final
    _assert_no_leak(feedback)


def test_cir_feedback_preserved_detail_sanitized(tmp_path):
    program = _gold()
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                fn["body"] = [s for s in fn["body"] if s.get("resource") != "main::b"]
    feedback = _feedback(tmp_path, program)
    preserved = [p for p in feedback["failed_properties"]
                 if str(p["id"]).startswith("preserved:")]
    assert preserved, feedback["failed_properties"]
    for entry in preserved:
        assert entry["detail"] == PRESERVED_DETAIL
        assert entry["outcome"] == "FAIL"
    _assert_no_leak(feedback)
