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
    assert "Stage 0: descriptive only" in text
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


# ── F4: counts, null reasons, unavailable warnings, missing ──────────────

def test_tiny_counts_null_reasons_and_missing():
    ds = report.load_runs(_tiny_runs(), root=TINY)
    assert ds.counts["G0"] == {"included": 17, "skipped": 1, "error": 0}
    assert ds.counts["STATIC"] == {"included": 18, "skipped": 0, "error": 1}
    assert ds.counts["SKEL"] == {"included": 18, "skipped": 0, "error": 0}
    assert ds.null_reasons["SKEL"] == {"unavailable:O3": 1}
    assert any("unavailable layer O3 in 1 SKEL cell(s)" == w
               for w in ds.warnings)
    ctx = _ctx(bootstrap=1000, seed=1, look=2)
    comparison = report._comparison(ds, "SKEL", "G0", ctx)
    assert comparison["n_units"] == 17
    assert comparison["missing_reference"] == 1  # SKEL unit absent from G0
    assert comparison["missing_control"] == 0


def _copy_tiny(tmp_path):
    root = tmp_path / "tiny"
    shutil.copytree(TINY, root)
    (root / "benchmarks").mkdir(exist_ok=True)
    return root


def test_unavailable_warning_in_report_and_stop_check(tmp_path, capsys):
    root = _copy_tiny(tmp_path)
    cell_path = (root / "deepseek" / "skel" / "cells" / "lock-order"
                 / "abba_2lock" / "0" / "result.json")
    cell = json.loads(cell_path.read_text(encoding="utf-8"))
    cell["oracle"]["layers"]["O3"]["status"] = "unavailable"
    cell["oracle"]["layers"]["O3"]["category"] = "tools_unavailable"
    cell["oracle"]["functional_ok"] = None
    cell_path.write_text(json.dumps(cell, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    runs = [str(p) for p in sorted(root.glob("*/*"))
            if (p / "MANIFEST.json").exists()]
    out = tmp_path / "out"
    assert cli.main(["report", *runs, "--table", "coverage", "--out", str(out),
                     "--root", str(root)]) == 0
    report_md = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "unavailable layer O3" in report_md
    assert cli.main(["stop-check", *runs, "--look", "2", "--root", str(root),
                     "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any("unavailable layer O3" in w for w in payload["warnings"])


def test_coverage_null_reason_table(tmp_path):
    ds = report.load_runs(_tiny_runs(), root=TINY)
    payload = report.table_coverage(ds, _ctx())
    assert payload["null_reasons"]["SKEL"] == {"unavailable:O3": 1}
    md = report.render_coverage_md(payload, ds, _ctx())
    assert "functional_ok: null" in md and "unavailable:O3" in md


# ── F5: per-model / per-tier CI, 7-group Q, Wilcoxon coverage ────────────

def test_tiny_per_model_and_tier_deltas():
    ds = report.load_runs(_tiny_runs(), root=TINY)
    ctx = _ctx(bootstrap=1000, seed=1, look=2)
    payload = report.table_tests(ds, ctx)
    comparison = next(r for r in payload["rows"] if r["control"] == "G0")
    # DeepSeek: b=4,c=1 over 8 paired units; GPT: b=3,c=2 over 9.
    assert comparison["per_model_stats"]["deepseek-flash"]["delta"] == \
        pytest.approx((4 - 1) / 8 * 100)
    assert comparison["per_model_stats"]["gpt-6-luna"]["delta"] == \
        pytest.approx((3 - 2) / 9 * 100)
    # L1: b=2,c=2 over 6 -> 0; L2: b=2,c=0 over 5 -> +40;
    # L3: b=3,c=1 over 6 -> +33.3.
    tiers = comparison["per_tier_stats"]
    assert tiers["L1"]["delta"] == pytest.approx(0.0, abs=1e-9)
    assert tiers["L2"]["delta"] == pytest.approx(2 / 5 * 100)
    assert tiers["L3"]["delta"] == pytest.approx(2 / 6 * 100)
    for tier in ("L1", "L2", "L3"):
        entry = tiers[tier]
        assert entry["ci_low"] <= entry["delta"] <= entry["ci_high"]
    again = next(r for r in report.table_tests(ds, ctx)["rows"]
                 if r["control"] == "G0")
    assert again["per_tier_stats"]["L3"]["ci_low"] == tiers["L3"]["ci_low"]


def test_seven_group_cochran_requires_full_coverage(tmp_path):
    ds = report.load_runs(_tiny_runs(), root=TINY)
    ctx = _ctx()
    payload = report.table_tests(ds, ctx)
    # tiny has no DYNAMIC_M, so the 7-group Q must be -- with a coverage note.
    entry = payload["dynamic_m_q"]["deepseek-flash"]
    assert entry["Q"] is None and entry["total"] == 0


def test_seven_group_cochran_planted(tmp_path):
    root = tmp_path / "planted"
    synth = _load_synth()
    synth.make_runs(root, synth.planted_spec())
    runs = sorted(p for p in root.glob("*/*") if (p / "MANIFEST.json").exists())
    ds = report.load_runs(runs, root=root)
    payload = report.table_tests(ds, _ctx(root=root, bootstrap=500, seed=1))
    for model in ("gpt-6-luna", "kimi-k3", "deepseek-flash", "qwen3.8-flash"):
        entry = payload["dynamic_m_q"][model]
        assert entry["Q"] is not None and entry["covered"] == entry["total"]
    md = report.render_tests_md(payload, ds, _ctx(root=root))
    assert "Cochran's Q over the 7 groups" in md


def _load_synth():
    import importlib.util
    spec = importlib.util.spec_from_file_location("r8synth", FIXTURES / "synth.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wilcoxon_covers_all_comparisons(tmp_path):
    root = tmp_path / "planted"
    synth = _load_synth()
    synth.make_runs(root, synth.planted_spec())
    runs = sorted(p for p in root.glob("*/*") if (p / "MANIFEST.json").exists())
    ds = report.load_runs(runs, root=root)
    payload = report.table_tests(ds, _ctx(root=root, bootstrap=200, seed=1))
    assert len(payload["metrics"]) == 10
    for key, metric in payload["metrics"].items():
        assert metric["tokens"] is not None, key
        assert metric["calls"] is not None, key


# ── F6: lockbud 2x2 ──────────────────────────────────────────────────────

def test_tiny_lockbud_hand_values():
    ds = report.load_runs(_tiny_runs(), root=TINY)
    payload = report.table_lockbud(ds, _ctx())
    joined = payload["joined"]
    assert joined["no_g0"] == 1
    assert (joined["tp"], joined["fp"], joined["fn"], joined["tn"]) == (0, 8, 2, 7)
    assert joined["excluded"] == 0 and joined["unavailable"] == 0
    assert payload["ratios"]["recall"] == 0.0
    assert payload["ratios"]["fp_on_ok"] == pytest.approx(7 / 9)
    assert payload["ratios"]["report_on_not_deadlock"] == pytest.approx(8 / 15)
    md = report.render_lockbud_md(payload, ds, _ctx())
    assert "no_g0" in md and "report on not-deadlock" in md


def _raw_cell(model_id, arm, task, rep, ok, *, accepted=False, baseline=None,
              oracle_extra=None, tool_ms=None):
    oracle = {"built": True, "ran": True, "run_ok": True,
              "functional_ok": ok, "functional_ok_no_o4": ok,
              "terminal_check": "pass" if ok else "fail",
              "oracle_complete": True, "layers": {}}
    if oracle_extra:
        oracle.update(oracle_extra)
    raw = {
        "schema_version": "skelnet-cell-v1", "arm": arm, "model": "M",
        "model_id": model_id, "task": task, "tier": "L1", "hint": "h1",
        "rep": rep, "seed": 1, "status": "ok", "skip_reason": None,
        "error": None, "accepted": accepted, "parse_ok": True,
        "check_ok": True, "rounds_used": 1, "history": [], "ledger": {},
        "evidence_sufficient": accepted, "rust_mode": "llm", "calls": [],
        "budget_used": {"calls": 0, "tokens": 0}, "oracle": oracle,
    }
    if baseline is not None:
        raw["baseline"] = baseline
    if tool_ms is not None:
        raw["compile_wall_ms"] = tool_ms
    return raw


def test_lockbud_v1_not_compiled_is_excluded(tmp_path):
    baseline = {"rounds": [
        {"call": 1, "stage": "generate", "reply_kind": "program", "version": 1,
         "compiled": False, "compile": "error",
         "tools": {"lockbud": {"status": "fail", "category": "ConflictLock"}},
         "feedback_sha256": "x", "feedback_bytes": 0, "truncated": False},
        {"call": 2, "stage": "rust_fix", "reply_kind": "program", "version": 2,
         "compiled": True, "compile": "ok",
         "tools": {"lockbud": {"status": "fail", "category": "ConflictLock"}},
         "feedback_sha256": "x", "feedback_bytes": 0, "truncated": False},
    ], "accepted_at_call": None, "accept_reason": "budget_exhausted",
        "final_version": 2, "first_round_cache_hit": False, "tools_missing": []}
    cells = [
        report._make_cell(_raw_cell("m", "G0", "t", 0, False), "r", "G0",
                          tmp_path),
        report._make_cell(_raw_cell("m", "STATIC", "t", 0, False,
                                    baseline=baseline), "r", "STATIC", tmp_path),
    ]
    ds = report.Dataset(cells=cells, run_ids=["r"], git_sha="x")
    payload = report.table_lockbud(ds, _ctx(root=tmp_path))
    assert payload["joined"]["excluded"] == 1
    assert payload["joined"]["tp"] + payload["joined"]["fp"] == 0


# ── F8: cost, prices, cache hits, G0 tool time ───────────────────────────

def test_cost_reads_g0_top_level_compile_wall_ms(tmp_path):
    cell = report._make_cell(_raw_cell("m", "G0", "t", 0, True,
                                       tool_ms=1234), "r", "G0", tmp_path)
    ds = report.Dataset(cells=[cell], run_ids=["r"], git_sha="x")
    payload = report.table_cost(ds, _ctx(root=tmp_path))
    g0 = next(r for r in payload["rows"] if r["label"] == "G0")
    assert g0["tool_ms"] == 1234


def test_cost_missing_price_warns_and_dashes_model(tmp_path):
    ds = report.load_runs(_tiny_runs(), root=TINY)
    prices = {"currency": "USD", "per_million": {
        "deepseek-flash": {"input": 1.0, "output": 2.0}}}
    ctx = _ctx(root=TINY, prices=prices)
    payload = report.table_cost(ds, ctx)
    assert payload["prices"]["missing"] == ["gpt-6-luna"]
    assert any("missing prices for gpt-6-luna" in w for w in ds.warnings)
    md = report.render_cost_md(payload, ds, ctx)
    assert "missing prices for gpt-6-luna" in md
    for label, entry in payload["prices"]["by_model"].items():
        if "gpt-6-luna" in entry:
            assert payload["prices"]["totals"][label] is None


def test_cost_cache_hit_table_tiny():
    ds = report.load_runs(_tiny_runs(), root=TINY)
    payload = report.table_cost(ds, _ctx())
    static = next(r for r in payload["rows"] if r["label"] == "STATIC")
    # Every STATIC cell's first round is a shared-cache hit.
    assert static["cache_hit_calls"] == 18
    assert static["cache_hit_billable"] > 0
    md = report.render_cost_md(payload, ds, _ctx())
    assert "Cache-hit calls" in md and "D8-12" in md


# ── F9: check@1, Cochran groups, tokens/correct ──────────────────────────

def test_check_at_1_skel_and_cir(tmp_path):
    def cell(arm, history):
        raw = _raw_cell("m", arm, "t", 0, False)
        raw["history"] = history
        return report._make_cell(raw, "r", arm, tmp_path)

    assert report._check_at_1(cell("SKEL", [
        {"attempt": 1, "stage": "check", "status": "error"}]) ) is False
    assert report._check_at_1(cell("SKEL", [
        {"attempt": 1, "stage": "verify", "outcome": "PASS",
         "complete": True}]) ) is True
    assert report._check_at_1(cell("CIR", [
        {"attempt": 1, "stage": "verify", "outcome": "INVALID",
         "complete": False}]) ) is False
    assert report._check_at_1(cell("CIR", [
        {"attempt": 1, "stage": "verify", "outcome": "PASS",
         "complete": True}]) ) is True
    cells = [cell("SKEL", [{"attempt": 1, "stage": "check", "status": "error"}]),
             cell("SKEL", [{"attempt": 1, "stage": "verify", "outcome": "PASS",
                            "complete": True}])]
    ds = report.Dataset(cells=cells, run_ids=["r"], git_sha="x")
    payload = report.table_design(ds, _ctx(root=tmp_path))
    skel = next(r for r in payload["rows"] if r["label"] == "SKEL")
    assert skel["check"] == pytest.approx(0.5)


def test_cochran_q_group_set(tmp_path):
    groups = ["SKEL", "CIR", "G0", "REFINE", "STATIC", "DYNAMIC"]
    pattern = {
        0: {"SKEL": True, "CIR": True},
        1: {"G0": True, "REFINE": True, "STATIC": True},
    }
    cells = []
    for block, outcomes in pattern.items():
        for group in groups:
            ok = outcomes.get(group, False)
            cells.append(report._make_cell(
                _raw_cell("m", group, f"t{block}", 0, ok), "r", group,
                tmp_path))
    ds = report.Dataset(cells=cells, run_ids=["r"], git_sha="x")
    payload = report.table_main(ds, _ctx(root=tmp_path, bootstrap=100, seed=1))
    q = payload["cochran"]["m"]["Q"]
    # blocks: [1,1,0,0,0,0], [0,0,1,1,1,0]; k=6, T=5, sum R^2=13,
    # Q = (5)*(6*5 - 25)/(6*5 - 13) = 25/17.
    assert q == pytest.approx(25 / 17)


def test_tokens_correct_uses_ok_not_accepted(tmp_path):
    cells = []
    specs = [("a", True, False), ("b", False, True), ("c", False, True)]
    for name, accepted, ok in specs:
        raw = _raw_cell("m", "G0", name, 0, ok, accepted=accepted)
        raw["calls"] = [{"usage": {"input": 1000, "output": 0,
                                   "reasoning": 0, "cached": 0}}]
        cells.append(report._make_cell(raw, "r", "G0", tmp_path))
    ds = report.Dataset(cells=cells, run_ids=["r"], git_sha="x")
    payload = report.table_cost(ds, _ctx(root=tmp_path))
    g0 = next(r for r in payload["rows"] if r["label"] == "G0")
    # total billable 3000 over 2 ok programs (accepted count is 1).
    assert g0["tokens_correct"] == pytest.approx(1500)


# ── G8: tiers unclassified and anytime codegen exclusion ─────────────────

def test_tiers_unclassified_column(tmp_path):
    specs = [("L1", True), (None, True), (None, False)]
    cells = []
    for index, (tier, ok) in enumerate(specs):
        raw = _raw_cell("m", "G0", f"t{index}", 0, ok)
        raw["tier"] = tier
        cells.append(report._make_cell(raw, "r", "G0", tmp_path))
    ds = report.Dataset(cells=cells, run_ids=["r"], git_sha="x")
    payload = report.table_tiers(ds, _ctx(root=tmp_path))
    row = next(r for r in payload["rows"] if r["label"] == "G0")
    assert row["L1"] == pytest.approx(1.0)
    assert row["unclassified"] == pytest.approx(1 / 2)
    md = report.render_tiers_md(payload, ds, _ctx(root=tmp_path))
    assert "unclassified" in md


def test_anytime_excludes_codegen(tmp_path):
    normal = _raw_cell("m", "G0", "t", 0, True)
    codegen = _raw_cell("m", "G0", "t2", 0, True)
    codegen["rust_mode"] = "codegen"
    cells = [report._make_cell(normal, "r", "G0", tmp_path),
             report._make_cell(codegen, "r", "G0", tmp_path)]
    ds = report.Dataset(cells=cells, run_ids=["r"], git_sha="x")
    payload = report.anytime_data(ds, _ctx(root=tmp_path))
    series = next(s for s in payload["series"] if s["label"] == "G0")
    assert series["points"][-1]["n"] == 1
    assert payload["excluded_codegen"] == 1
