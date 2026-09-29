"""T9: the staged stopping rules and the stop-check CLI."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from skelnet import cli, report, stop_check

FIXTURES = Path(__file__).parent / "fixtures" / "round08"
_spec = importlib.util.spec_from_file_location("r8synth", FIXTURES / "synth.py")
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)

SUCCESS = {"SKEL": 0.85, "CIR": 0.7, "G0": 0.5, "REFINE": 0.5, "STATIC": 0.5,
           "DYNAMIC": 0.5, "DYNAMIC_M": 0.85, "SKEL-outcome": 0.6}
FUTILITY = {"SKEL": 0.4, "CIR": 0.4, "G0": 0.6, "REFINE": 0.6, "STATIC": 0.6,
            "DYNAMIC": 0.6, "DYNAMIC_M": 0.6, "SKEL-outcome": 0.4}
CONTINUE = {"SKEL": 0.55, "CIR": 0.55, "G0": 0.5, "REFINE": 0.5,
            "STATIC": 0.5, "DYNAMIC": 0.5, "DYNAMIC_M": 0.55,
            "SKEL-outcome": 0.5}


def _build(root, rates):
    shutil.rmtree(root, ignore_errors=True)
    spec = dict(synth.planted_spec())
    spec["rates"] = rates
    synth.make_runs(root, spec)
    synth.write_fake_tasks(root, spec["tasks"])
    return sorted(p for p in Path(root).glob("*/*")
                  if (p / "MANIFEST.json").exists())


def _edit_skel(root, predicate):
    for path in Path(root).glob("*/*"):
        if not (path / "MANIFEST.json").exists():
            continue
        manifest = json.loads((path / "MANIFEST.json").read_text(encoding="utf-8"))
        label = "SKEL-outcome" if (
            manifest["arm"] == "SKEL"
            and manifest["run_params"]["feedback_mode"] == "outcome_only") \
            else manifest["arm"]
        if label != "SKEL":
            continue
        for task in manifest["tasks"]["selected"]:
            for rep in range(manifest["reps"]):
                cell_path = path / "cells" / task / str(rep) / "result.json"
                cell = json.loads(cell_path.read_text(encoding="utf-8"))
                if predicate(manifest, task, rep, cell):
                    cell_path.write_text(
                        json.dumps(cell, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")


def _verdict(root):
    runs = sorted(p for p in Path(root).glob("*/*")
                  if (p / "MANIFEST.json").exists())
    ctx = report.ReportContext(root=Path(root), look=2, planned_units=144)
    ds = report.load_runs(runs, root=Path(root))
    return stop_check.look23(ds, ctx)


def test_look2_success(tmp_path):
    root = tmp_path / "success"
    _build(root, SUCCESS)
    result = _verdict(root)
    assert result["verdict"] == "success"
    for key in ("1_holm", "2_per_model", "3_l2l3", "4_sensitivity", "5_ci"):
        assert result["criteria"][key]["ok"] is True


def test_look2_futility(tmp_path):
    root = tmp_path / "futility"
    _build(root, FUTILITY)
    assert _verdict(root)["verdict"] == "futility"


def test_look2_continue(tmp_path):
    root = tmp_path / "continue"
    _build(root, CONTINUE)
    result = _verdict(root)
    assert result["verdict"] == "continue"
    assert result["criteria"]["1_holm"]["ok"] is False


def test_criterion2_only_counterexample(tmp_path):
    root = tmp_path / "c2"
    _build(root, SUCCESS)
    # Boost STATIC in two models so SKEL does not beat it there.
    for path in Path(root).glob("*/*"):
        if not (path / "MANIFEST.json").exists():
            continue
        manifest = json.loads((path / "MANIFEST.json").read_text(encoding="utf-8"))
        if manifest["arm"] != "STATIC" or manifest["model_id"] not in (
                "gpt-6-luna", "kimi-k3"):
            continue
        for task in manifest["tasks"]["selected"]:
            for rep in range(manifest["reps"]):
                cell_path = path / "cells" / task / str(rep) / "result.json"
                cell = json.loads(cell_path.read_text(encoding="utf-8"))
                cell["oracle"]["functional_ok"] = True
                cell["oracle"]["functional_ok_no_o4"] = True
                cell_path.write_text(json.dumps(cell, indent=2, sort_keys=True) + "\n",
                                     encoding="utf-8")
    result = _verdict(root)
    assert result["criteria"]["2_per_model"]["ok"] is False
    assert result["verdict"] == "continue"


def _fail_l3(manifest, task, rep, cell):
    if cell.get("tier") != "L3" or cell["oracle"]["functional_ok"] is False:
        return False
    cell["oracle"]["functional_ok"] = False
    cell["oracle"]["functional_ok_no_o4"] = False
    return True


def _kill_sensitivity(manifest, task, rep, cell):
    if cell["oracle"]["functional_ok"] is not True:
        return False
    if cell["oracle"].get("functional_ok_no_o4") is False:
        return False
    cell["oracle"]["functional_ok_no_o4"] = False
    return True


def test_criterion3_counterexample(tmp_path):
    root = tmp_path / "c3"
    _build(root, SUCCESS)
    _edit_skel(root, _fail_l3)
    result = _verdict(root)
    assert result["criteria"]["3_l2l3"]["ok"] is False
    assert result["verdict"] != "success"


def test_criterion4_only_counterexample(tmp_path):
    root = tmp_path / "c4"
    _build(root, SUCCESS)
    _edit_skel(root, _kill_sensitivity)
    result = _verdict(root)
    assert result["criteria"]["4_sensitivity"]["ok"] is False
    assert result["criteria"]["1_holm"]["ok"] is True
    assert result["criteria"]["5_ci"]["ok"] is True
    assert result["verdict"] == "continue"


def test_cli_stop_check_json(tmp_path, capsys):
    root = tmp_path / "success"
    runs = _build(root, SUCCESS)
    rc = cli.main(["stop-check", *[str(p) for p in runs], "--look", "2",
                   "--planned-units", "144", "--root", str(root), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "success"


def _minimal_run(tmp_path):
    source = (FIXTURES / "tiny" / "deepseek" / "skel")
    run = tmp_path / "run"
    shutil.copytree(source, run)
    manifest_path = run / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tasks"]["selected"] = ["lock-order/abba_2lock"]
    manifest["reps"] = 1
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for path in run.glob("cells/*/*/result.json"):
        if path.parent.parent.name != "abba_2lock":
            shutil.rmtree(path.parent.parent, ignore_errors=True)
    cell_path = run / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json"
    cell = json.loads(cell_path.read_text(encoding="utf-8"))
    for call in cell["calls"]:
        call["usage"] = {"input": 1000, "output": 500, "reasoning": 0,
                         "cached": 0}
        call["wall_ms"] = 1000
        call["transport_attempt"] = 1
        call["finish_reasons"] = ["stop"]
        call["cache_hit"] = False
    cell_path.write_text(json.dumps(cell, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    return run, cell


def test_look0_extrapolation_and_ledger(tmp_path, capsys):
    run, cell = _minimal_run(tmp_path)
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"stages": {"0": {"requests": 2}}}),
                      encoding="utf-8")
    rc = cli.main(["stop-check", str(run), "--look", "0", "--root", str(tmp_path),
                   "--budget-file", str(budget), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ledger"]["lower"] == 2
    assert payload["ledger"]["upper"] == 2
    assert payload["ledger"]["consistent"] is True
    # 24 tasks x 3 reps = 72 units; 2 calls and 3000 billable tokens per cell.
    row = next(r for r in payload["stage1"]["rows"]
               if r["label"] == "SKEL" and r.get("calls") is not None)
    assert row["calls"] == pytest.approx(2 * 72)
    assert row["billable_tokens"] == pytest.approx(3000 * 72)
    assert row["llm_s"] == pytest.approx(2000 * 72 / 1000)

    budget.write_text(json.dumps({"stages": {"0": {"requests": 99}}}),
                      encoding="utf-8")
    cli.main(["stop-check", str(run), "--look", "0", "--root", str(tmp_path),
              "--budget-file", str(budget), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ledger"]["consistent"] is False


def test_look0_truncation_flag(tmp_path, capsys):
    run, cell = _minimal_run(tmp_path)
    cell["calls"][0]["truncation_retry"] = True
    cell["calls"][0]["finish_reasons"] = ["length", "stop"]
    (run / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json").write_text(
        json.dumps(cell, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rc = cli.main(["stop-check", str(run), "--look", "0", "--root", str(tmp_path),
                   "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    model = next(m for m in payload["models"]
                 if m["model_id"] == "deepseek-flash")
    assert model["truncation_flag"] is True
