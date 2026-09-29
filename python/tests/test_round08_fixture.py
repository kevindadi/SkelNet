"""T1: the round-8 synthetic fixtures validate and are deterministic."""

import hashlib
import importlib.util
import json
from pathlib import Path

from skelnet.schema import validate_cell

FIXTURES = Path(__file__).parent / "fixtures" / "round08"
_spec = importlib.util.spec_from_file_location("r8synth", FIXTURES / "synth.py")
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)


def _cells(run_dir: Path):
    manifest = json.loads((run_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    for task in manifest["tasks"]["selected"]:
        for rep in range(manifest["reps"]):
            path = run_dir / "cells" / task / str(rep) / "result.json"
            yield json.loads(path.read_text(encoding="utf-8"))


def _run_dirs(root: Path):
    return sorted(p for p in root.glob("*/*") if (p / "MANIFEST.json").exists())


def test_tiny_cells_validate_and_have_manifests():
    runs = _run_dirs(FIXTURES / "tiny")
    assert len(runs) == 6
    for run in runs:
        cells = list(_cells(run))
        assert len(cells) == 9
        for cell in cells:
            assert validate_cell(cell) == [], (run, cell["task"], cell["rep"])


def test_planted_cells_validate(tmp_path):
    root = tmp_path / "planted"
    runs = synth.make_runs(root, synth.planted_spec())
    assert len(runs) == 32
    for run in runs:
        assert (run / "MANIFEST.json").exists()
        for cell in _cells(run):
            assert validate_cell(cell) == [], (run, cell["task"], cell["rep"])


def _digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.json")):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_synth_is_byte_identical(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    synth.make_runs(first, synth.planted_spec())
    synth.make_runs(second, synth.planted_spec())
    assert _digest(first) == _digest(second)


def test_planted_effect_is_visible(tmp_path):
    root = tmp_path / "planted"
    synth.make_runs(root, synth.planted_spec())
    rates: dict[str, list[int]] = {}
    for run in _run_dirs(root):
        manifest = json.loads((run / "MANIFEST.json").read_text(encoding="utf-8"))
        label = manifest["arm"]
        if label == "SKEL" and manifest["run_params"]["feedback_mode"] == "outcome_only":
            label = "SKEL-outcome"
        bucket = rates.setdefault(label, [0, 0])
        for cell in _cells(run):
            bucket[0] += 1
            if cell["oracle"]["functional_ok"] is True:
                bucket[1] += 1
    skel = rates["SKEL"][1] / rates["SKEL"][0]
    for baseline in ("G0", "REFINE", "STATIC", "DYNAMIC"):
        assert skel - rates[baseline][1] / rates[baseline][0] > 0.12
    dynamic_m = rates["DYNAMIC_M"][1] / rates["DYNAMIC_M"][0]
    assert abs(skel - dynamic_m) < 0.02
    instrument = {}
    for run in _run_dirs(root):
        manifest = json.loads((run / "MANIFEST.json").read_text(encoding="utf-8"))
        label = manifest["arm"]
        hits = total = 0
        for cell in _cells(run):
            total += 1
            layer = cell["oracle"].get("layers", {}).get("O4", {})
            if layer.get("category") == "instrument_unsupported":
                hits += 1
        instrument.setdefault(label, [0, 0])
        instrument[label][0] += hits
        instrument[label][1] += total
    cir_rate = instrument["CIR"][0] / instrument["CIR"][1]
    assert cir_rate > 0.2
    for other in ("G0", "SKEL", "DYNAMIC"):
        assert instrument[other][0] == 0


def test_fp_check_and_probe_fixtures_parse():
    fp = json.loads((FIXTURES / "fp_check" / "FP_CHECK.json").read_text(
        encoding="utf-8"))
    probe = json.loads((FIXTURES / "probe" / "PROBE.json").read_text(
        encoding="utf-8"))
    assert set(fp["summary"]) == {"clippy", "lockbud"}
    assert fp["summary"]["lockbud"]["buggy_detection_rate"] == 1.0
    assert probe["schema_version"] == "skelnet-probe-v1"
    ids = [model["model_id"] for model in probe["models"]]
    assert "gpt-6-luna" in ids and "kimi-k3" in ids
