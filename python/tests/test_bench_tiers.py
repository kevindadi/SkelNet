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
    # threads 0 and 3 are L1; 4 is not. states 300 is L1; 301 is not.
    assert classify_tier(0, 0, 0, 6, False)[0] == "L1"
    assert classify_tier(3, 2, 1, 300, False)[0] == "L1"
    assert classify_tier(2, 1, 1, 301, False)[0] != "L1"
    assert classify_tier(4, 2, 1, 300, False)[0] != "L1"
    # L2: 3–4 threads, enough structure, states 300 through 5000.
    assert classify_tier(3, 1, 2, 300, False)[0] == "L2"
    assert classify_tier(4, 4, 1, 301, False)[0] == "L2"
    assert classify_tier(4, 4, 1, 1371, False)[0] == "L2"
    assert classify_tier(4, 3, 2, 5000, False)[0] == "L2"
    assert classify_tier(4, 4, 1, 5001, False)[0] != "L2"
    # L3 starts where L2's state or thread window ends.
    assert classify_tier(4, 1, 1, 5000, True)[0] == "L3"
    assert classify_tier(4, 3, 3, 5001, False)[0] == "L3"
    assert classify_tier(6, 2, 3, 100_000, False)[0] == "L3"
    assert classify_tier(6, 2, 3, 100_001, False)[0] != "L3"
    assert classify_tier(7, 1, 1, 10, False)[0] is None
    _computed, nearest, violations = classify_tier(7, 1, 1, 10, False)
    assert nearest == "L1"
    assert any(item.startswith("threads") for item in violations)


def test_metrics_ignore_called_helpers_and_plain_variables():
    cir = _cir(["main::w1", "main::w2"],
               [_res("m", "Mutex"), {"name": "acc", "kind": "var", "type": "Var"}])
    cir["modules"][0]["functions"].append({
        "name": "w1", "kind": "normal",
        "body": [
            {"sid": "s1", "kind": "mutex_lock", "resource": "main::m"},
            {"sid": "s2", "kind": "call", "func": "main::compute"},
        ],
    })
    metrics = metrics_from_cir(cir)
    assert metrics["threads"] == 2
    assert metrics["sync_resources"] == 1
    assert metrics["mechanisms"] == ["Mutex"]
    assert metrics["parameterized"] is False
    assert "main::compute" not in metrics["thread_funcs"]


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

    # Four threads and four used mutexes is L2, but a legacy task stays declared L1.
    l2 = _cir(["main::a", "main::b", "main::c", "main::d"],
              [_res("m1", "Mutex"), _res("m2", "Mutex"),
               _res("m3", "Mutex"), _res("m4", "Mutex")])
    l2["modules"][0]["functions"][0]["body"] = [
        {"sid": f"u{i}", "kind": "mutex_lock", "resource": f"main::m{i}"}
        for i in range(1, 5)
    ] + l2["modules"][0]["functions"][0]["body"]
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
    # An extension task is not a frozen baseline task, so its declaration is computed.
    base = json.loads((root / "benchmarks" / "BASELINE.json").read_text(encoding="utf-8"))
    base["tasks"] = [row for row in base["tasks"] if row["task"] != "fam/fresh"]
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps(base), encoding="utf-8")
    class Explored(FallbackTools):
        def lower_json(self, skel):
            return {"modules": []}, None

        def explore(self, cir, contract):
            return {"complete": True, "states_explored": 1371, "outcome": "PASS"}, None

    report = tier_repo(root, "fam/fresh", tools=Explored())
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
    assert data["note"] == "keep-me"
    assert "tier" not in data and "tier_source" not in data
    assert list(data)[-1] == "tier_metrics"
    assert data["tier_metrics"]["computed_tier"] == "L1"
    assert text.endswith("\n")
    assert (root / "benchmarks" / "TIERS.md").is_file()
    assert "fam/legacy" in (root / "benchmarks" / "TIERS.md").read_text(encoding="utf-8")


def _lock(resource: str, sid: str = "lk") -> dict:
    return {"sid": sid, "kind": "mutex_lock", "resource": resource}


def test_repeated_scope_entries_count_as_separate_threads():
    cir = _cir(["main::w", "main::w", "main::w", "main::w"], [])
    metrics = metrics_from_cir(cir)
    assert metrics["threads"] == 4
    assert metrics["thread_funcs"] == ["main::w"]


def test_loop_spawn_counts_as_one_thread():
    cir = {"modules": [{"name": "main", "resources": [], "functions": [{
        "name": "main",
        "body": [
            {"sid": "s1", "kind": "spawn", "func": "worker"},
            {"sid": "s2", "kind": "join", "handle": "h"},
            {"sid": "s3", "kind": "goto", "target": "s1"},
        ],
    }]}]}
    assert metrics_from_cir(cir)["threads"] == 1


