"""B4: real Shuttle / miri on a lost update and a correct busy-wait.

The fixtures are independent copies of the atomic-data/atomic_lost_update and
lock-order/partial_deadlock_bystander tasks (contract, gold, requirements and
the reference programs); nothing here reads benchmarks/.
"""

import json
import shutil
from pathlib import Path

from skelnet import cli
from skelnet.oracle import RustOracle

from round03_helpers import rust_tools

FIXTURES = Path(__file__).parent / "fixtures" / "round09b"
LOST = FIXTURES / "lost_update"
SPIN = FIXTURES / "spin_bystander"
TIMEOUT = 90.0


def _run(task_dir: Path, program: str, workdir: Path):
    oracle = RustOracle(terminal=cli.read_terminal(task_dir), task_dir=task_dir,
                        layers=("O1", "O2", "O3"), stress_runs=2,
                        timeout=TIMEOUT)
    source = (task_dir / "rust" / program).read_text(encoding="utf-8")
    return oracle.evaluate(source, workdir)


@rust_tools
def test_lost_update_is_caught_deterministically_by_o3(tmp_path):
    assert cli.read_terminal(LOST) == "DONE c=2"
    first = _run(LOST, "buggy.rs", tmp_path / "a")
    second = _run(LOST, "buggy.rs", tmp_path / "b")
    for result in (first, second):
        o3 = result.layers["O3"]
        assert (o3.status, o3.category) == ("fail", "wrong_output"), o3.to_dict()
        assert result.functional_ok is False
    wrong_a = first.layers["O3"].data["shuttle"]["schedules_wrong"]
    wrong_b = second.layers["O3"].data["shuttle"]["schedules_wrong"]
    assert wrong_a == wrong_b > 0
    failure = (tmp_path / "a" / "shuttle" / "failure.txt").read_text(encoding="utf-8")
    assert failure.startswith("output mismatch in schedule ")
    assert "expected last line: 'DONE c=2'" in failure
    assert str(tmp_path) not in failure


@rust_tools
def test_lost_update_reference_explores_every_schedule(tmp_path):
    result = _run(LOST, "fixed.rs", tmp_path)
    o3 = result.layers["O3"]
    shuttle = o3.data["shuttle"]
    assert (o3.status, o3.category) == ("pass", None), o3.to_dict()
    assert shuttle["output_check"] == "pass"
    assert shuttle["pct_completed"] == 2000
    assert shuttle["random_completed"] == 2000
    assert shuttle["pct_abandoned"] == 0
    assert shuttle["schedules_wrong"] == 0


@rust_tools
def test_busy_wait_reference_passes_with_few_abandoned_pct_runs(tmp_path):
    result = _run(SPIN, "fixed.rs", tmp_path)
    o3 = result.layers["O3"]
    shuttle = o3.data["shuttle"]
    assert (o3.status, o3.category) == ("pass", None), o3.to_dict()
    assert shuttle["random_completed"] == 2000
    # Measured at 4 with the oracle seed; PCT starves the spinner rarely.
    assert 0 < shuttle["pct_abandoned"] < 100
    assert shuttle["output_check"] == "pass"
    assert result.functional_ok_no_o4 is True


@rust_tools
def test_permanent_spin_is_livelock_not_panic(tmp_path):
    result = _run(SPIN, "buggy.rs", tmp_path)
    assert result.layers["O2"].category == "hang"
    shuttle = result.layers["O3"].data["shuttle"]
    assert (shuttle["status"], shuttle["category"]) == ("fail", "livelock")
    assert shuttle["detail"].startswith("exceeded max_steps bound 1000000")
    assert shuttle["wall_ms"] < 120_000
    assert result.layers["O3"].status == "fail"
    assert result.layers["O3"].category == "livelock"


@rust_tools
def test_calibrate_cli_matches_both_fixtures(tmp_path):
    fixtures = tmp_path / "fixtures"
    for task_dir in (LOST, SPIN):
        shutil.copytree(task_dir, fixtures / task_dir.name)
    out = tmp_path / "out"
    rc = cli.main(["oracle", "calibrate", "--fixtures", str(fixtures),
                   "--out", str(out), "--layers", "O1,O2,O3",
                   "--timeout", str(int(TIMEOUT))])
    document = json.loads((out / "CALIBRATION.json").read_text(encoding="utf-8"))
    assert rc == 0, document["summary"]
    assert document["summary"]["mismatched"] == 0
    programs = {(task["task"], p["program"]): p
                for task in document["tasks"] for p in task["programs"]}
    assert programs[("lost_update", "buggy.rs")]["layers"]["O3"]["category"] == "wrong_output"
    assert programs[("spin_bystander", "buggy.rs")]["layers"]["O2"]["category"] == "hang"
    assert programs[("spin_bystander", "fixed.rs")]["o3_shuttle"]["pct_abandoned"] > 0
