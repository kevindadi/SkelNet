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
    assert result["status"] == "fail"
    assert "no layers" in result["reason"]


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
    (task / "requirements.json").write_text(
        json.dumps(_reqs(terminal="DONE x=1")) + "\n", encoding="utf-8")
    (task / "rust" / "fixed.rs").write_text(
        'fn main() { let x = 1; println!("DONE x={} ", x); }\n', encoding="utf-8")
    spaced = _check(root, "fam/task", "V7", run=True)
    assert spaced["status"] == "fail" and "DONE x=1 " in spaced["reason"]
    (task / "rust" / "fixed.rs").write_text(
        'fn main() { let x = 1; println!("DONE x={}", x); std::process::exit(1); }\n',
        encoding="utf-8")
    exited = _check(root, "fam/task", "V7", run=True)
    assert exited["status"] == "fail" and "exit" in exited["reason"]


def test_cli_main_validate_json(tmp_path, capsys):
    root = tmp_path / "repo"
    make_task(root)
    rc = cli.main(["bench", "validate", "--root", str(root), "--tasks", "fam/task",
                   "--checks", "V1,V2", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fail_count"] == 0
    assert [row["id"] for row in payload["tasks"][0]["checks"]] == ["V1", "V2"]


def test_v2_rejects_a_non_list_hint_and_a_missing_hint_file(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    data = _reqs(hint_variants=5)
    (task / "requirements.json").write_text(json.dumps(data), encoding="utf-8")
    failed = _check(root, "fam/task", "V2")
    assert failed["status"] == "fail"
    assert "TypeError" not in failed["reason"]
    assert "hint_variants" in failed["reason"]
    data = _reqs(hint_variants=["h1"])
    (task / "requirements.json").write_text(json.dumps(data), encoding="utf-8")
    (task / "REQUIREMENTS.h1.md").unlink()
    missing = _check(root, "fam/task", "V2")
    assert missing["status"] == "fail" and "REQUIREMENTS.h1.md" in missing["reason"]


def test_v3_entities_marker_terminal_v2_and_task_path(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    h1 = _h1().replace("- Roles: t1.", "- Roles: other.")
    (task / "REQUIREMENTS.h1.md").write_text(h1, encoding="utf-8")
    assert "Entities" in _check(root, "fam/task", "V3")["reason"]
    (task / "REQUIREMENTS.h1.md").write_text(_h1() + "still [U]\n", encoding="utf-8")
    # Keep the entities section identical; the marker sits after it only if a
    # later heading closes the section. Put [U] in the requirement sentence.
    (task / "REQUIREMENTS.h1.md").write_text(
        _h1().replace("Do the work.", "Do the work. [U]"), encoding="utf-8")
    assert "[U]" in _check(root, "fam/task", "V3")["reason"]
    data = _reqs(terminal="DONE done=1", terminal_v2="DONE value=2")
    (task / "requirements.json").write_text(json.dumps(data), encoding="utf-8")
    (task / "REQUIREMENTS.h1.md").write_text(_h1("DONE done=1"), encoding="utf-8")
    (task / "REQUIREMENTS.md").write_text(_h0("DONE done=1"), encoding="utf-8")
    quoted = _check(root, "fam/task", "V3")
    assert quoted["status"] == "fail" and "terminal" in quoted["reason"]
    (task / "REQUIREMENTS.h1.md").write_text(
        _h1("DONE value=2").replace("Do the work.", "Do the work in fam/task."),
        encoding="utf-8")
    assert "fam/task" in _check(root, "fam/task", "V3")["reason"]


def test_v4_complete_and_property_mismatches(tmp_path):
    root = tmp_path / "repo"
    make_task(root)
    _baseline(root, complete=False)
    complete = _check(root, "fam/task", "V4")
    assert complete["status"] == "fail" and "complete" in complete["reason"]
    _baseline(root, properties=[{"id": "other", "outcome": "PASS"}])
    assert "missing" in _check(root, "fam/task", "V4")["reason"]
    _baseline(root, properties=[{"id": "no-deadlock", "outcome": "PASS"},
                                {"id": "extra", "outcome": "PASS"}])
    assert "extra" in _check(root, "fam/task", "V4")["reason"]
    _baseline(root, properties=[{"id": "no-deadlock", "outcome": "FAIL"}])
    assert "changed" in _check(root, "fam/task", "V4")["reason"]


def test_tool_error_text_is_not_a_missing_binary(tmp_path):
    from skelnet.bench import ToolUnavailable
    root = tmp_path / "repo"
    make_task(root)
    _baseline(root)

    class Plain:
        def verify_skel(self, skel, contract):
            return None, "entry function `main::main` was not found"

        def explore(self, *args):
            return None, "entry function `main::main` was not found"

        def check_skel(self, skel):
            return 1, [], None

        def lower_json(self, skel):
            return None, "entry function `main::main` was not found"

    failed = _check(root, "fam/task", "V4", tools=Plain())
    assert failed["status"] == "fail" and "not found" in failed["reason"]

    class Missing:
        def verify_skel(self, skel, contract):
            return None, ToolUnavailable("skelnet binary is not available")

        def explore(self, *args):
            return None, ToolUnavailable("concir-backend binary is not available")

        def check_skel(self, skel):
            return None, [], ToolUnavailable("skelnet binary is not available")

        def lower_json(self, skel):
            return None, ToolUnavailable("skelnet binary is not available")

    assert _check(root, "fam/task", "V4", tools=Missing())["status"] == "skip"


def test_injected_tool_exception_is_a_failed_check(tmp_path):
    root = tmp_path / "repo"
    make_task(root)
    _baseline(root)

    class Boom:
        def verify_skel(self, skel, contract):
            raise RuntimeError("boom")

    failed = _check(root, "fam/task", "V4", tools=Boom())
    assert failed["status"] == "fail" and failed["reason"].startswith("RuntimeError:")


def test_v6_format_shapes_and_split_prints(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root, files={
        "requirements.json": json.dumps(_reqs(terminal="DONE t1=1 t2=1")) + "\n",
        "REQUIREMENTS.md": _h0("DONE t1=1 t2=1"),
        "REQUIREMENTS.h1.md": _h1("DONE t1=1 t2=1"),
    })
    passing = [
        'println!("DONE t1={:?} t2={:?}", a, b);',
        'println!("DONE t1={0} t2={1}", a, b);',
        'println!("DONE t1={a:>1} t2={b:?}");',
        'writeln!(std::io::stdout(), "DONE t1={} t2={}", a, b);',
        'let line = format!("DONE t1={} t2={}", a, b); println!("{}", line);',
        'let line = format!("DONE t1={} t2={}", a, b); println!("{line}");',
        '// "DONE t1=1 t2=1"\n    println!("DONE t1={} t2={}", a, b);',
    ]
    for body in passing:
        (task / "rust" / "fixed.rs").write_text(
            f"fn main() {{ let (a, b) = (1, 1); {body} }}\n", encoding="utf-8")
        assert _check(root, "fam/task", "V6")["status"] == "pass", body
    # A correct println! is also present, so this fails only because `\n` decodes
    # to a newline and the literal line equals the terminal.
    (task / "rust" / "fixed.rs").write_text(
        'fn main() { let (a, b) = (1, 1);\n'
        '    print!("DONE t1=1 t2=1\\n");\n'
        '    println!("DONE t1={} t2={}", a, b);\n'
        '}\n', encoding="utf-8")
    assert _check(root, "fam/task", "V6")["status"] == "fail"
    (task / "rust" / "fixed.rs").write_text(
        'fn main() {\n'
        '    // println!("DONE t1=1 t2=1");\n'
        '    let r = 1;\n'
        '    print!("DONE ");\n'
        '    println!("t1=1 t2=1");\n'
        '    println!("round {}", r);\n'
        '}\n', encoding="utf-8")
    assert _check(root, "fam/task", "V6")["status"] == "fail"


def test_v8_schema_layer_and_default_factory(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    task = make_task(root)
    expect_path = task / "rust" / "expect.json"
    expect = json.loads(expect_path.read_text(encoding="utf-8"))
    del expect["buggy.rs"]
    expect_path.write_text(json.dumps(expect), encoding="utf-8")
    assert "missing" in _check(root, "fam/task", "V8", oracle=True)["reason"]

    def restore(spec):
        expect_path.write_text(json.dumps({
            "schema_version": "skelnet-rust-expect-v1",
            "fixed.rs": {"functional": True},
            "buggy.rs": spec,
        }), encoding="utf-8")

    restore({"functional": False, "layer": "O1", "category": "deadlock"})
    assert "not valid" in _check(root, "fam/task", "V8", oracle=True)["reason"]

    restore({"functional": False, "layer": "O3", "category": "deadlock"})

    def factory(task_dir, terminal, category="deadlock", status="fail"):
        class Oracle:
            def evaluate(self, source, workdir):
                ok = "println!(\"{}\", 0)" not in source
                return type("R", (), {
                    "functional_ok": ok,
                    "layers": {"O3": type("L", (), {"status": status, "category": category})()},
                })()
        return Oracle()

    hang = _check(root, "fam/task", "V8", oracle=True,
                  oracle_factory=lambda task_dir, terminal: factory(
                      task_dir, terminal, category="hang"))
    assert hang["status"] == "fail" and "hang" in hang["reason"]
    passed_layer = _check(root, "fam/task", "V8", oracle=True,
                          oracle_factory=lambda task_dir, terminal: factory(
                              task_dir, terminal, status="pass"))
    assert passed_layer["status"] == "fail" and "status=pass" in passed_layer["reason"]

    seen = {}

    def recording(task_dir, terminal):
        seen["task_dir"] = task_dir
        seen["terminal"] = terminal
        return factory(task_dir, terminal)

    monkeypatch.setattr("skelnet.cli.default_oracle_factory",
                        lambda timeout: recording)
    result = _check(root, "fam/task", "V8", oracle=True)
    assert result["status"] == "pass"
    assert seen["task_dir"] == task
    from skelnet import cli
    assert seen["terminal"] == cli.read_terminal(task)


def test_v9_missing_record_and_missing_file(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root)
    _manifest(root, task, "fam/task")
    rows = json.loads((root / "benchmarks" / "MANIFEST.json").read_text(encoding="utf-8"))
    rows["files"] = [row for row in rows["files"] if row["file"] != "rust/buggy.rs"]
    (root / "benchmarks" / "MANIFEST.json").write_text(json.dumps(rows), encoding="utf-8")
    assert "MANIFEST missing" in _check(root, "fam/task", "V9")["reason"]
    rows["files"].append({"task": "fam/task", "file": "rust/missing.rs", "sha256": "abc"})
    (root / "benchmarks" / "MANIFEST.json").write_text(json.dumps(rows), encoding="utf-8")
    assert "missing rust/missing.rs" in _check(root, "fam/task", "V9")["reason"]


def test_cli_task_patterns_and_zero_matches(tmp_path, capsys):
    root = tmp_path / "repo"
    make_task(root, "boundary/edge", boundary=True)
    make_task(root, "condvar/cv")
    make_task(root, "fam/task")
    rc = cli.main(["bench", "validate", "--root", str(root), "--tasks",
                   "boundary/*,condvar/*", "--checks", "V1", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc in (0, 1)
    assert {row["task"] for row in payload["tasks"]} == {"boundary/edge", "condvar/cv"}
    rc = cli.main(["bench", "validate", "--root", str(root), "--tasks", "nomatch", "--json"])
    captured = capsys.readouterr()
    assert rc == 2 and "nomatch" in captured.err and captured.out.strip() == ""
    rc = cli.main(["bench", "validate", "--root", str(root), "--tasks",
                   "fam/*,nomatch", "--json"])
    captured = capsys.readouterr()
    assert rc == 2 and "nomatch" in captured.err and captured.out.strip() == ""
    rc = cli.main(["bench", "tiers", "--root", str(root), "--tasks", "nomatch", "--write"])
    captured = capsys.readouterr()
    assert rc == 2 and "nomatch" in captured.err
    assert not (root / "benchmarks" / "TIERS.md").exists()


def test_default_checks_skip_run_and_oracle(tmp_path):
    root = tmp_path / "repo"
    make_task(root)
    _baseline(root)
    _manifest(root, root / "benchmarks" / "tasks" / "fam" / "task", "fam/task")
    report = validate_repo(root, "fam/task", tools=OkTools())
    by_id = {row["id"]: row["status"] for row in report["tasks"][0]["checks"]}
    assert by_id["V7"] == "skip" and by_id["V8"] == "skip"
    assert by_id["V1"] == "pass" and by_id["V4"] == "pass"


def _binaries_available() -> bool:
    try:
        from skelnet.backend import Backend
        Backend()
    except FileNotFoundError:
        return False
    return True


def _copy_tasks(tmp_path, rels: list[str]) -> Path:
    import shutil
    from skelnet.backend import repo_root
    root = tmp_path / "repo"
    bench = root / "benchmarks"
    bench.mkdir(parents=True)
    origin = repo_root() / "benchmarks"
    for name in ("BASELINE.json", "DEVIATIONS.json", "MANIFEST.json", "BASELINE_EXT.json"):
        if (origin / name).is_file():
            shutil.copy(origin / name, bench / name)
    for rel in rels:
        shutil.copytree(origin / "tasks" / rel, bench / "tasks" / rel)
    return root


@pytest.mark.skipif(not _binaries_available(),
                    reason="skelnet or concir-backend binary is not available")
def test_real_frontend_error_does_not_abort_the_run(tmp_path):
    root = _copy_tasks(tmp_path, ["lock-order/abba_2lock"])
    broken = root / "benchmarks" / "tasks" / "lock-order" / "broken"
    import shutil
    shutil.copytree(root / "benchmarks" / "tasks" / "lock-order" / "abba_2lock", broken)
    (broken / "gold.skel").write_text(
        "skeleton broken;\nfn main() { lock zz { } }\n", encoding="utf-8")
    base = json.loads((root / "benchmarks" / "BASELINE.json").read_text(encoding="utf-8"))
    abba = next(row for row in base["tasks"] if row["task"] == "lock-order/abba_2lock")
    base["tasks"].append({**abba, "task": "lock-order/broken"})
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps(base), encoding="utf-8")
    report = validate_repo(root, "lock-order/*", checks=("V4",))
    by_task = {row["task"]: row["checks"][0] for row in report["tasks"]}
    assert by_task["lock-order/broken"]["status"] == "fail"
    assert "S101" in by_task["lock-order/broken"]["reason"]
    assert by_task["lock-order/abba_2lock"]["status"] == "pass"


@pytest.mark.skipif(not _binaries_available(),
                    reason="skelnet or concir-backend binary is not available")
def test_real_missing_main_is_a_v4_failure(tmp_path):
    root = _copy_tasks(tmp_path, ["lock-order/abba_2lock"])
    skel = root / "benchmarks" / "tasks" / "lock-order" / "abba_2lock" / "gold.skel"
    skel.write_text("skeleton abba_2lock;\nmutex a;\nmutex b;\nfn t1() {}\n", encoding="utf-8")
    result = validate_repo(root, "lock-order/abba_2lock", checks=("V4",))
    row = result["tasks"][0]["checks"][0]
    assert row["status"] == "fail"
    assert "not found" in row["reason"] or "frontend" in row["reason"]


@pytest.mark.skipif(not _binaries_available(),
                    reason="skelnet or concir-backend binary is not available")
def test_real_abba_v4_and_changed_property(tmp_path):
    root = _copy_tasks(tmp_path, ["lock-order/abba_2lock"])
    assert validate_repo(root, "lock-order/abba_2lock", checks=("V4",))["tasks"][0]["checks"][0]["status"] == "pass"
    base = json.loads((root / "benchmarks" / "BASELINE.json").read_text(encoding="utf-8"))
    for row in base["tasks"]:
        if row["task"] == "lock-order/abba_2lock":
            row["properties"][0]["outcome"] = "FAIL"
    (root / "benchmarks" / "BASELINE.json").write_text(json.dumps(base), encoding="utf-8")
    failed = validate_repo(root, "lock-order/abba_2lock", checks=("V4",))["tasks"][0]["checks"][0]
    assert failed["status"] == "fail"


@pytest.mark.skipif(not _binaries_available(),
                    reason="skelnet or concir-backend binary is not available")
def test_real_lowered_cir_matches_until_a_field_changes(tmp_path):
    root = _copy_tasks(tmp_path, ["condvar/two_cv_two_locks"])
    passed = validate_repo(root, "condvar/two_cv_two_locks", checks=("V5",))["tasks"][0]["checks"][0]
    assert passed["status"] == "pass", passed
    cir = root / "benchmarks" / "tasks" / "condvar" / "two_cv_two_locks" / "gold.cir.json"
    data = json.loads(cir.read_text(encoding="utf-8"))
    data["program"] = "tampered"
    cir.write_text(json.dumps(data), encoding="utf-8")
    assert validate_repo(root, "condvar/two_cv_two_locks", checks=("V5",))["tasks"][0]["checks"][0]["status"] == "fail"


def test_boundary_v7_v8_skip_with_run_and_oracle(tmp_path):
    root = tmp_path / "repo"
    make_task(root, "boundary/edge", boundary=True)
    report = validate_repo(root, "boundary/edge", run=True, oracle=True, tools=OkTools())
    checks = {row["id"]: row for row in report["tasks"][0]["checks"]}
    assert checks["V7"]["status"] == "skip"
    assert checks["V7"]["reason"] == "boundary task has no reference program"
    assert checks["V8"]["status"] == "skip"
    assert checks["V8"]["reason"] == "boundary task has no reference program"
    without = validate_repo(root, "boundary/edge", tools=OkTools())
    plain = {row["id"]: row for row in without["tasks"][0]["checks"]}
    assert plain["V7"]["reason"] == "not requested (--run)"
    assert plain["V8"]["reason"] == "not requested (--oracle)"


def test_main_task_missing_fixed_still_fails_v7_v8(tmp_path):
    root = tmp_path / "repo"
    task = make_task(root, "fam/task")
    (task / "rust" / "fixed.rs").unlink()
    report = validate_repo(root, "fam/task", checks=("V7", "V8"), run=True,
                           oracle=True, tools=OkTools())
    rows = report["tasks"][0]["checks"]
    assert [row["status"] for row in rows] == ["fail", "fail"]
    assert "fixed.rs is missing" in rows[0]["reason"]
    assert "fixed.rs is missing" in rows[1]["reason"]


def test_only_boundary_tasks_strict_run_oracle_exits_0(tmp_path, capsys):
    root = tmp_path / "repo"
    task = make_task(root, "boundary/only", boundary=True)
    _manifest(root, task, "boundary/only")
    rc = cli.main([
        "bench", "validate", "--root", str(root), "--tasks", "boundary/*",
        "--run", "--oracle", "--strict", "--json",
    ])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    report = json.loads(captured.out)
    assert report["fail_count"] == 0
    checks = {row["id"]: row for row in report["tasks"][0]["checks"]}
    assert checks["V7"]["status"] == "skip"
    assert checks["V8"]["status"] == "skip"