def test_condvar_and_its_mutex_are_one_mechanism():
    cir = _cir(["main::w"], [_res("m", "Mutex"), _res("cv", "Condvar")])
    cir["modules"][0]["functions"][0]["body"] = [
        {"sid": "a", "kind": "mutex_lock", "resource": "main::m"},
        {"sid": "b", "kind": "condvar_wait", "condvar": "main::cv", "lock": "main::m"},
    ] + cir["modules"][0]["functions"][0]["body"]
    assert metrics_from_cir(cir)["mechanisms"] == ["Condvar"]
    assert metrics_from_cir(cir)["sync_resources"] == 2
    cir["modules"][0]["resources"].append(_res("other", "Mutex"))
    cir["modules"][0]["functions"][0]["body"].append(
        {"sid": "c", "kind": "mutex_lock", "resource": "main::other"})
    assert metrics_from_cir(cir)["mechanisms"] == ["Condvar", "Mutex"]


def test_unused_resources_are_not_counted():
    cir = _cir(["main::w"], [_res("used", "Mutex"), _res("idle", "Mutex")])
    cir["modules"][0]["functions"][0]["body"].insert(
        0, _lock("main::used", "u"))
    metrics = metrics_from_cir(cir)
    assert metrics["sync_resources"] == 1
    assert metrics["unused_resources"] == ["main::idle"]


def test_channel_fields_do_not_imply_protocol_params(tmp_path):
    from skelnet.bench import validate_repo
    cir = _cir(["main::w"], [_res("ch", "Channel", capacity=0),
                            _res("s", "Semaphore", count=0)])
    cir["modules"][0]["functions"][0]["body"].insert(
        0, {"sid": "u", "kind": "send", "channel": "main::ch"})
    assert metrics_from_cir(cir)["parameterized"] is False
    root = tmp_path / "repo"
    _task(root, "fam/task", cir, states=10, extra_reqs={"protocol_params": {"accounts": 1}})
    failed = validate_repo(root, "fam/task", checks=("V2",))
    assert failed["tasks"][0]["checks"][0]["status"] == "fail"
    reqs = json.loads((root / "benchmarks/tasks/fam/task/requirements.json").read_text())
    reqs["entities"] = {"roles": ["w"], "resources": []}
    reqs["protocol_params"] = {"accounts": 4}
    (root / "benchmarks/tasks/fam/task/requirements.json").write_text(json.dumps(reqs))
    assert validate_repo(root, "fam/task", checks=("V2",))["tasks"][0]["checks"][0]["status"] == "pass"
    report = tier_repo(root, "fam/task", tools=FallbackTools())
    assert report["tasks"][0]["metrics"]["parameterized"] is True


class IncompleteTools:
    def lower_json(self, skel):
        return {"modules": []}, None

    def explore(self, cir, contract):
        return {"complete": False, "states_explored": 10, "outcome": "UNKNOWN"}, None


def test_incomplete_explore_fails_the_state_condition(tmp_path):
    root = tmp_path / "repo"
    cir = _cir(["main::w"], [_res("m", "Mutex")])
    cir["modules"][0]["functions"][0]["body"].insert(0, _lock("m"))
    _task(root, "fam/open", cir, states=10)
    base = {"tasks": []}
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps(base))
    report = tier_repo(root, "fam/open", tools=IncompleteTools())
    row = report["tasks"][0]
    assert row["metrics"]["states_complete"] is False
    assert row["computed_tier"] is None
    assert row["declared_tier"] == "unclassified"
    assert any(item.startswith("states") for item in row["violations"])


def test_one_task_exception_does_not_abort_tier_repo(tmp_path):
    root = tmp_path / "repo"
    ok = _cir(["main::w"], [_res("m", "Mutex")])
    ok["modules"][0]["functions"][0]["body"].insert(0, _lock("m"))
    _task(root, "fam/ok", ok, states=6)
    boom = _cir([], [])
    _task(root, "fam/boom", boom, states=6)
    (root / "benchmarks" / "tasks" / "fam" / "boom" / "gold.skel").write_text(
        "skeleton boom;\n", encoding="utf-8")
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")

    class Boom:
        def lower_json(self, skel):
            if "boom" in Path(skel).read_text(encoding="utf-8"):
                raise RuntimeError("tier exploded")
            return {"modules": []}, None

        def explore(self, cir, contract):
            return {"complete": True, "states_explored": 6, "outcome": "PASS"}, None

    report = tier_repo(root, "fam/*", tools=Boom())
    by_task = {row["task"]: row for row in report["tasks"]}
    assert by_task["fam/ok"]["computed_tier"] == "L1"
    assert by_task["fam/boom"]["declared_tier"] == "unclassified"
    assert "RuntimeError" in by_task["fam/boom"]["error"]


