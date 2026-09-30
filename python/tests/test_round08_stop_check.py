"""T9/F2/F3: the staged stopping rules and the stop-check CLI."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from skelnet import cli

FIXTURES = Path(__file__).parent / "fixtures" / "round08"
_spec = importlib.util.spec_from_file_location("r8synth", FIXTURES / "synth.py")
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)

SUCCESS = {"SKEL": 0.85, "CIR": 0.7, "G0": 0.5, "REFINE": 0.5, "STATIC": 0.5,
           "DYNAMIC": 0.5, "DYNAMIC_M": 0.85, "SKEL-outcome": 0.6}
FUTILITY = {"SKEL": 0.4, "CIR": 0.4, "G0": 0.6, "REFINE": 0.6, "STATIC": 0.6,
            "DYNAMIC": 0.6, "DYNAMIC_M": 0.6, "SKEL-outcome": 0.4}


# ── helpers ──────────────────────────────────────────────────────────────

def _build(root, rates):
    shutil.rmtree(root, ignore_errors=True)
    spec = dict(synth.planted_spec())
    spec["rates"] = rates
    synth.make_runs(root, spec)
    synth.write_fake_tasks(root, spec["tasks"])
    return Path(root)


def _iter(root):
    for path in Path(root).glob("*/*"):
        if not (path / "MANIFEST.json").exists():
            continue
        manifest = json.loads((path / "MANIFEST.json").read_text(encoding="utf-8"))
        label = "SKEL-outcome" if (
            manifest["arm"] == "SKEL"
            and manifest["run_params"]["feedback_mode"] == "outcome_only") \
            else manifest["arm"]
        for task in manifest["tasks"]["selected"]:
            for rep in range(manifest["reps"]):
                yield path, manifest, label, task, rep


def _read(path, task, rep):
    return json.loads((path / "cells" / task / str(rep) / "result.json").read_text(
        encoding="utf-8"))


def _write(path, task, rep, cell):
    (path / "cells" / task / str(rep) / "result.json").write_text(
        json.dumps(cell, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _edit_group(root, label, fn):
    for path, manifest, cell_label, task, rep in _iter(root):
        if cell_label != label:
            continue
        cell = _read(path, task, rep)
        if fn(manifest, task, rep, cell):
            _write(path, task, rep, cell)


def _cli(tmp_path, root, look=2, planned=144, extra=()):
    runs = sorted(p for p in Path(root).glob("*/*")
                  if (p / "MANIFEST.json").exists())
    out = tmp_path / f"out-{look}-{len(extra)}"
    args = ["stop-check", *[str(p) for p in runs], "--look", str(look),
            "--planned-units", str(planned), "--root", str(root), "--json"]
    args += list(extra)
    import io
    import contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = cli.main(args)
    assert rc == 0
    return json.loads(buffer.getvalue())


# ── success / futility / continue ────────────────────────────────────────

def test_look2_success(tmp_path):
    root = _build(tmp_path / "success", SUCCESS)
    payload = _cli(tmp_path, root)
    assert payload["verdict"] == "success"
    for key in ("1_holm", "2_per_model", "3_l2l3", "4_sensitivity", "5_ci"):
        assert payload["criteria"][key]["ok"] is True


def test_look2_futility(tmp_path):
    root = _build(tmp_path / "futility", FUTILITY)
    payload = _cli(tmp_path, root)
    assert payload["verdict"] == "futility"
    assert "margin<3pp" in payload["futility_reasons"]


def test_look2_continue(tmp_path):
    root = _build(tmp_path / "continue", {
        "SKEL": 0.55, "CIR": 0.55, "G0": 0.5, "REFINE": 0.5, "STATIC": 0.5,
        "DYNAMIC": 0.5, "DYNAMIC_M": 0.55, "SKEL-outcome": 0.5})
    payload = _cli(tmp_path, root)
    assert payload["verdict"] == "continue"
    assert payload["criteria"]["1_holm"]["ok"] is False


# ── isolated criterion counterexamples (F3) ──────────────────────────────

CRITERIA = ("1_holm", "2_per_model", "3_l2l3", "4_sensitivity", "5_ci")


def _assert_only(criteria, target):
    for key in CRITERIA:
        assert criteria[key]["ok"] is (key != target), key


def test_criterion2_only(tmp_path):
    root = _build(tmp_path / "c2", SUCCESS)
    for path, manifest, label, task, rep in _iter(root):
        if label != "STATIC" or manifest["model_id"] not in (
                "gpt-6-luna", "kimi-k3"):
            continue
        cell = _read(path, task, rep)
        cell["oracle"]["functional_ok"] = True
        cell["oracle"]["functional_ok_no_o4"] = True
        _write(path, task, rep, cell)
    payload = _cli(tmp_path, root)
    _assert_only(payload["criteria"], "2_per_model")
    assert payload["verdict"] == "continue"


def test_criterion3_only(tmp_path):
    root = _build(tmp_path / "c3", SUCCESS)
    skel = {}
    for path, manifest, label, task, rep in _iter(root):
        if label == "SKEL":
            skel[(manifest["model_id"], task, rep)] = _read(
                path, task, rep)["oracle"]["functional_ok"]

    def edit(manifest, task, rep, cell):
        if cell.get("tier") in ("L2", "L3"):
            ok = skel.get((manifest["model_id"], task, rep)) is True
        else:
            ok = False
        cell["oracle"]["functional_ok"] = ok
        cell["oracle"]["functional_ok_no_o4"] = ok
        return True

    _edit_group(root, "STATIC", edit)
    payload = _cli(tmp_path, root)
    _assert_only(payload["criteria"], "3_l2l3")
    assert payload["verdict"] == "continue"


def test_criterion4_only(tmp_path):
    root = _build(tmp_path / "c4", SUCCESS)

    def edit(manifest, task, rep, cell):
        if cell["oracle"]["functional_ok"] is not True:
            return False
        if cell["oracle"].get("functional_ok_no_o4") is False:
            return False
        cell["oracle"]["functional_ok_no_o4"] = False
        return True

    _edit_group(root, "SKEL", edit)
    payload = _cli(tmp_path, root)
    _assert_only(payload["criteria"], "4_sensitivity")
    assert payload["verdict"] == "continue"


def test_criterion5_only(tmp_path):
    root = _build(tmp_path / "c5", SUCCESS)
    tiers = {}
    skel = {}
    for path, manifest, label, task, rep in _iter(root):
        if label == "SKEL":
            cell = _read(path, task, rep)
            tiers[task] = cell.get("tier")
            skel[(manifest["model_id"], task, rep)] = cell["oracle"]["functional_ok"]
    targets = sorted(t for t, tier in tiers.items() if tier in ("L2", "L3"))[:2]

    def edit_g0(manifest, task, rep, cell):
        if task in targets:
            ok = False
        else:
            ok = skel.get((manifest["model_id"], task, rep)) is True
        cell["oracle"]["functional_ok"] = ok
        cell["oracle"]["functional_ok_no_o4"] = ok
        return True

    def edit_skel(manifest, task, rep, cell):
        if task not in targets:
            return False
        cell["oracle"]["functional_ok"] = True
        cell["oracle"]["functional_ok_no_o4"] = True
        return True

    _edit_group(root, "G0", edit_g0)
    _edit_group(root, "SKEL", edit_skel)
    payload = _cli(tmp_path, root)
    _assert_only(payload["criteria"], "5_ci")
    assert payload["verdict"] == "continue"


# ── F2: Look-2 futility reasons ──────────────────────────────────────────

def test_look2_futility_margin_only(tmp_path):
    root = _build(tmp_path / "f2a", {
        "SKEL": 0.52, "CIR": 0.5, "G0": 0.5, "REFINE": 0.5, "STATIC": 0.5,
        "DYNAMIC": 0.5, "DYNAMIC_M": 0.52, "SKEL-outcome": 0.5})
    payload = _cli(tmp_path, root)
    assert payload["futility"] is True
    assert payload["futility_reasons"] == ["margin<3pp"]
    assert payload["criteria"]["3_l2l3"]["ok"] is True


def test_look2_futility_l2l3_only(tmp_path):
    root = _build(tmp_path / "f2b", {
        "SKEL": 0.9, "CIR": 0.2, "G0": 0.2, "REFINE": 0.2, "STATIC": 0.2,
        "DYNAMIC": 0.2, "DYNAMIC_M": 0.9, "SKEL-outcome": 0.5})

    def edit(manifest, task, rep, cell):
        ok = cell.get("tier") == "L1"
        cell["oracle"]["functional_ok"] = ok
        cell["oracle"]["functional_ok_no_o4"] = ok
        return True

    _edit_group(root, "SKEL", edit)
    payload = _cli(tmp_path, root)
    assert payload["futility"] is True
    assert payload["futility_reasons"] == ["l2l3 regression"]
    assert payload["margin"] > 0.03


def test_look3_reports_but_does_not_judge_futility(tmp_path):
    root = _build(tmp_path / "look3", FUTILITY)
    payload = _cli(tmp_path, root, look=3, extra=["--previous-look-units", "86"])
    assert payload["futility"] is False
    assert "margin<3pp" in payload["futility_reasons"]


# ── F3: Look 1 ───────────────────────────────────────────────────────────

def test_look1_tiny_margin_and_failure_stages(tmp_path):
    runs = sorted(p for p in (FIXTURES / "tiny").glob("*/*")
                  if (p / "MANIFEST.json").exists())
    import io
    import contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = cli.main(["stop-check", *[str(p) for p in runs], "--look", "1",
                       "--root", str(FIXTURES / "tiny"), "--json"])
    assert rc == 0
    payload = json.loads(buffer.getvalue())
    assert payload["skel_rate"] == pytest.approx(13 / 18)
    assert payload["best_rate"] == pytest.approx(9 / 17)
    assert payload["margin"] == pytest.approx(13 / 18 - 9 / 17)
    assert payload["futility"] is False
    g0 = payload["failure_stages"]["G0"]
    assert g0["rust_compile"] == 8 and g0["ok"] == 9
    assert sum(g0.values()) == 17
    skel = payload["failure_stages"]["SKEL"]
    assert sum(skel.values()) == 18


def test_look1_futility(tmp_path):
    root = _build(tmp_path / "futility", FUTILITY)
    payload = _cli(tmp_path, root, look=1)
    assert payload["futility"] is True
    # Exact-count assignment: SKEL 14/36 per model (56/144); the best baseline
    # REFINE/STATIC/DYNAMIC take round(0.6*36)=22/36 (88/144).
    assert payload["skel_rate"] == pytest.approx(56 / 144)
    assert payload["best_rate"] == pytest.approx(88 / 144)
    assert payload["margin"] == pytest.approx(56 / 144 - 88 / 144)


# ── F3: Look 3 alpha from F1 table ───────────────────────────────────────
#
# Round 9 (D9-9) makes the final-look boundary depend on the real information
# fraction t_final = paired units / planned units.  The round-8 planted fixture
# has 144 paired units, so the test sets --planned-units 144 (t_final = 1) and
# varies the previous look's units.  The expected values come from the OBF
# spending function computed independently (not from the code under test).

@pytest.mark.parametrize("previous,expected", [
    (86, 0.0457279),   # t_prev = 0.5972
    (43, 0.0498534),   # t_prev = 0.2986
])
def test_look3_alpha_uses_previous_look_units(tmp_path, previous, expected):
    root = _build(tmp_path / f"alpha{previous}", SUCCESS)
    payload = _cli(tmp_path, root, look=3, planned=144,
                   extra=["--previous-look-units", str(previous)])
    assert payload["alpha"] == pytest.approx(expected, abs=2e-5)


# ── Look 0 (F8) ──────────────────────────────────────────────────────────

def _minimal_run(tmp_path):
    source = (FIXTURES / "tiny" / "deepseek" / "skel")
    run = tmp_path / "run"
    shutil.copytree(source, run)
    manifest_path = run / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tasks"]["selected"] = ["lock-order/abba_2lock"]
    manifest["reps"] = 1
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
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
    return run


def test_look0_extrapolation_ledger_and_warnings(tmp_path, capsys):
    run = _minimal_run(tmp_path)
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"stages": {"0": {"requests": 2}}}),
                      encoding="utf-8")
    rc = cli.main(["stop-check", str(run), "--look", "0", "--root",
                   str(tmp_path), "--budget-file", str(budget), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ledger"]["lower"] == 2 and payload["ledger"]["upper"] == 2
    assert payload["ledger"]["consistent"] is True
    rows = payload["stage1"]["rows"]
    assert len(rows) == 4 * 6
    # Only DeepSeek/SKEL has data (2 calls/cell); the other three models fall
    # back to that all-model average, so totals.calls = 4 * 2 * 72.
    assert payload["stage1"]["totals"]["calls"] == pytest.approx(4 * 2 * 72)
    assert any(row.get("note") == "all-model average" for row in rows)
    assert sum(r["calls"] for r in rows) == pytest.approx(
        payload["stage1"]["totals"]["calls"])

    # Missing budget file -> warning, not silent.
    rc = cli.main(["stop-check", str(run), "--look", "0", "--root",
                   str(tmp_path), "--budget-file", str(tmp_path / "nope.json")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "budget file not found" in out


def test_ledger_transport_upper_bound(tmp_path, capsys):
    run = _minimal_run(tmp_path)
    cell_path = run / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json"
    cell = json.loads(cell_path.read_text(encoding="utf-8"))
    cell["calls"][0]["transport_attempt"] = 3
    cell_path.write_text(json.dumps(cell, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"stages": {"0": {"requests": 4}}}),
                      encoding="utf-8")
    rc = cli.main(["stop-check", str(run), "--look", "0", "--root", str(tmp_path),
                   "--budget-file", str(budget), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ledger"]["lower"] == 2
    assert payload["ledger"]["upper"] == 4
    assert payload["ledger"]["consistent"] is True
    budget.write_text(json.dumps({"stages": {"0": {"requests": 5}}}),
                      encoding="utf-8")
    cli.main(["stop-check", str(run), "--look", "0", "--root", str(tmp_path),
              "--budget-file", str(budget), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ledger"]["consistent"] is False


def test_ledger_excludes_cache_hits(tmp_path, capsys):
    run = _minimal_run(tmp_path)
    cell_path = run / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json"
    cell = json.loads(cell_path.read_text(encoding="utf-8"))
    cell["calls"][0]["cache_hit"] = True
    cell_path.write_text(json.dumps(cell, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"stages": {"0": {"requests": 1}}}),
                      encoding="utf-8")
    cli.main(["stop-check", str(run), "--look", "0", "--root", str(tmp_path),
              "--budget-file", str(budget), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ledger"]["lower"] == 1  # only the second, non-cache call


def test_look0_truncation_flag(tmp_path, capsys):
    run = _minimal_run(tmp_path)
    cell_path = run / "cells" / "lock-order" / "abba_2lock" / "0" / "result.json"
    cell = json.loads(cell_path.read_text(encoding="utf-8"))
    cell["calls"][0]["truncation_retry"] = True
    cell["calls"][0]["finish_reasons"] = ["length", "stop"]
    cell_path.write_text(json.dumps(cell, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    rc = cli.main(["stop-check", str(run), "--look", "0", "--root", str(tmp_path),
                   "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    model = next(m for m in payload["models"]
                 if m["model_id"] == "deepseek-flash")
    assert model["truncation_flag"] is True
