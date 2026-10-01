"""R9d-P5: the read-only program-feature counter.

`report.program_feature_counts` scans each run's final `cells/**/candidate.rs`
for `thread::scope`, `thread::Builder`, `yield_now` and `sleep`; Look 0 exposes
it so Stage 1 can check that the R9d fixes took effect.
"""

import json
import shutil
from pathlib import Path

from skelnet import cli, report

TINY = Path(__file__).parent / "fixtures" / "round08" / "tiny" / "deepseek" / "skel"


def _synthetic_run(root: Path, arm: str, programs: dict) -> Path:
    run = root / f"run-{arm}"
    (run / "cells" / "lock-order" / "abba_2lock").mkdir(parents=True)
    (run / "MANIFEST.json").write_text(json.dumps({"arm": arm, "run_id": run.name}),
                                       encoding="utf-8")
    for rep, source in programs.items():
        cell = run / "cells" / "lock-order" / "abba_2lock" / str(rep)
        cell.mkdir()
        (cell / "candidate.rs").write_text(source, encoding="utf-8")
    return run


def test_program_feature_counts_per_arm(tmp_path):
    good = "fn main() { let h = std::thread::spawn(|| {}); h.join().unwrap(); }"
    skel = ("fn main() { let h = std::thread::Builder::new().spawn(|| {}).unwrap(); "
            "while !flag { std::hint::spin_loop(); } h.join().unwrap(); }")
    bad = "fn main() { std::thread::scope(|s| { s.spawn(|| {}); }); }"
    r_skel = _synthetic_run(tmp_path, "SKEL", {0: skel})
    r_g0 = _synthetic_run(tmp_path, "G0", {0: good, 1: bad})

    counts = report.program_feature_counts([r_skel, r_g0])
    assert counts["programs"] == 3
    assert counts["totals"]["thread_builder"] == 1
    assert counts["totals"]["thread_scope"] == 1
    assert counts["by_arm"]["SKEL"]["thread_builder"] == 1
    assert counts["by_arm"]["SKEL"]["thread_scope"] == 0
    assert counts["by_arm"]["G0"]["thread_scope"] == 1
    assert counts["by_arm"]["G0"]["programs"] == 2


def test_program_feature_counts_yield_and_sleep(tmp_path):
    src = ("fn main() { std::thread::yield_now(); std::thread::sleep(1); "
           "sleep(2); }")
    run = _synthetic_run(tmp_path, "STATIC", {0: src})
    counts = report.program_feature_counts([run])
    assert counts["totals"]["yield_now"] == 1
    assert counts["totals"]["sleep"] == 2


def test_look0_includes_program_features(tmp_path, capsys):
    # Reuse the committed tiny run (a valid cell) and drop one Builder program.
    run = tmp_path / "run"
    shutil.copytree(TINY, run)
    cell = run / "cells" / "lock-order" / "abba_2lock" / "0"
    (cell / "candidate.rs").write_text(
        "fn main() { let h = std::thread::Builder::new().spawn(|| {}).unwrap(); "
        "h.join().unwrap(); }", encoding="utf-8")

    rc = cli.main(["stop-check", str(run), "--look", "0", "--root", str(tmp_path),
                   "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "program_features" in payload
    assert payload["program_features"]["totals"]["thread_builder"] == 1
    assert payload["program_features"]["totals"]["thread_scope"] == 0
