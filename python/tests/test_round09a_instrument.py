"""A1: a MutexGuard signature still passes O4 after instrumentation."""

from pathlib import Path

from round03_helpers import rust_tools
from skelnet import cli
from skelnet.oracle import RustOracle

FIXTURE = Path(__file__).parent / "fixtures" / "round09a" / "mutexguard"


@rust_tools
def test_mutexguard_signature_o4_passes(tmp_path):
    source = (FIXTURE / "rust" / "fixed.rs").read_text(encoding="utf-8")
    oracle = RustOracle(
        terminal=cli.read_terminal(FIXTURE), task_dir=FIXTURE,
        layers=("O1", "O2", "O4"), stress_runs=1, monitor_runs=1)
    result = oracle.evaluate(source, tmp_path)
    o4 = result.layers["O4"]
    assert result.layers["O1"].status == "pass", result.layers["O1"].to_dict()
    assert result.layers["O2"].status == "pass", result.layers["O2"].to_dict()
    assert (o4.status, o4.category) == ("pass", None), o4.to_dict()
