"""Difficulty tiers from gold ConcIR shape and explored state counts."""

import json
from pathlib import Path

from skelnet.bench import classify_tier, metrics_from_cir, tier_repo


def _cir(funcs, resources, states_hint=None):
    body = [{"sid": "s1", "kind": "scope", "funcs": funcs},
            {"sid": "s2", "kind": "return"}]
    return {"modules": [{"name": "main", "resources": resources,
                         "functions": [{"name": "main", "kind": "normal", "body": body}]}]}


def _res(name, typ, **extra):
    row = {"name": name, "kind": "sync", "type": typ}
    row.update(extra)
    return row


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FallbackTools:
    """Lower/explore are unavailable, so the state count comes from BASELINE."""

    def lower_json(self, skel):
        return None, "skelnet not found"

    def explore(self, cir, contract):
        return None, "concir-backend not found"


def _task(root: Path, rel: str, cir: dict, states: int, *, ext: bool = False,
          extra_reqs: dict | None = None) -> None:
    task = root / "benchmarks" / "tasks" / rel
    reqs = {"terminal": "DONE t=1", "keep": "yes"}
    if extra_reqs:
        reqs.update(extra_reqs)
    _write(task / "contract.json", "{}\n")
    _write(task / "gold.skel", "skeleton t;\n")
    _write(task / "gold.cir.json", json.dumps(cir) + "\n")
    _write(task / "requirements.json", json.dumps(reqs, indent=2) + "\n")
    _write(root / "benchmarks" / "BASELINE.json", json.dumps({
        "tasks": [{"task": rel, "outcome": "PASS", "complete": True,
                   "properties": [], "states_explored_reference": states}]
    }) + "\n")
    if ext:
        _write(root / "benchmarks" / "BASELINE_EXT.json", json.dumps({
            "schema_version": "skelnet-baseline-ext-v1",
            "tasks": [{"task": rel, "outcome": "PASS", "complete": True, "properties": []}]
        }) + "\n")


def test_classify_tier_boundaries():
    assert classify_tier(3, 2, 1, 300, False)[0] == "L1"
    assert classify_tier(4, 2, 1, 300, False)[0] == "unclassified"
    assert classify_tier(4, 3, 2, 301, False)[0] == "L2"
    assert classify_tier(3, 1, 2, 300, False)[0] == "L2"
    assert classify_tier(4, 3, 2, 5000, False)[0] == "L2"
    assert classify_tier(4, 3, 3, 5000, False)[0] == "L3"
    assert classify_tier(4, 1, 1, 5000, True)[0] == "L3"
    assert classify_tier(6, 2, 3, 100_000, False)[0] == "L3"
    tier, violations = classify_tier(7, 1, 1, 10, False)
    assert tier == "unclassified"
    assert any("threads" in item for item in violations)


def test_metrics_ignore_called_helpers_and_plain_variables():
    cir = _cir(["main::w1", "main::w2"],
               [_res("m", "Mutex"), {"name": "acc", "kind": "var", "type": "Var"}])
    cir["modules"][0]["functions"].append({
        "name": "w1", "kind": "normal",
        "body": [{"sid": "s1", "kind": "call", "func": "main::compute"}],
    })
    metrics = metrics_from_cir(cir)
    assert metrics["threads"] == 2
    assert metrics["sync_resources"] == 1
    assert metrics["mechanisms"] == ["Mutex"]
    assert metrics["parameterized"] is False


def test_spawn_counts_as_a_thread():
    cir = {"modules": [{"name": "main", "resources": [], "functions": [{
        "name": "main", "body": [{"kind": "spawn", "func": "worker"}]}]}]}
    assert metrics_from_cir(cir)["threads"] == 1


def test_tier_repo_legacy_declaration_and_extension_task(tmp_path):
    root = tmp_path / "repo"
    cir = _cir(["main::t1", "main::t2"], [_res("a", "Mutex"), _res("b", "Mutex")])
    _task(root, "fam/legacy", cir, states=10)
    report = tier_repo(root, "fam/legacy", tools=FallbackTools())
    row = report["tasks"][0]
    assert row["computed_tier"] == "L1"
    assert row["declared_tier"] == "L1"
    assert row["tier_source"] == "legacy"
    assert row["metrics"]["states_source"] == "baseline"
    assert report["mismatches"] == []

    # Four threads and two mechanisms is L2, but a legacy task stays declared L1.
    l2 = _cir(["main::a", "main::b", "main::c", "main::d"],
              [_res("m", "Mutex"), _res("c", "Condvar")])
    _task(root, "fam/bigger", l2, states=1371)
    # _task rewrites BASELINE.json with only the new task. Put both entries back.
    base = json.loads((root / "benchmarks" / "BASELINE.json").read_text(encoding="utf-8"))
    base["tasks"].append({"task": "fam/legacy", "outcome": "PASS", "complete": True,
                          "properties": [], "states_explored_reference": 10})
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps(base), encoding="utf-8")
    report = tier_repo(root, "all", tools=FallbackTools())
    by_task = {row["task"]: row for row in report["tasks"]}
    assert by_task["fam/bigger"]["computed_tier"] == "L2"
    assert by_task["fam/bigger"]["declared_tier"] == "L1"
    assert "fam/bigger" in report["mismatches"]

    _task(root, "fam/fresh", l2, states=1371, ext=True)
    report = tier_repo(root, "fam/fresh", tools=FallbackTools())
    fresh = report["tasks"][0]
    assert fresh["computed_tier"] == "L2"
    assert fresh["declared_tier"] == "L2"
    assert fresh["tier_source"] == "computed"


def test_write_appends_only_the_tier_keys(tmp_path):
    root = tmp_path / "repo"
    cir = _cir(["main::t1"], [_res("a", "Mutex")])
    _task(root, "fam/legacy", cir, states=10, extra_reqs={"note": "keep-me"})
    tier_repo(root, "fam/legacy", write=True, tools=FallbackTools())
    path = root / "benchmarks" / "tasks" / "fam" / "legacy" / "requirements.json"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert list(data)[-3:] == ["tier", "tier_source", "tier_metrics"]
    assert data["note"] == "keep-me"
    assert data["tier"] == "L1"
    assert data["tier_source"] == "legacy"
    assert text.endswith("\n")
    assert (root / "benchmarks" / "TIERS.md").is_file()
    assert "fam/legacy" in (root / "benchmarks" / "TIERS.md").read_text(encoding="utf-8")
