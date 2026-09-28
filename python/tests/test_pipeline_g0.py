"""Fake-LLM G0 baseline: direct Rust. Acceptance is compile, not the oracle."""

import json
from types import SimpleNamespace

from skelnet.oracle import FakeOracle
from skelnet.pipeline import run_g0_cell
from skelnet.providers import ScriptedProvider
from skelnet.rusttools.runner import ToolRunner

from round03_helpers import ns

RUST = "```rust\nfn main() { println!(\"DONE\"); }\n```"


def _ok(_tools, _workdir, _source):
    return SimpleNamespace(ok=True, errors=[], unavailable=None)


def _bad(_tools, _workdir, _source):
    return SimpleNamespace(ok=False, errors=[{"rendered": "error: x"}], unavailable=None)


def test_g0_compiles_but_oracle_fails_is_accepted(tmp_path):
    provider = ScriptedProvider([{"text": RUST}])
    oracle = FakeOracle(functional_ok=False)
    result = run_g0_cell(task="t", requirements="do a thing", provider=provider,
                         oracle=oracle, workdir=tmp_path, compile_fn=_ok)
    assert result.accepted is True
    assert result.check_ok is True
    assert result.rust is not None and "fn main" in result.rust
    assert oracle.calls == [result.rust]


def test_g0_does_not_compile_is_rejected_and_oracle_still_runs(tmp_path):
    provider = ScriptedProvider([{"text": RUST}])
    oracle = FakeOracle(functional_ok=True)
    result = run_g0_cell(task="t", requirements="do a thing", provider=provider,
                         oracle=oracle, workdir=tmp_path, compile_fn=_bad)
    assert result.accepted is False
    assert result.check_ok is False
    assert oracle.calls == [result.rust]


def test_g0_default_compile_follows_the_runner(tmp_path):
    def run(cmd, cwd, timeout, env):
        source = (cwd / "src" / "main.rs").read_text(encoding="utf-8")
        if "NOCOMPILE" in source:
            payload = {
                "reason": "compiler-message",
                "message": {"level": "error", "message": "boom", "code": None,
                            "rendered": "error: boom\n"},
            }
            return ns(101, json.dumps(payload), "")
        return ns(0, "", "")

    bad = ScriptedProvider([{"text": "```rust\nfn main() {} // NOCOMPILE\n```"}])
    oracle = FakeOracle(functional_ok=True)
    result = run_g0_cell(task="t", requirements="do a thing", provider=bad,
                         oracle=oracle, workdir=tmp_path / "bad",
                         tools=ToolRunner(runner=run, toolchain="nightly-test"))
    assert result.accepted is False
    assert oracle.calls

    good = ScriptedProvider([{"text": RUST}])
    oracle2 = FakeOracle(functional_ok=False)
    result2 = run_g0_cell(task="t", requirements="do a thing", provider=good,
                          oracle=oracle2, workdir=tmp_path / "good",
                          tools=ToolRunner(runner=run, toolchain="nightly-test"))
    assert result2.accepted is True
    assert oracle2.calls
