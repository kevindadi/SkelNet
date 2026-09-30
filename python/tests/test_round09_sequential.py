"""R9-P4: sequential final-look boundary, missing-arg gates, no_success."""

import contextlib
import importlib.util
import io
import json
import shutil
from pathlib import Path

import pytest

from skelnet import cli, report

FIXTURES = Path(__file__).parent / "fixtures" / "round08"
_spec = importlib.util.spec_from_file_location("r8synth", FIXTURES / "synth.py")
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)

# Coordinator-supplied reference values (SciPy), total alpha 0.05, planned 880.
REFERENCE = [
    (528, 880, 0.0113964, 0.0456610),
    (528, 800, 0.0113964, 0.0465167),
    (528, 700, 0.0113964, 0.0478848),
    (480, 880, 0.0079590, 0.0468958),
    (400, 880, 0.0036480, 0.0485173),
]

SUCCESS = {"SKEL": 0.85, "CIR": 0.7, "G0": 0.5, "REFINE": 0.5, "STATIC": 0.5,
           "DYNAMIC": 0.5, "DYNAMIC_M": 0.85, "SKEL-outcome": 0.6}
FUTILITY = {"SKEL": 0.4, "CIR": 0.4, "G0": 0.6, "REFINE": 0.6, "STATIC": 0.6,
            "DYNAMIC": 0.6, "DYNAMIC_M": 0.6, "SKEL-outcome": 0.4}


def _build(root, rates):
    shutil.rmtree(root, ignore_errors=True)
    spec = dict(synth.planted_spec())
    spec["rates"] = rates
    synth.make_runs(root, spec)
    synth.write_fake_tasks(root, spec["tasks"])
    return Path(root)


def _runs(root):
    return sorted(p for p in Path(root).glob("*/*")
                  if (p / "MANIFEST.json").exists())


def _stop_check(runs, root, look, extra=(), json_out=True):
    args = ["stop-check", *[str(p) for p in runs], "--look", str(look),
            "--root", str(root)]
    if json_out:
        args.append("--json")
    args += list(extra)
    import contextlib
    import io
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        rc = cli.main(args)
    return rc, buffer.getvalue()


@pytest.mark.parametrize("previous,final,spent,expected", REFERENCE)
def test_final_nominal_alpha_matches_reference(previous, final, spent, expected):
    got = report._final_nominal_alpha(previous / 880, final / 880)
    assert got == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("previous,final,spent,expected", REFERENCE)
def test_look2_spent_alpha_matches_reference(previous, final, spent, expected):
    got = report.stats.obf_nominal_boundaries([previous / 880, final / 880])[0]
    assert got == pytest.approx(spent, abs=1e-6)


def test_look3_requires_previous_units(tmp_path):
    root = _build(tmp_path / "r", SUCCESS)
    rc, _ = _stop_check(_runs(root), root, look=3)
    assert rc == 2


def test_look3_previous_units_and_from_agree(tmp_path):
    root = _build(tmp_path / "r", SUCCESS)
    runs = _runs(root)
    rc, out = _stop_check(runs, root, look=3,
                          extra=["--previous-look-units", "86"])
    assert rc == 0
    payload = json.loads(out)
    look2 = tmp_path / "look2.json"
    look2.write_text(json.dumps({"look": 2, "units": 86}), encoding="utf-8")
    rc2, out2 = _stop_check(runs, root, look=3,
                            extra=["--previous-look-from", str(look2)])
    assert rc2 == 0
    assert json.loads(out2)["alpha"] == pytest.approx(payload["alpha"])


def test_look3_previous_from_reads_units_field(tmp_path):
    root = _build(tmp_path / "r", SUCCESS)
    look2 = tmp_path / "look2.json"
    look2.write_text(json.dumps({"units": 86}), encoding="utf-8")
    rc, out = _stop_check(_runs(root), root, look=3,
                          extra=["--previous-look-from", str(look2)])
    assert rc == 0
    assert json.loads(out)["alpha"] > 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"paired_units": 86}), encoding="utf-8")
    rc2, err = _stop_check(_runs(root), root, look=3,
                           extra=["--previous-look-from", str(bad)])
    assert rc2 == 2
    assert "units" in err