class _Explored:
    def __init__(self, states: int) -> None:
        self.states = states

    def lower_json(self, skel):
        return {"modules": []}, None

    def explore(self, cir, contract):
        return {"complete": True, "states_explored": self.states, "outcome": "PASS"}, None


def test_nearest_declaration_is_tier_source(tmp_path):
    """One non-state miss is declared nearest; a state miss or two misses are not."""
    root = tmp_path / "repo"
    # 4 threads, 1 used mutex, 10 states: only the L1 thread window is missed.
    threads = _cir(["a", "b", "c", "d"], [_res("m", "Mutex")])
    threads["modules"][0]["functions"][0]["body"].insert(0, _lock("m"))
    _task(root, "fam/threads", threads, states=10)
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
    row = tier_repo(root, "fam/threads", tools=_Explored(10))["tasks"][0]
    assert row["declared_tier"] == "L1" and row["tier_source"] == "nearest"
    assert row["violations"] == ["threads in 0..3"]

    states = _cir(["main::w"], [_res("m", "Mutex")])
    states["modules"][0]["functions"][0]["body"].insert(0, _lock("m"))
    _task(root, "fam/states", states, states=5001)
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
    row = tier_repo(root, "fam/states", tools=_Explored(5001))["tasks"][0]
    assert row["declared_tier"] == "unclassified"
    assert row["violations"] == ["states<=300"]

    both = _cir(["a", "b", "c", "d", "e", "f", "g"],
                [_res(f"m{i}", "Mutex") for i in range(9)])
    both["modules"][0]["functions"][0]["body"] = [
        _lock(f"m{i}", f"u{i}") for i in range(9)
    ] + both["modules"][0]["functions"][0]["body"]
    _task(root, "fam/both", both, states=10)
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
    row = tier_repo(root, "fam/both", tools=_Explored(10))["tasks"][0]
    assert row["declared_tier"] == "unclassified"
    assert len(row["violations"]) >= 2


def test_nearest_accepts_one_structural_miss_but_not_a_state_miss():
    # 4 threads, 1 mutex, 10 states: L1 misses only threads. That is a nearest L1.
    computed, nearest, violations = classify_tier(4, 1, 1, 10, False)
    assert computed is None and nearest == "L1"
    assert violations == ["threads in 0..3"]
    # 2 threads, 1 mutex, 5001 states: L1 misses only states, so the declaration stays unclassified.
    computed, nearest, violations = classify_tier(2, 1, 1, 5001, False)
    assert computed is None and nearest == "L1"
    assert violations == ["states<=300"]
    # Two misses is not a nearest declaration.
    computed, nearest, violations = classify_tier(7, 9, 1, 10, False)
    assert computed is None
    assert len(violations) >= 2


def test_legacy_tier_is_not_rewritten(tmp_path):
    root = tmp_path / "repo"
    cir = _cir(["main::t"], [_res("a", "Mutex")])
    cir["modules"][0]["functions"][0]["body"].insert(0, _lock("main::a"))
    _task(root, "fam/kept", cir, states=10, extra_reqs={
        "tier": "L2", "tier_source": "legacy", "note": "stay"})
    # Not in BASELINE, but explicitly legacy.
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps({"tasks": []}))
    tier_repo(root, "fam/kept", write=True, tools=FallbackTools())
    data = json.loads((root / "benchmarks/tasks/fam/kept/requirements.json").read_text())
    assert data["tier"] == "L2" and data["tier_source"] == "legacy"
    assert data["note"] == "stay"
    assert "fam/kept" in tier_repo(root, "fam/kept", tools=FallbackTools())["legacy_outside_baseline"]


def _tier_binaries() -> bool:
    try:
        from skelnet.backend import Backend
        Backend()
    except FileNotFoundError:
        return False
    return True


def test_real_abba_state_count_comes_from_explore(tmp_path):
    import pytest
    if not _tier_binaries():
        pytest.skip("skelnet or concir-backend binary is not available")
    import shutil
    from skelnet.backend import repo_root
    root = tmp_path / "repo"
    origin = repo_root() / "benchmarks"
    (root / "benchmarks").mkdir(parents=True)
    shutil.copy(origin / "BASELINE.json", root / "benchmarks" / "BASELINE.json")
    shutil.copytree(origin / "tasks" / "lock-order" / "abba_2lock",
                    root / "benchmarks" / "tasks" / "lock-order" / "abba_2lock")
    report = tier_repo(root, "lock-order/abba_2lock")
    row = report["tasks"][0]
    assert row["metrics"]["states_source"] == "explore"
    assert row["metrics"]["states"] == 39
