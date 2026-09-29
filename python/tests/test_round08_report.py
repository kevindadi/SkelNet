"""T5/T6/T8: loading, derived fields, tables and the report CLI."""

import json
import shutil
from pathlib import Path

import pytest

from skelnet import cli, report

FIXTURES = Path(__file__).parent / "fixtures" / "round08"
TINY = FIXTURES / "tiny"


def _tiny_runs():
    return sorted(p for p in TINY.glob("*/*") if (p / "MANIFEST.json").exists())


def _ctx(root=TINY, **kwargs):
    return report.ReportContext(root=root, **kwargs)


# ── T5: loading and derived fields ───────────────────────────────────────

def test_load_rejects_non_run_dir(tmp_path):
    (tmp_path / "not-a-run").mkdir()
    with pytest.raises(report.ReportInputError):
        report.load_runs([tmp_path / "not-a-run"], root=tmp_path)


def test_load_rejects_duplicate_cells(tmp_path):
    first = _tiny_runs()[0]
    with pytest.raises(report.ReportInputError):
        report.load_runs([first, first], root=TINY)


def test_load_allows_duplicates_with_flag(tmp_path):
    first = _tiny_runs()[0]
    ds = report.load_runs([first, first], root=TINY, allow_duplicates=True)
    assert any("duplicate" in warning for warning in ds.warnings)


def test_load_rejects_inconsistent_run_params(tmp_path):
    runs = _tiny_runs()
    copied = tmp_path / "copy"
    shutil.copytree(runs[0], copied)
    manifest_path = copied / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_params"]["call_budget"] = 9
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for cell_path in copied.glob("cells/**/result.json"):
        cell = json.loads(cell_path.read_text(encoding="utf-8"))
        cell["model_id"] = "copy-model"
        cell["model"] = "Copy Model"
        cell_path.write_text(json.dumps(cell), encoding="utf-8")
    with pytest.raises(report.ReportInputError):
        report.load_runs([runs[0], copied], root=TINY)
    ds = report.load_runs([runs[0], copied], root=TINY, allow_mixed=True)
    assert any("call_budget" in message for message in ds.mixed)


def test_tiny_derived_fields():
    ds = report.load_runs(_tiny_runs(), root=TINY)
    assert ds.n_skipped == 1 and ds.n_error == 1
    index = {(c.model_id, c.label, c.task, c.rep): c for c in ds.cells}
    skipped = index[("deepseek-flash", "G0", "condvar/lost_wakeup", 0)]
    assert skipped.included is False
    error = index[("deepseek-flash", "STATIC", "condvar/lost_wakeup", 0)]
    assert error.included is True and error.ok is False
    null = index[("deepseek-flash", "SKEL", "condvar/lost_wakeup", 0)]
    assert null.ok is False and null.coverage["functional_null"] is True
    g0 = index[("deepseek-flash", "G0", "lock-order/abba_2lock", 0)]
    assert g0.final_call == 1
    skel = index[("deepseek-flash", "SKEL", "lock-order/abba_2lock", 0)]
    assert skel.final_call == 2
    no_conc = index[("deepseek-flash", "SKEL", "lock-order/abba_2lock", 0)]
    assert no_conc.coverage["no_concurrency"] is True
    assert null.coverage["oracle_complete_false"] is True


def test_tiny_main_table_values():
    ds = report.load_runs(_tiny_runs(), root=TINY)
    ctx = _ctx(bootstrap=1000, seed=1, look=2)
    payload = report.table_main(ds, ctx)
    rows = {row["label"]: row for row in payload["rows"]}
    assert rows["SKEL"]["pooled"] == pytest.approx(13 / 18)
    assert rows["G0"]["pooled"] == pytest.approx(9 / 17)
    assert rows["STATIC"]["pooled"] == pytest.approx(9 / 18)
    g0 = payload["comparisons"]["G0"]
    assert g0["b"] == 7 and g0["c"] == 3
    assert g0["p"] == pytest.approx(0.34375)
    assert g0["delta"] == pytest.approx((7 - 3) / 17 * 100)
    static = payload["comparisons"]["STATIC"]
    assert static["b"] == 7 and static["c"] == 3
    assert static["delta"] == pytest.approx((7 - 3) / 18 * 100)
    assert payload["pass3"]["pooled"] == pytest.approx(1.0)
    assert rows["SKEL"]["sens"] == pytest.approx(14 / 18)


def test_tiny_failure_and_coverage_tables():
    ds = report.load_runs(_tiny_runs(), root=TINY)
    ctx = _ctx()
    failures = report.table_failures(ds, ctx)
    by_label = {row["label"]: row for row in failures["rows"]}
    assert by_label["G0"]["columns"]["build"] == pytest.approx(1 / 17)
    assert by_label["G0"]["deadlock"] == pytest.approx(2 / 17)
    coverage = report.table_coverage(ds, ctx)
    skel = next(row for row in coverage["rows"] if row["label"] == "SKEL")
    assert skel["functional_null"] == pytest.approx(1 / 18)
    assert skel["no_concurrency"] == pytest.approx(1 / 18)


def test_tiers_reads_origin(tmp_path):
    runs = _tiny_runs()
    synth_tasks = [
        {"task": "lock-order/abba_2lock", "tier": "L1", "origin": "classic"},
        {"task": "condvar/lost_wakeup", "tier": "L2", "origin": "disguised"},
    ]
    # The tiny cells reference three tasks; write the origin for two.
    import importlib.util
    spec = importlib.util.spec_from_file_location("r8synth", FIXTURES / "synth.py")
    synth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synth)
    root = tmp_path / "repo"
    synth.write_fake_tasks(root, synth_tasks + [
        {"task": "semaphore/permits", "tier": "L3", "origin": "classic"}])
    ds = report.load_runs(runs, root=root)
    payload = report.table_tiers(ds, _ctx(root=root))
    skel = next(row for row in payload["rows"] if row["label"] == "SKEL")
    assert skel["classic"] is not None and skel["disguised"] is not None


