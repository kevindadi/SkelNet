"""Fake-LLM CIR ablation: code-block extraction, verification, then Rust."""

import json

from skelnet.backend import Backend, repo_root
from skelnet.oracle import FakeOracle
from skelnet.pipeline import extract_cir, run_cir_cell
from skelnet.providers import ScriptedProvider
from skelnet.rusttools.compile import CompileResult

TASK = "lock-order/abba_2lock"


def _ok_compile(tools, workdir, source, **kwargs):
    return CompileResult(ok=True)


def _gold() -> dict:
    return json.loads(
        (repo_root() / "benchmarks" / "tasks" / TASK / "gold.cir.json").read_text())


def _contract():
    return repo_root() / "benchmarks" / "tasks" / TASK / "contract.json"


def _invalid() -> dict:
    program = _gold()
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t1":
                fn["body"] = [s for s in fn["body"]
                              if not (s.get("kind") == "mutex_unlock"
                                      and s.get("resource") == "main::b")]
    return program


def _buggy() -> dict:
    program = _gold()
    for module in program["modules"]:
        for fn in module["functions"]:
            if fn["name"] == "t2":
                for stmt in fn["body"]:
                    if stmt.get("kind") in ("mutex_lock", "mutex_unlock"):
                        stmt["resource"] = ("main::b" if stmt["resource"] == "main::a"
                                            else "main::a")
    return program


def test_extract_cir_handles_fences_and_bare_json():
    assert extract_cir('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_cir('```\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_cir('{"a": 1}') == '{"a": 1}'


def test_cir_arm_accepts_valid_program(tmp_path):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    cir = (root / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json").read_text()
    rust = "```rust\nfn main() {}\n```"
    provider = ScriptedProvider([{"text": cir}, {"text": rust}])
    result = run_cir_cell(
        task="lock-order/abba_2lock", requirements="two workers, two locks",
        contract_path=contract, provider=provider, backend=Backend(),
        oracle=FakeOracle(True), workdir=tmp_path, rounds=4, compile_fn=_ok_compile)
    assert result.accepted, result.history
    assert result.history[0]["outcome"] == "PASS"
    assert result.oracle.functional_ok


def test_cir_arm_extracts_fenced_reply(tmp_path):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    cir = (root / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json").read_text()
    fenced = "Here is the program:\n```json\n" + cir + "\n```\n"
    provider = ScriptedProvider([{"text": fenced}, {"text": "```rust\nfn main() {}\n```"}])
    result = run_cir_cell(
        task="lock-order/abba_2lock", requirements="two workers, two locks",
        contract_path=contract, provider=provider, backend=Backend(),
        oracle=FakeOracle(True), workdir=tmp_path, rounds=4, compile_fn=_ok_compile)
    assert result.accepted, result.history
    assert result.parse_ok


def test_cir_check_ok_excludes_invalid_and_unsupported(tmp_path):
    # check_ok counts a semantic result that is neither INVALID nor UNSUPPORTED
    # (D5-1); a FAIL round still counts.
    provider = ScriptedProvider([{"text": json.dumps(_invalid())},
                                 {"text": json.dumps(_buggy())}])
    result = run_cir_cell(
        task=TASK, requirements="two workers, two locks", contract_path=_contract(),
        provider=provider, backend=Backend(), oracle=FakeOracle(True),
        workdir=tmp_path, rounds=2)
    assert result.check_ok is True  # round 2 is FAIL, not INVALID/UNSUPPORTED
    assert not result.accepted


def test_cir_check_ok_false_for_process_errors(tmp_path):
    provider = ScriptedProvider([{"text": "not json"}, {"text": "not json"}])
    result = run_cir_cell(
        task=TASK, requirements="two workers, two locks", contract_path=_contract(),
        provider=provider, backend=Backend(), oracle=FakeOracle(True),
        workdir=tmp_path, rounds=2)
    assert result.check_ok is False


def test_cir_codegen_rust_mode(tmp_path):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    cir = (root / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json").read_text()
    provider = ScriptedProvider([{"text": cir}])
    oracle = FakeOracle(True)
    result = run_cir_cell(
        task="lock-order/abba_2lock", requirements="two workers, two locks",
        contract_path=contract, provider=provider, backend=Backend(),
        oracle=oracle, workdir=tmp_path, rounds=4, rust_mode="codegen")
    assert result.accepted, result.history
    assert result.rust and "fn main" in result.rust
    assert len(provider.calls) == 1  # no Rust LLM call in codegen mode
    assert result.oracle.details["extra_files"] == ["src/cir_trace.rs"]
