"""Fake-LLM end-to-end: buggy skeleton -> remapped feedback -> fixed -> accept."""

from skelnet.backend import Backend, repo_root
from skelnet.oracle import FakeOracle
from skelnet.pipeline import run_skel_cell
from skelnet.providers import ScriptedProvider

BUGGY = """```skel
skeleton abba_bug;
mutex a;
mutex b;
@R1
fn main() { scope { spawn t1(); spawn t2(); } }
@R2 @R4
fn t1() { lock a { lock b { } } }
@R3 @R4
fn t2() { lock b { lock a { } } }
```"""

FIXED = """```skel
skeleton abba_ok;
mutex a;
mutex b;
@R1
fn main() { scope { spawn t1(); spawn t2(); } }
@R2 @R4
fn t1() { lock a { lock b { } } }
@R3 @R4
fn t2() { lock a { lock b { } } }
```"""

RUST = "```rust\nfn main() { println!(\"DONE\"); }\n```"


def test_skel_arm_revises_then_accepts(tmp_path):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    provider = ScriptedProvider([{"text": BUGGY}, {"text": FIXED}, {"text": RUST}])
    oracle = FakeOracle(functional_ok=True)
    result = run_skel_cell(
        task="lock-order/abba_2lock", requirements="two workers, two locks",
        contract_path=contract, provider=provider, backend=Backend(),
        oracle=oracle, workdir=tmp_path, rounds=4)
    assert result.accepted, result.history
    assert [h["outcome"] for h in result.history] == ["FAIL", "PASS"]
    assert result.evidence_sufficient
    assert result.oracle.functional_ok
    assert len(provider.calls) == 3  # two skeleton attempts + one Rust call
    # The second request actually carried remapped feedback with a line number.
    assert provider.calls[1].feedback is not None
    assert '"line"' in provider.calls[1].feedback


def test_skel_codegen_rust_mode_skips_llm_rust(tmp_path):
    root = repo_root()
    contract = root / "benchmarks/tasks/lock-order/abba_2lock/contract.json"
    provider = ScriptedProvider([{"text": BUGGY}, {"text": FIXED}])
    oracle = FakeOracle(functional_ok=True)
    result = run_skel_cell(
        task="lock-order/abba_2lock", requirements="two workers, two locks",
        contract_path=contract, provider=provider, backend=Backend(),
        oracle=oracle, workdir=tmp_path, rounds=4, rust_mode="codegen")
    assert result.accepted, result.history
    assert result.rust and "fn main" in result.rust
    assert len(provider.calls) == 2  # no Rust LLM call in codegen mode
    assert result.oracle.details["extra_files"] == ["src/cir_trace.rs"]