def test_benchmark_table_fake_repo(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("r8synth", FIXTURES / "synth.py")
    synth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synth)
    root = tmp_path / "repo"
    synth.write_fake_tasks(root, [
        {"task": "lock-order/a", "tier": "L1", "origin": "classic"},
        {"task": "lock-order/b", "tier": "L1", "origin": "classic"},
        {"task": "condvar/c", "tier": "L1", "origin": "classic"},
        {"task": "boundary/x", "tier": None, "origin": None},
    ])
    payload = report.table_benchmark(report.Dataset([], [], "x"), _ctx(root=root))
    rows = {row["family"]: row for row in payload["rows"]}
    assert rows["lock-order"]["L1"] == 2
    assert rows["condvar"]["L1"] == 1
    assert payload["boundary"] == 1
    assert payload["total"]["L2"] == 12 and payload["total"]["L3"] == 8


# ── T8: the report CLI ───────────────────────────────────────────────────

@pytest.mark.parametrize("table", report.ALL_TABLES)
def test_cli_each_table(tmp_path, table):
    out = tmp_path / table
    rc = cli.main(["report", *[str(p) for p in _tiny_runs()],
                   "--table", table, "--format", "both", "--out", str(out)])
    assert rc == 0
    assert (out / report.TEX_PATHS[table]).exists()
    assert (out / "REPORT.md").exists()
    assert (out / "report.json").exists()


def test_cli_all_tables_and_figure(tmp_path):
    out = tmp_path / "all"
    rc = cli.main(["report", *[str(p) for p in _tiny_runs()],
                   "--table", "all", "--figure", "anytime", "--out", str(out)])
    assert rc == 0
    assert (out / "figures" / "anytime.tex").exists()
    assert (out / "data" / "anytime.csv").exists()


@pytest.mark.parametrize("fmt", ["md", "tex", "both"])
def test_cli_formats(tmp_path, fmt):
    out = tmp_path / fmt
    rc = cli.main(["report", *[str(p) for p in _tiny_runs()],
                   "--table", "main", "--format", fmt, "--out", str(out)])
    assert rc == 0
    assert (out / "tables" / "main.tex").exists() == (fmt in ("tex", "both"))


def test_cli_legacy_path_is_unchanged(tmp_path, capsys):
    run = tmp_path / "run"
    (run / "cells").mkdir(parents=True)
    summary = {"run_id": "run", "arm": "G0", "model": "DeepSeek Flash",
               "cells": [{"parse_ok": True, "oracle": {"functional_ok": True}}]}
    (run / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
    (run / "MANIFEST.json").write_text(json.dumps({"run_id": "run"}),
                                       encoding="utf-8")
    rc = cli.main(["report", str(run)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.rstrip("\n") == cli._report_markdown([summary]).rstrip("\n")


def test_cli_non_run_dir_exit_2(tmp_path, capsys):
    (tmp_path / "nope").mkdir()
    rc = cli.main(["report", str(tmp_path / "nope"), "--table", "main"])
    assert rc == 2


def test_cli_duplicate_exit_2(tmp_path):
    run = str(_tiny_runs()[0])
    rc = cli.main(["report", run, run, "--table", "main"])
    assert rc == 2
    rc = cli.main(["report", run, run, "--table", "main", "--allow-duplicates"])
    assert rc == 0


def test_cli_look0_hides_tests(tmp_path):
    out = tmp_path / "look0"
    rc = cli.main(["report", *[str(p) for p in _tiny_runs()],
                   "--table", "main", "--look", "0", "--out", str(out)])
    assert rc == 0
    text = (out / "tables" / "main.tex").read_text(encoding="utf-8")
    assert "Stage 0: descriptive only" not in text  # footnote still numeric
    # delta/CI/p columns are all -- for the G0 row
    g0 = next(line for line in text.splitlines() if line.startswith("\\arm{G0}"))
    assert "-- & -- & --" in g0


def test_cli_prices_hand_computed(tmp_path):
    run = tmp_path / "one"
    (run / "cells" / "t" / "0").mkdir(parents=True)
    cell = json.loads((_tiny_runs()[0] / "cells" / "lock-order" / "abba_2lock"
                       / "0" / "result.json").read_text(encoding="utf-8"))
    cell["task"] = "t"
    cell["calls"][0]["usage"] = {"input": 1_000_000, "output": 500_000,
                                 "reasoning": 0, "cached": 200_000}
    (run / "cells" / "t" / "0" / "result.json").write_text(
        json.dumps(cell), encoding="utf-8")
    manifest = json.loads((_tiny_runs()[0] / "MANIFEST.json").read_text(
        encoding="utf-8"))
    manifest["tasks"]["selected"] = ["t"]
    manifest["reps"] = 1
    (run / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({
        "currency": "USD",
        "per_million": {cell["model_id"]: {"input": 1.0, "output": 2.0,
                                           "cached_input": 0.5}}}),
        encoding="utf-8")
    out = tmp_path / "out"
    rc = cli.main(["report", str(run), "--table", "cost", "--out", str(out),
                   "--prices", str(prices)])
    assert rc == 0
    md = (out / "REPORT.md").read_text(encoding="utf-8")
    # (1e6 - 0.2e6)*1 + 0.2e6*0.5 + 0.5e6*2 = 0.8e6 + 0.1e6 + 1.0e6 = 1.9e6 /1e6
    assert "1.90" in md
