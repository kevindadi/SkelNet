"""V1–V9 and the ``bench validate`` command path."""

import json
from pathlib import Path

import pytest

from skelnet import cli
from skelnet.bench import validate_repo

from round03_helpers import cargo_available


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _reqs(**extra) -> dict:
    data = {
        "terminal": "DONE t=1",
        "entities": {"roles": ["t1"], "resources": [{"name": "a", "kind": "lock"}]},
    }
    data.update(extra)
    return data


def _h0(terminal: str = "DONE t=1") -> str:
    return f"# Requirements\n\nR1. Do the work.\nR2. Print `{terminal}`. [U]\n\n## Entities\n\n- Roles: t1.\n"


def _h1(terminal: str = "DONE t=1") -> str:
    return f"# Requirements\n\nR1. Do the work.\nR2. Print `{terminal}`.\n\n## Entities\n\n- Roles: t1.\n"


def _fixed(terminal_expr: str = 'println!("DONE t={}", 1);') -> str:
    return f"fn main() {{ {terminal_expr} }}\n"


def make_task(root: Path, rel: str = "fam/task", *, boundary: bool = False,
              files: dict | None = None, complete: bool = True) -> Path:
    """A minimal task directory. ``files`` overrides text contents."""
    task = root / "benchmarks" / "tasks" / rel
    task.mkdir(parents=True, exist_ok=True)
    blob = files or {}
    if boundary:
        for name in ("contract.json", "ground_truth.json", "spec.md"):
            _write(task / name, blob.get(name, "{}\n" if name.endswith(".json") else "# spec\n"))
        return task
    if not complete and not blob:
        _write(task / "contract.json", "{}\n")
        return task
    mapping = {
        "spec.md": "# spec\n",
        "requirements.json": json.dumps(_reqs(), indent=2) + "\n",
        "REQUIREMENTS.md": _h0(),
        "REQUIREMENTS.h1.md": _h1(),
        "contract.json": "{}\n",
        "gold.skel": "skeleton t;\nfn main() {}\n",
        "gold.cir.json": "{}\n",
        "ground_truth.json": "{}\n",
        "rust/fixed.rs": _fixed(),
        "rust/buggy.rs": "fn main() { println!(\"{}\", 0); }\n",
        "rust/expect.json": json.dumps({
            "schema_version": "skelnet-rust-expect-v1",
            "fixed.rs": {"functional": True},
            "buggy.rs": {"functional": False, "layer": "O3", "category": "deadlock"},
        }) + "\n",
    }
    mapping.update(blob)
    for name, text in mapping.items():
        _write(task / name, text)
    return task


def _baseline(root: Path, rel: str = "fam/task", **fields) -> None:
    entry = {"task": rel, "outcome": "PASS", "complete": True,
             "properties": [{"id": "no-deadlock", "outcome": "PASS"}],
             "states_explored_reference": 10}
    entry.update(fields)
    _write(root / "benchmarks" / "BASELINE.json",
           json.dumps({"schema_version": "skelnet-baseline-v1", "tasks": [entry]}) + "\n")


