"""R9d-P3: the instrumenter rewrites `thread::Builder` spawns.

The Stage-0 pilot had 9 Builder programs whose O4 was `instrument_unsupported`.
The instrumenter now rewrites `Builder::new()[.name(..)][.stack_size(..)].spawn`
to `crate::cir_trace::builder_spawn`, which returns `io::Result<JoinHandle>` so a
trailing `.unwrap()` still compiles. These tests run the real oracle (gated on
rust tools).
"""

import json
from pathlib import Path

import pytest

from skelnet import cli
from skelnet.oracle import RustOracle

from round03_helpers import rust_tools

FIXTURES = Path(__file__).parent / "fixtures" / "round09d" / "builder_spawns"
REPO = Path(__file__).resolve().parents[2]
META = json.loads((FIXTURES / "meta.json").read_text(encoding="utf-8"))


def _evaluate(program: str, task: str, workdir: Path):
    task_dir = REPO / "benchmarks" / "tasks" / task
    oracle = RustOracle(terminal=cli.read_terminal(task_dir), task_dir=task_dir,
                        layers=("O1", "O2", "O4"), stress_runs=2, monitor_runs=1)
    return oracle.evaluate(program, workdir)


@rust_tools
def test_builder_abba_reference_passes_o4(tmp_path):
    program = (FIXTURES / "qwen-g0__lock-order__abba_2lock.rs").read_text(
        encoding="utf-8")
    assert "Builder" in program
    result = _evaluate(program, "lock-order/abba_2lock", tmp_path / "abba")
    o4 = result.layers["O4"]
    assert o4.status == "pass", o4.to_dict()
    assert o4.category != "instrument_unsupported", o4.to_dict()


@rust_tools
@pytest.mark.parametrize("slug", sorted(META))
def test_stage0_builder_programs_are_instrumented(tmp_path, slug):
    entry = META[slug]
    program = (FIXTURES / f"{slug}.rs").read_text(encoding="utf-8")
    result = _evaluate(program, entry["task"], tmp_path / slug)
    o4 = result.layers["O4"]
    assert not (o4.status == "unsupported"
                and o4.category == "instrument_unsupported"), o4.to_dict()
