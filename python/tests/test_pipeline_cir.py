"""Fake-LLM CIR ablation: a valid ConcIR candidate verifies PASS, then Rust."""

from skelnet.backend import Backend, repo_root
from skelnet.oracle import FakeOracle
from skelnet.pipeline import run_cir_cell
from skelnet.providers import ScriptedProvider


def test_cir_arm_accepts_valid_program(tmp_path):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    cir = (root / "benchmarks/tasks/lock-order/abba_2lock/gold.cir.json").read_text()
    rust = "```rust\nfn main() {}\n```"
    provider = ScriptedProvider([{"text": cir}, {"text": rust}])
    result = run_cir_cell(
        task="lock-order/abba_2lock", requirements="two workers, two locks",
        contract_path=contract, provider=provider, backend=Backend(),
        oracle=FakeOracle(True), workdir=tmp_path, rounds=4)
    assert result.accepted, result.history
    assert result.history[0]["outcome"] == "PASS"
    assert result.oracle.functional_ok