def test_look3_nonsignificant_is_no_success(tmp_path):
    root = _build(tmp_path / "r", FUTILITY)
    runs = _runs(root)
    rc, out = _stop_check(runs, root, look=3,
                          extra=["--previous-look-units", "86"])
    assert rc == 0
    assert json.loads(out)["verdict"] == "no_success"
    rc2, md = _stop_check(runs, root, look=3, json_out=False,
                          extra=["--previous-look-units", "86"])
    assert rc2 == 0
    assert "Verdict: **no_success**" in md


def test_report_look3_uses_same_alpha_and_gates(tmp_path):
    root = _build(tmp_path / "r", SUCCESS)
    runs = _runs(root)
    rc, out = _stop_check(runs, root, look=3,
                          extra=["--previous-look-units", "86"])
    alpha = json.loads(out)["alpha"]

    import contextlib
    import io
    outdir = tmp_path / "report"
    args = ["report", *[str(p) for p in runs], "--table", "main", "--look", "3",
            "--previous-look-units", "86", "--root", str(root),
            "--out", str(outdir)]
    with contextlib.redirect_stdout(io.StringIO()):
        rc2 = cli.main(args)
    assert rc2 == 0
    document = json.loads((outdir / "report.json").read_text(encoding="utf-8"))
    assert document["tables"]["main"]["alpha"] == pytest.approx(alpha)
    assert "Nominal alpha" in (outdir / "REPORT.md").read_text(encoding="utf-8")

    buffer2 = io.StringIO()
    with contextlib.redirect_stdout(buffer2), contextlib.redirect_stderr(buffer2):
        rc3 = cli.main(["report", *[str(p) for p in runs], "--table", "main",
                        "--look", "3", "--root", str(root)])
    assert rc3 == 2


def test_final_nominal_alpha_rejects_non_increasing():
    with pytest.raises(ValueError):
        report._final_nominal_alpha(0.6, 0.6)
    with pytest.raises(ValueError):
        report._final_nominal_alpha(0.6, 0.5)


def test_look3_final_units_not_above_previous_is_an_error(tmp_path):
    root = _build(tmp_path / "r", SUCCESS)
    runs = _runs(root)
    for previous in ("144", "200"):
        rc, out = _stop_check(runs, root, look=3,
                              extra=["--previous-look-units", previous])
        assert rc == 2, previous
        assert "144" in out and previous in out
    for previous in ("144", "200"):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            rc = cli.main(["report", *[str(p) for p in runs], "--table", "main",
                           "--look", "3", "--planned-units", "880",
                           "--previous-look-units", previous, "--root",
                           str(root)])
        assert rc == 2, previous
        assert "144" in buffer.getvalue() and previous in buffer.getvalue()


@pytest.mark.parametrize("planned,expected", [(240, 0.0498719),
                                              (200, 0.0494435)])
def test_look3_uses_the_real_final_fraction(tmp_path, planned, expected):
    root = _build(tmp_path / "r", SUCCESS)
    runs = _runs(root)
    rc, out = _stop_check(runs, root, look=3,
                          extra=["--planned-units", str(planned),
                                 "--previous-look-units", "86"])
    assert rc == 0
    payload = json.loads(out)
    assert payload["units"] == 144
    assert payload["alpha"] == pytest.approx(expected, abs=1e-6)

    outdir = tmp_path / f"report-{planned}"
    with contextlib.redirect_stdout(io.StringIO()):
        rc2 = cli.main(["report", *[str(p) for p in runs], "--table", "main",
                        "--look", "3", "--planned-units", str(planned),
                        "--previous-look-units", "86", "--root", str(root),
                        "--out", str(outdir)])
    assert rc2 == 0
    document = json.loads((outdir / "report.json").read_text(encoding="utf-8"))
    assert document["tables"]["main"]["alpha"] == pytest.approx(expected,
                                                                abs=1e-6)
