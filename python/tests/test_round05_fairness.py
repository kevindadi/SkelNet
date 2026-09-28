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


# ── M7/M8: opaque ids on real backend output ─────────────────────────
def _contract_strings() -> list[str]:
    contract = _contract()
    strings = [p["id"] for p in contract.get("properties") or [] if p.get("id")]
    strings += [p["description"] for p in contract.get("preserved") or []
                if p.get("description")]
    return strings


def _assert_no_contract_strings(feedback: dict) -> None:
    text = render_feedback(feedback)
    for marker in _contract_strings():
        assert marker not in text, marker


@rust_tools
def test_opaque_hides_ids_buggy_skeleton(tmp_path):
    from test_feedback_disclosure import BUGGY
    skel = tmp_path / "buggy.skel"
    skel.write_text(BUGGY, encoding="utf-8")
    verify = Backend().verify(skel, CONTRACT_PATH)
    fb = build_explore_feedback(verify, property_ids="opaque")
    _assert_no_contract_strings(fb)
    assert (fb["failed_properties"][0]["id"]
            == fb["diagnostics"][0]["property"]
            == fb["counterexamples"][0]["property"])


@rust_tools
def test_opaque_hides_description_in_message(tmp_path):
    from test_feedback_disclosure import PARTIAL
    skel = tmp_path / "partial.skel"
    skel.write_text(PARTIAL, encoding="utf-8")
    verify = Backend().verify(skel, CONTRACT_PATH)
    fb = build_explore_feedback(verify, property_ids="opaque")
    _assert_no_contract_strings(fb)


@rust_tools
def test_opaque_cir_fills_reqs(tmp_path):
    from test_feedback_disclosure import BUGGY as _buggy_skel  # noqa: F401
    program = json.loads(
        (repo_root() / "benchmarks/tasks" / TASK / "gold.cir.json").read_text())
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                fn["body"] = [s for s in fn["body"] if s.get("resource") != "main::b"]
    cir = tmp_path / "partial.cir.json"
    cir.write_text(json.dumps(program), encoding="utf-8")
    verify = Backend().verify_cir(cir, CONTRACT_PATH)
    fb = build_cir_feedback(verify, contract=_contract(), property_ids="opaque")
    _assert_no_contract_strings(fb)
    entry = fb["failed_properties"][0]
    assert entry["id"] == "P1"
    assert entry["reqs"] == ["R2", "R3"]


# ── N2: keep mode is byte-identical to 9dfaefe ───────────────────────
_EXPECTED_FULL_KEEP = '{\n  "stage": "explore",\n  "outcome": "FAIL",\n  "complete": true,\n  "failed_properties": [\n    {\n      "id": "no-deadlock",\n      "outcome": "FAIL",\n      "detail": "a reachable state has no enabled step and unfinished threads",\n      "reqs": [\n        "R4",\n        "R5",\n        "R7",\n        "R8"\n      ]\n    }\n  ],\n  "preserved_unmet": [],\n  "diagnostics": [\n    {\n      "property": "property:no-deadlock",\n      "outcome": "info",\n      "message": "reachable global deadlock",\n      "skel": {\n        "loc": "main::main::s1",\n        "construct": "scope",\n        "line": 4,\n        "col": 13,\n        "end_line": 4,\n        "end_col": 46,\n        "reqs": []\n      },\n      "unmapped": false\n    }\n  ],\n  "counterexamples": [\n    {\n      "property": "no-deadlock",\n      "reqs": [\n        "R4",\n        "R5",\n        "R7",\n        "R8"\n      ],\n      "steps": [\n        {\n          "step": 1,\n          "thread": 0,\n          "function": "main::main",\n          "line": 4,\n          "statement": "fn main() { scope { spawn t1(); spawn t2(); } }"\n        },\n        {\n          "step": 2,\n          "thread": 1,\n          "function": "main::t1",\n          "line": 5,\n          "statement": "fn t1() { lock a { lock b { } } }"\n        },\n        {\n          "step": 3,\n          "thread": 2,\n          "function": "main::t2",\n          "line": 6,\n          "statement": "fn t2() { lock b { lock a { } } }"\n        },\n        {\n          "step": 4,\n          "thread": 1,\n          "function": "main::t1",\n          "line": 5,\n          "statement": "fn t1() { lock a { lock b { } } }"\n        },\n        {\n          "step": 5,\n          "thread": 2,\n          "function": "main::t2",\n          "line": 6,\n          "statement": "fn t2() { lock b { lock a { } } }"\n        }\n      ],\n      "final_note": "T0 waits scope ; T1 holds [main::a] waits mutex main::b; T2 holds [main::b] waits mutex main::a"\n    }\n  ],\n  "unmapped": 0,\n  "note": "UNKNOWN means the analysis did not complete; it is not a proof of safety. FAIL may already contain a counterexample."\n}\n'


@rust_tools
def test_keep_mode_matches_9dfaefe(tmp_path):
    from test_feedback_disclosure import BUGGY
    skel = tmp_path / "buggy.skel"
    skel.write_text(BUGGY, encoding="utf-8")
    verify = Backend().verify(skel, CONTRACT_PATH)
    fb = build_explore_feedback(verify)
    assert fb["diagnostics"][0]["property"] == "property:no-deadlock"
    assert render_feedback(fb) == _EXPECTED_FULL_KEEP.rstrip("\n")
