"""Fake-LLM G0 baseline: direct Rust scored by the shared oracle."""

from skelnet.oracle import FakeOracle
from skelnet.pipeline import run_g0_cell
from skelnet.providers import ScriptedProvider


def test_g0_arm_scores_rust(tmp_path):
    rust = "```rust\nfn main() { println!(\"DONE\"); }\n```"
    provider = ScriptedProvider([{"text": rust}])
    oracle = FakeOracle(functional_ok=True)
    result = run_g0_cell(task="t", requirements="do a thing", provider=provider,
                         oracle=oracle, workdir=tmp_path)
    assert result.accepted
    assert result.rust is not None and "fn main" in result.rust
    assert oracle.calls == [result.rust]