def _manifest(root: Path, task: Path, rel: str) -> None:
    import hashlib
    rows = []
    for path in sorted(task.rglob("*")):
        if path.is_file():
            rel_file = str(path.relative_to(task))
            rows.append({"task": rel, "file": rel_file,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    _write(root / "benchmarks" / "MANIFEST.json",
           json.dumps({"schema_version": "skelnet-benchmark-manifest-v1", "files": rows}) + "\n")


class OkTools:
    def verify_skel(self, skel, contract):
        return {"outcome": "PASS", "complete": True,
                "properties": [{"id": "no-deadlock", "outcome": "PASS"}]}, None

    def check_skel(self, skel):
        return 1, ["S104"], None

    def lower_json(self, skel):
        return {}, None

    def explore(self, cir, contract):
        return {"outcome": "PASS", "complete": True,
                "properties": [{"id": "no-deadlock", "outcome": "PASS"}],
                "states_explored": 10}, None


def _check(root, rel, name, **kwargs):
    report = validate_repo(root, rel, checks=(name,), tools=kwargs.pop("tools", OkTools()),
                           **kwargs)
    return report["tasks"][0]["checks"][0]


def test_v1_pass_and_missing_buggy(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    assert _check(root, "fam/task", "V1")["status"] == "pass"
    (task / "rust" / "buggy.rs").unlink()
    failed = _check(root, "fam/task", "V1")
    assert failed["status"] == "fail"
    assert "rust/buggy*.rs" in failed["reason"]


def test_v1_boundary_requires_only_three_files(tmp_path):
    root = tmp_path / "repo"
    make_task(root, "boundary/edge", boundary=True)
    assert _check(root, "boundary/edge", "V1")["status"] == "pass"
    for name in ("V2", "V3", "V6"):
        skipped = _check(root, "boundary/edge", name)
        assert skipped["status"] == "skip", name
    (root / "benchmarks" / "tasks" / "boundary" / "edge" / "spec.md").unlink()
    assert _check(root, "boundary/edge", "V1")["status"] == "fail"


def test_v2_allows_an_empty_resource_list(tmp_path):
    root = tmp_path / "repo"
    data = _reqs()
    data["entities"]["resources"] = []
    make_task(root, files={"requirements.json": json.dumps(data) + "\n"})
    assert _check(root, "fam/task", "V2")["status"] == "pass"
    data["entities"].pop("resources")
    (root / "benchmarks" / "tasks" / "fam" / "task" / "requirements.json").write_text(
        json.dumps(data), encoding="utf-8")
    assert _check(root, "fam/task", "V2")["status"] == "fail"


def test_v2_pass_strict_and_placeholder_terminal(tmp_path):
    root = tmp_path / "repo"
    make_task(root)
    assert _check(root, "fam/task", "V2")["status"] == "pass"
    strict = _check(root, "fam/task", "V2", strict=True)
    assert strict["status"] == "fail" and "tier" in strict["reason"]
    reqs = root / "benchmarks" / "tasks" / "fam" / "task" / "requirements.json"
    data = json.loads(reqs.read_text(encoding="utf-8"))
    data["tier"] = "L1"
    reqs.write_text(json.dumps(data), encoding="utf-8")
    assert _check(root, "fam/task", "V2", strict=True)["status"] == "pass"


def test_v2_done_placeholder_needs_a_different_terminal_v2(tmp_path):
    root = tmp_path / "repo"
    make_task(root, files={"requirements.json": json.dumps(_reqs(terminal="DONE done=1")) + "\n"})
    failed = _check(root, "fam/task", "V2")
    assert failed["status"] == "fail" and "terminal_v2" in failed["reason"]
    data = _reqs(terminal="DONE done=1", terminal_v2="DONE done=1")
    (root / "benchmarks" / "tasks" / "fam" / "task" / "requirements.json").write_text(
        json.dumps(data), encoding="utf-8")
    assert "differ" in _check(root, "fam/task", "V2")["reason"]
    data["terminal_v2"] = "DONE value=1"
    data["hint_variants"] = ["h0", "h1"]
    (root / "benchmarks" / "tasks" / "fam" / "task" / "requirements.json").write_text(
        json.dumps(data), encoding="utf-8")
    assert _check(root, "fam/task", "V2")["status"] == "pass"


def test_v3_pass_and_rejects_marker_or_renumbering(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    assert _check(root, "fam/task", "V3")["status"] == "pass"
    (task / "REQUIREMENTS.h1.md").write_text(_h1().replace("R2.", "R9."), encoding="utf-8")
    assert _check(root, "fam/task", "V3")["status"] == "fail"
    (task / "REQUIREMENTS.h1.md").write_text(
        _h1().replace("Do the work.", "Do the work. see contract.json"),
        encoding="utf-8")
    failed = _check(root, "fam/task", "V3")
    assert failed["status"] == "fail" and "contract.json" in failed["reason"]


def test_v4_matches_baseline_and_skips_unmigrated_deviation(tmp_path):
    root = tmp_path / "repo"
    make_task(root)
    _baseline(root)
    assert _check(root, "fam/task", "V4")["status"] == "pass"
    _write(root / "benchmarks" / "DEVIATIONS.json", json.dumps({
        "deviations": [{"kind": "baseline_deviation", "task": "fam/task",
                        "baseline_outcome": "UNSUPPORTED"}]
    }))
    skipped = _check(root, "fam/task", "V4")
    assert skipped["status"] == "skip" and "moved_to" in skipped["reason"]


def test_v4_outcome_mismatch_fails(tmp_path):
    root = tmp_path / "repo"
    make_task(root)
    _baseline(root, outcome="FAIL")
    failed = _check(root, "fam/task", "V4")
    assert failed["status"] == "fail" and "outcome" in failed["reason"]


def test_v4_boundary_direct_skel_must_be_rejected(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root, "boundary/edge", boundary=True)
    _write(task / "direct.skel", "skeleton bad;\n")
    _baseline(root, rel="boundary/edge")
    assert _check(root, "boundary/edge", "V4")["status"] == "pass"
    assert "S104" in _check(root, "boundary/edge", "V4")["reason"]

    class Accepts:
        def verify_skel(self, skel, contract):
            return None, "unused"

        def check_skel(self, skel):
            return 0, [], None

        def explore(self, cir, contract):
            return None, "no cir"

        def lower_json(self, skel):
            return None, "unused"

    failed = _check(root, "boundary/edge", "V4", tools=Accepts())
    assert failed["status"] == "fail" and "exited 0" in failed["reason"]


def test_v4_uses_moved_to_when_the_directory_was_renamed(tmp_path):
    root = tmp_path / "repo"
    make_task(root, "boundary/renamed", boundary=True)
    _write(root / "benchmarks" / "tasks" / "boundary" / "renamed" / "gold.cir.json", "{}\n")
    _baseline(root, rel="condvar/old")
    _write(root / "benchmarks" / "DEVIATIONS.json", json.dumps({
        "deviations": [{"kind": "baseline_deviation", "task": "condvar/old",
                        "moved_to": "boundary/renamed"}]
    }))
    assert _check(root, "boundary/renamed", "V4")["status"] == "pass"


def test_v5_compares_canonical_lowered_json(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    (task / "gold.cir.json").write_text(json.dumps({"b": 1, "a": [2, 1]}) + "\n", encoding="utf-8")
    _write(root / "benchmarks" / "BASELINE_EXT.json", json.dumps({
        "schema_version": "skelnet-baseline-ext-v1",
        "tasks": [{"task": "fam/task", "outcome": "PASS", "complete": True, "properties": []}]
    }))

    class Lower:
        def lower_json(self, skel):
            return {"a": [2, 1], "b": 1}, None

        def verify_skel(self, *a):
            return None, "unused"

        def explore(self, *a):
            return None, "unused"

        def check_skel(self, *a):
            return 0, [], None

    assert _check(root, "fam/task", "V5", tools=Lower())["status"] == "pass"

    class Drift(Lower):
        def lower_json(self, skel):
            return {"a": [2], "b": 1}, None

    assert _check(root, "fam/task", "V5", tools=Drift())["status"] == "fail"
    # A task that is not in the extension file is not checked.
    (root / "benchmarks" / "BASELINE_EXT.json").unlink()
    assert _check(root, "fam/task", "V5", tools=Lower())["status"] == "skip"


def test_v6_rejects_a_hardcoded_terminal_and_honors_the_allowlist(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    assert _check(root, "fam/task", "V6")["status"] == "pass"
    # A formatted print plus a separate literal of the whole terminal line.
    (task / "rust" / "fixed.rs").write_text(
        'fn main() { let s = "DONE t=1"; println!("{}", s); }\n', encoding="utf-8")
    assert _check(root, "fam/task", "V6")["status"] == "fail"
    _write(root / "benchmarks" / "terminal_allowlist.json",
           json.dumps({"fam/task": "prints a constant on purpose"}) + "\n")
    skipped = _check(root, "fam/task", "V6")
    assert skipped["status"] == "skip" and "constant" in skipped["reason"]


def test_v8_functional_and_layer_expectations(tmp_path):
    root = tmp_path / "repo"
    make_task(root)

    class Oracle:
        def evaluate(self, source, workdir):
            if "buggy" in source or 'println!("{}", 0)' in source:
                return type("R", (), {
                    "functional_ok": False,
                    "layers": {"O3": type("L", (), {"status": "fail", "category": "deadlock"})()},
                })()
            return type("R", (), {"functional_ok": True, "layers": {}})()

    def factory(task_dir, terminal):
        return Oracle()

    assert _check(root, "fam/task", "V8", oracle=True, oracle_factory=factory)["status"] == "pass"

    class AlwaysPass(Oracle):
        def evaluate(self, source, workdir):
            return type("R", (), {"functional_ok": True, "layers": {}})()

    failed = _check(root, "fam/task", "V8", oracle=True,
                    oracle_factory=lambda task_dir, terminal: AlwaysPass())
    assert failed["status"] == "fail" and "buggy.rs" in failed["reason"]


def test_v8_without_layers_skips_the_category_check(tmp_path):
    root = tmp_path / "repo"
    make_task(root)

    class Oracle:
        def evaluate(self, source, workdir):
            ok = "buggy" not in source and 'println!("{}", 0)' not in source
            return type("R", (), {"functional_ok": ok, "layers": None})()

    result = _check(root, "fam/task", "V8", oracle=True,
                    oracle_factory=lambda task_dir, terminal: Oracle())
    assert result["status"] == "pass"
    assert "skipped" in result["reason"]


def test_v9_hashes_and_requires_rust_records(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    _manifest(root, task, "fam/task")
    assert _check(root, "fam/task", "V9")["status"] == "pass"
    rows = json.loads((root / "benchmarks" / "MANIFEST.json").read_text(encoding="utf-8"))
    for row in rows["files"]:
        if row["file"] == "rust/fixed.rs":
            row["sha256"] = "0" * 64
    (root / "benchmarks" / "MANIFEST.json").write_text(json.dumps(rows), encoding="utf-8")
    assert _check(root, "fam/task", "V9")["status"] == "fail"


def test_v7_is_skipped_unless_run_is_set(tmp_path):
    root = tmp_path / "repo"
    make_task(root)
    report = validate_repo(root, "fam/task", checks=("V7",), run=False)
    assert report["tasks"][0]["checks"][0]["status"] == "skip"


@pytest.mark.skipif(not cargo_available(), reason="cargo is not available")
def test_v7_cargo_run_matches_the_terminal_line(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    assert _check(root, "fam/task", "V7", run=True)["status"] == "pass"
    (task / "rust" / "fixed.rs").write_text(_fixed('println!("NOPE");'), encoding="utf-8")
    failed = _check(root, "fam/task", "V7", run=True)
    assert failed["status"] == "fail"


def test_cli_main_validate_json(tmp_path, capsys):
    root = tmp_path / "repo"
    make_task(root)
    rc = cli.main(["bench", "validate", "--root", str(root), "--tasks", "fam/task",
                   "--checks", "V1,V2", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fail_count"] == 0
    assert [row["id"] for row in payload["tasks"][0]["checks"]] == ["V1", "V2"]


def test_default_checks_skip_run_and_oracle(tmp_path):
    root = tmp_path / "repo"
    make_task(root)
    _baseline(root)
    _manifest(root, root / "benchmarks" / "tasks" / "fam" / "task", "fam/task")
    report = validate_repo(root, "fam/task", tools=OkTools())
    by_id = {row["id"]: row["status"] for row in report["tasks"][0]["checks"]}
    assert by_id["V7"] == "skip" and by_id["V8"] == "skip"
    assert by_id["V1"] == "pass" and by_id["V4"] == "pass"
