"""T7: SKEL/CIR feedback fairness (D5-1..D5-4, D11)."""

import json

from skelnet.backend import Backend, BackendResult, repo_root
from skelnet.pipeline import extract_cir, run_cir_cell
from skelnet.prompts import (apply_feedback_mode, build_cir_feedback,
                             build_explore_feedback, render_feedback)

from round03_helpers import rust_tools

TASK = "lock-order/abba_2lock"
CONTRACT_PATH = repo_root() / "benchmarks/tasks" / TASK / "contract.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


class _Result:
    def __init__(self, payload, *, kind="semantic", outcome=None):
        self.kind = kind
        self.status = "ok"
        self.outcome = outcome or payload.get("outcome")
        self.complete = payload.get("complete", True)
        self.payload = payload
        self.error = None


# ── D5-2: opaque property ids ────────────────────────────────────────
def test_opaque_ids_are_replaced_everywhere():
    payload = {
        "outcome": "FAIL", "complete": True,
        "properties": [
            {"id": "no-deadlock", "outcome": "FAIL", "detail": "d", "reqs": ["R4"]},
            {"id": "preserved: main::t1 completes", "outcome": "FAIL",
             "detail": "x", "reqs": ["R1"]},
        ],
        "diagnostics": [{"code": "property:no-deadlock", "severity": "info",
                         "message": "reachable global deadlock (no-deadlock)",
                         "skel": {"loc": "main::main::s1", "line": 5},
                         "unmapped": False}],
        "counterexamples": [{"property": "no-deadlock", "reqs": ["R4"],
                             "steps": [{"step": 1, "thread": 0,
                                        "function": "main::main",
                                        "skel": {"loc": "s1", "line": 5},
                                        "statement": "s"}], "final_note": None}],
        "unmapped": False,
    }
    index: dict = {}
    fb = build_explore_feedback(_Result(payload), property_ids="opaque",
                                index=index)
    assert index["no-deadlock"] == "P1"
    assert index["preserved: main::t1 completes"] == "P2"
    assert fb["failed_properties"][0]["id"] == "P1"
    assert fb["failed_properties"][1]["id"] == "P2"
    assert fb["counterexamples"][0]["property"] == "P1"
    text = render_feedback(fb)
    assert "no-deadlock" not in text
    assert "preserved: main::t1 completes" not in text
    assert "P1" in text and "P2" in text


def test_keep_ids_is_default():
    payload = {"outcome": "FAIL", "complete": True,
               "properties": [{"id": "no-deadlock", "outcome": "FAIL"}],
               "diagnostics": [], "counterexamples": [], "unmapped": False}
    fb = build_explore_feedback(_Result(payload))
    assert fb["failed_properties"][0]["id"] == "no-deadlock"


# ── D5-4: CIR reqs filled from the contract, nothing else ────────────
def test_cir_feedback_fills_reqs_from_contract():
    payload = {"outcome": "FAIL", "complete": True,
               "properties": [{"id": "no-deadlock", "outcome": "FAIL",
                               "detail": "deadlock", "reqs": None}],
               "invalid": [], "diagnostics": [], "unmapped": False}
    fb = build_cir_feedback(_Result(payload), contract=_contract())
    assert fb["failed_properties"][0]["reqs"] == ["R4", "R5", "R7", "R8"]
    text = render_feedback(fb)
    for marker in ("goal", "bounds", "holds_all", "function_completed"):
        assert marker not in text


def test_cir_feedback_without_contract_keeps_null_reqs():
    payload = {"outcome": "FAIL", "complete": True,
               "properties": [{"id": "no-deadlock", "outcome": "FAIL"}],
               "invalid": [], "diagnostics": [], "unmapped": False}
    fb = build_cir_feedback(_Result(payload))
    assert fb["failed_properties"][0]["reqs"] is None


# ── D5-3: CIR feedback never carries repair_hints ────────────────────
@rust_tools
def test_cir_feedback_has_no_repair_hints(tmp_path):
    program = json.loads(
        (repo_root() / "benchmarks/tasks" / TASK / "gold.cir.json").read_text())
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                for stmt in fn["body"]:
                    if stmt.get("kind") in ("mutex_lock", "mutex_unlock"):
                        stmt["resource"] = ("main::b" if stmt["resource"] == "main::a"
                                            else "main::a")
    cir = tmp_path / "buggy.cir.json"
    cir.write_text(json.dumps(program), encoding="utf-8")
    result = Backend().verify_cir(cir, CONTRACT_PATH)
    assert result.outcome == "FAIL"
    fb = build_cir_feedback(result, contract=_contract())
    text = render_feedback(fb)
    assert "repair_hints" not in text
    assert "repair_hint" not in text
    # The raw payload's repair_hints (if any) are not forwarded.
    assert "repair_hints" not in fb


# ── D5-1: CIR check_ok excludes INVALID and UNSUPPORTED ──────────────
class _StatusBackend:
    def __init__(self, outcome):
        self.outcome = outcome

    def verify_cir(self, path, contract):
        return BackendResult("semantic", "ok", outcome=self.outcome,
                             complete=False, payload={"properties": []})


def _check_ok(outcome):
    from skelnet.providers import ScriptedProvider
    provider = ScriptedProvider([{"text": '{"a": 1}'}])
    result = run_cir_cell(
        task=TASK, requirements="r", contract_path=CONTRACT_PATH,
        provider=provider, backend=_StatusBackend(outcome), oracle=None,
        workdir=_tmp(), rounds=1, call_budget=5)
    return result.check_ok


def _tmp():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


def test_cir_check_ok_rule():
    assert _check_ok("FAIL") is True
    assert _check_ok("UNKNOWN") is True
    assert _check_ok("INVALID") is False
    assert _check_ok("UNSUPPORTED") is False


# ── D11: CIR is never normalised ─────────────────────────────────────
class _RecordingBackend:
    def __init__(self):
        self.seen = None

    def verify_cir(self, path, contract):
        self.seen = path.read_text(encoding="utf-8")
        return BackendResult("semantic", "ok", outcome="FAIL", complete=False,
                             payload={"properties": []})


def test_cir_candidate_written_verbatim(tmp_path):
    aliased = '{"program": "p", "modules": [{"funcs": []}]}'  # alias, not normalised
    from skelnet.providers import ScriptedProvider
    backend = _RecordingBackend()
    run_cir_cell(task=TASK, requirements="r", contract_path=CONTRACT_PATH,
                 provider=ScriptedProvider([{"text": aliased}]), backend=backend,
                 oracle=None, workdir=tmp_path, rounds=1, call_budget=5)
    written = (tmp_path / "candidate_1.cir.json").read_text(encoding="utf-8")
    assert written == extract_cir(aliased)
    assert backend.seen == extract_cir(aliased)
