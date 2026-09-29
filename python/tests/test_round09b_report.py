"""B7: O3 wrong_output / livelock in the D8-14 failure-layer table.

Both map to the O3 "other" column explicitly: they are not unclassified, and
neither counts towards the deadlock rate unless O2 also hung.
"""

import json
import shutil
from pathlib import Path

import pytest

from skelnet import report

TINY = Path(__file__).parent / "fixtures" / "round08" / "tiny"
RUN = TINY / "deepseek" / "g0"


def _o3_fail(oracle: dict, category: str, *, o2: str | None = None) -> dict:
    oracle = json.loads(json.dumps(oracle))
    for name in ("O1", "O2", "O3", "O4"):
        oracle["layers"][name] = {"status": "pass", "category": None,
                                  "detail": None, "wall_ms": 1}
    if o2 is not None:
        oracle["layers"]["O2"] = {"status": "fail", "category": o2,
                                  "detail": "x", "wall_ms": 1}
        oracle["layers"]["O4"] = {"status": "not_run", "category": None,
                                  "detail": f"O2 {o2}", "wall_ms": None}
    oracle["layers"]["O3"] = {"status": "fail", "category": category,
                              "detail": "x", "wall_ms": 1}
    oracle["functional_ok"] = False
    oracle["functional_ok_no_o4"] = False
    return oracle


def _dataset(tmp_path, plan):
    """Copy the tiny G0 run and rewrite the cells named in ``plan``."""
    run = tmp_path / "g0"
    shutil.copytree(RUN, run)
    cells = sorted(run.glob("cells/*/*/*/result.json"))
    included = [p for p in cells
                if json.loads(p.read_text(encoding="utf-8"))["status"] != "skipped"]
    for path, change in zip(included, plan):
        cell = json.loads(path.read_text(encoding="utf-8"))
        cell["oracle"] = _o3_fail(cell["oracle"], *change[:1], o2=change[1])
        path.write_text(json.dumps(cell, indent=2), encoding="utf-8")
    ds = report.load_runs([run], root=TINY)
    return ds, len(included)


def _g0_row(ds):
    rows = report.table_failures(ds, report.ReportContext(root=TINY))["rows"]
    return next(row for row in rows if row["label"] == "G0")


@pytest.mark.parametrize("category", ["wrong_output", "livelock"])
def test_new_o3_categories_are_mapped_explicitly(category):
    assert report._FAIL_MAP["O3"][category] == "other"


def test_wrong_output_and_livelock_land_in_o3_other(tmp_path):
    ds, n = _dataset(tmp_path, [("wrong_output", None), ("livelock", None)] * 4)
    row = _g0_row(ds)
    assert row["columns"]["other"] == pytest.approx(8 / n)
    assert row["columns"]["output"] == 0
    assert row["columns"]["deadl"] == 0
    assert row["deadlock"] == pytest.approx(0)
    assert not [w for w in ds.warnings if w.startswith("unclassified failing layer")]


def _delta(tmp_path, change):
    """(changed row, baseline row, n): only the first cell differs."""
    base, n = _dataset(tmp_path / "base", [("wrong_output", None)])
    changed, _ = _dataset(tmp_path / "changed", [change])
    return _g0_row(changed), _g0_row(base), n, changed


def test_livelock_with_o2_hang_counts_as_deadlock_in_the_hang_column(tmp_path):
    row, base, n, _ = _delta(tmp_path, ("livelock", "hang"))
    assert row["columns"]["hang"] - base["columns"]["hang"] == pytest.approx(1 / n)
    assert row["columns"]["other"] - base["columns"]["other"] == pytest.approx(-1 / n)
    assert row["deadlock"] - base["deadlock"] == pytest.approx(1 / n)


def test_unknown_o3_category_is_other_and_warned(tmp_path):
    row, base, n, ds = _delta(tmp_path, ("schedule_output", None))
    assert row["columns"]["other"] == base["columns"]["other"]
    assert row["deadlock"] == base["deadlock"]
    assert "unclassified failing layer O3:schedule_output in 1 cell(s)" in ds.warnings
