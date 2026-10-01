"""R3d: real RustOracle -> instrument binary -> Rust runtime -> monitor coverage.

All generated programs, traces and reports live in tmp_path. No mocks are used.
CONCIR_INSTRUMENT/CONCIR_BACKEND can pin the tested workspace build (or a mutant).
"""
import json
from pathlib import Path
import subprocess

import pytest

from round03_helpers import rust_tools
from skelnet import backend, cli
from skelnet.oracle import RustOracle
from skelnet.rusttools.monitor import binding_of, residual_spawns

FIXTURE = Path(__file__).parent / "fixtures" / "round03d"
CASES = [
    ("abba_2lock", "scope_named", 2, ("t1", "t2"), "pass", None),
    ("abba_2lock", "push_fn", 2, ("t1", "t2"), "pass", None),
    ("abba_2lock", "loop3", 3, (), "fail", "not_observed"),
    ("nested_scope_lock_order", "outer_inline", 3, ("outer", "x1", "x2"), "pass", None),
    ("nested_scope_lock_order", "outer_scope", 3, ("outer", "x1", "x2"), "pass", None),
    ("nested_scope_lock_order", "outer_fn", 3, ("outer", "x1", "x2"), "pass", None),
]


def _evaluate(source, tmp_path, task="abba_2lock", threads=2,
              names=("t1", "t2"), status="pass", category=None):
    task_dir = FIXTURE / task
    oracle = RustOracle(terminal=cli.read_terminal(task_dir), task_dir=task_dir,
                        layers=("O1", "O2", "O4"), stress_runs=1, monitor_runs=1)
    result = oracle.evaluate(source, tmp_path)
    o4 = result.layers["O4"]
    assert result.layers["O1"].status == "pass", result.layers["O1"].to_dict()
    assert result.layers["O2"].status == "pass", result.layers["O2"].to_dict()
    assert (o4.status, o4.category) == (status, category), o4.to_dict()
    assert "instrument_unsupported" not in o4.data["categories"], o4.to_dict()
    assert o4.data["actual_threads"] == threads, o4.to_dict()
    mapping = o4.data["mapping"]
    expected = {name: f"main::{name}" for name in ("a", "b", *names)}
    assert {binding_of(k): v for k, v in mapping.items()} == expected, mapping
    assert all("#" in k for k in mapping), mapping
    inst = tmp_path / "o4" / "instrumented"
    assert residual_spawns((inst / "annotated.rs").read_text()) == []
    resources = json.loads((inst / "resources.json").read_text())["resources"]
    spawns = [r for r in resources if r["kind"] == "Spawn"]
    traces = list((tmp_path / "o4" / "traces").glob("*.jsonl"))
    assert len(traces) == 1
    events = [json.loads(line) for line in traces[0].read_text().splitlines()]
    spawn_events = [event for event in events if event["op"] == "spawn"]
    assert len(spawn_events) == threads
    assert len({event["t"] for event in events if event["t"] != "t0"}) == threads
    assert all(set(event) == {"t", "sid", "op", "r"} for event in events)
    assert {event["r"] for event in spawn_events} == {r["name"] for r in spawns}
    assert len({event["sid"] for event in spawn_events}) == threads
    return spawns, o4


@rust_tools
@pytest.mark.parametrize("task,name,threads,names,status,category", CASES, ids=[c[1] for c in CASES])
def test_fixture_real_o4(tmp_path, task, name, threads, names, status, category):
    source = (FIXTURE / task / "rust" / f"{name}.rs").read_text()
    spawns, _ = _evaluate(source, tmp_path, task, threads, names, status, category)
    if name == "loop3":
        assert len(spawns) == 1
        assert spawns[0]["in_loop"] is True
    if name == "outer_inline":
        assert spawns[0]["display"] == "outer"
        assert spawns[0]["name_source"] == "binding"


def _binary():
    try:
        path = backend.find_binary("concir-instrument", env_var="CONCIR_INSTRUMENT")
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    if not path.is_file():
        pytest.skip(f"concir-instrument missing: {path}")
    return path


@pytest.mark.parametrize("task,name,threads,names,status,category", CASES, ids=[c[1] for c in CASES])
def test_wrap_has_no_residual_spawn(tmp_path, task, name, threads, names, status, category):
    # Binary-only test: no cargo or miri needed.
    source = FIXTURE / task / "rust" / f"{name}.rs"
    proc = subprocess.run([str(_binary()), str(source), "--wrappers", "--out", str(tmp_path)],
                          text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert residual_spawns((tmp_path / "annotated.rs").read_text()) == []
    resources = json.loads((tmp_path / "resources.json").read_text())["resources"]
    assert len([r for r in resources if r["kind"] == "Spawn"]) == (1 if name == "loop3" else threads)


HEADER = """use std::sync::{Arc, Mutex};
use std::thread;
fn t1(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); }
fn t2(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); }
"""
MAIN = """fn main() {
    let a = Arc::new(Mutex::new(())); let b = Arc::new(Mutex::new(()));
    let (a1, b1) = (Arc::clone(&a), Arc::clone(&b));
"""
END = '\nprintln!("DONE t1=1 t2=1");\n}'


@rust_tools
@pytest.mark.parametrize("form", ["push", "vec", "return", "argument", "if", "match", "outside_main", "module", "bare", "bare_group", "bare_local"])
def test_expression_forms_real_o4(tmp_path, form):
    spawn = "thread::spawn(move || t1(a1, b1))"
    prefix = ""
    if form == "push":
        body = f"let mut hs = Vec::new(); hs.push({spawn}); for h in hs {{ h.join().unwrap(); }}"
    elif form == "vec":
        body = f"let hs = vec![{spawn}]; for h in hs {{ h.join().unwrap(); }}"
    elif form == "argument":
        prefix = "fn consume(h: thread::JoinHandle<()>) { h.join().unwrap(); }\n"
        body = f"consume({spawn});"
    elif form in ("return", "outside_main", "module"):
        ret = "return " if form == "return" else ""
        prefix = f"fn launch(a1: Arc<Mutex<()>>, b1: Arc<Mutex<()>>) -> thread::JoinHandle<()> {{ {ret}{spawn} }}\n"
        if form == "module":
            prefix = "mod workers { use std::sync::{Arc, Mutex}; use std::thread; use super::t1; " + prefix.replace("fn launch", "pub fn launch") + " }\n"
            body = "workers::launch(a1, b1).join().unwrap();"
        else:
            body = "launch(a1, b1).join().unwrap();"
    elif form in ("if", "match"):
        expr = f"if true {{ {spawn} }} else {{ panic!(\"unused\") }}" if form == "if" else f"match true {{ true => {spawn}, false => panic!(\"unused\") }}"
        body = f"let h = {expr}; h.join().unwrap();"
    else:
        imports = {"bare": "use std::thread::spawn;", "bare_group": "use std::thread::{self as threads, spawn};", "bare_local": ""}
        prefix = imports[form]
        body = ("use std::thread::spawn; " if form == "bare_local" else "") + "let h = spawn(move || t1(a1, b1)); h.join().unwrap();"
    source = HEADER + prefix + MAIN + body + "let h = thread::spawn(move || t2(a,b)); h.join().unwrap();" + END
    _evaluate(source, tmp_path)


@rust_tools
@pytest.mark.parametrize("form", ["for_let", "for_push", "map", "while", "loop"])
def test_repeated_site_real_o4(tmp_path, form):
    source = (FIXTURE / "abba_2lock" / "rust" / "loop3.rs").read_text()
    if form == "for_let":
        source = source.replace("hs.push(thread::spawn(move || worker(a, b)));", "let h = thread::spawn(move || worker(a, b)); hs.push(h);")
    elif form == "map":
        start = source.index("    let mut hs")
        end = source.index("    for h in hs")
        source = source[:start] + "let hs = (0..3).map(|_| { let (a,b) = (Arc::clone(&a),Arc::clone(&b)); thread::spawn(move || worker(a,b)) }).collect::<Vec<_>>();\n" + source[end:]
    elif form in ("while", "loop"):
        loop = "while i < 3 {" if form == "while" else "loop { if i == 3 { break; }"
        source = source.replace("for _ in 0..3 {", f"let mut i = 0; {loop} i += 1;")
    spawns, _ = _evaluate(source, tmp_path, threads=3, names=(), status="fail", category="not_observed")
    assert len(spawns) == 1
    assert spawns[0]["in_loop"] is True


@rust_tools
@pytest.mark.parametrize("form", ["import", "group_import", "parameter", "nested_same", "nested_capture"])
def test_scope_forms_real_o4(tmp_path, form):
    task = "nested_scope_lock_order" if form.startswith("nested") else "abba_2lock"
    name = "outer_scope" if task.startswith("nested") else "scope_named"
    source = (FIXTURE / task / "rust" / f"{name}.rs").read_text()
    if form in ("import", "group_import"):
        source = source.replace("thread::scope(", "scope(")
        source = ("use std::thread::scope;\n" if form == "import" else "use std::thread::{self as threads, scope};\n") + source
    elif form == "parameter":
        source = source.replace("|s|", "|workers|").replace("s.spawn(", "workers.spawn(")
    elif form == "nested_same":
        source = source.replace("s2", "s")
    elif form == "nested_capture":
        source = source.replace("            thread::scope(|s2| {", "            {").replace("s2.spawn", "s.spawn").replace("            });", "            }")
    if task.startswith("nested"):
        _evaluate(source, tmp_path, task, 3, ("outer", "x1", "x2"))
    else:
        _evaluate(source, tmp_path)


@rust_tools
@pytest.mark.parametrize("form", ["binding", "builtins", "first_call"])
def test_naming_real_o4(tmp_path, form):
    if form == "binding":
        prefix = "fn before() {}\nfn work(a: Arc<Mutex<()>>, b: Arc<Mutex<()>>) { t1(a,b); }\n"
        body = "let t1 = thread::spawn(move || { before(); work(a1,b1); }); t1.join().unwrap(); let t2 = thread::spawn(move || { before(); work(a,b); }); t2.join().unwrap();"
        expected_source = "binding"
    elif form == "builtins":
        prefix = ""
        body = "let handle = thread::spawn(move || { let a1 = Arc::clone(&a1); t1(a1,b1); }); handle.join().unwrap(); let h = thread::spawn(move || t2(a,b)); h.join().unwrap();"
        expected_source = "callee"
    else:
        prefix = "fn after() {}\n"
        body = "let mut hs = Vec::new(); hs.push(thread::spawn(move || { t1(a1,b1); after(); })); hs.push(thread::spawn(move || { t2(a,b); after(); })); for h in hs { h.join().unwrap(); }"
        expected_source = "first_call"
    spawns, _ = _evaluate(HEADER + prefix + MAIN + body + END, tmp_path)
    assert spawns[0]["name_source"] == expected_source


def _builder_source() -> str:
    source = (FIXTURE / "abba_2lock" / "rust" / "push_fn.rs").read_text()
    return source.replace("thread::spawn(", "thread::Builder::new().spawn(").replace(
        "b1)));", "b1)).unwrap());").replace("t2(a, b)));", "t2(a, b)).unwrap());")


@rust_tools
def test_builder_form_is_instrumented(tmp_path):
    # R9d-P3: Builder spawns are rewritten, so O4 runs instead of reporting
    # instrument_unsupported.
    task_dir = FIXTURE / "abba_2lock"
    result = RustOracle(terminal=cli.read_terminal(task_dir), task_dir=task_dir,
                        layers=("O1", "O2", "O4"), stress_runs=1,
                        monitor_runs=1).evaluate(_builder_source(), tmp_path)
    assert result.layers["O1"].status == "pass", result.layers["O1"].to_dict()
    o4 = result.layers["O4"]
    assert not (o4.status == "unsupported"
                and o4.category == "instrument_unsupported"), o4.to_dict()
    assert o4.data["actual_threads"] == 2


@rust_tools
@pytest.mark.parametrize("form", ["builder_scoped", "opaque_macro", "custom_method"])
def test_unsupported_forms_keep_real_o4_unsupported(tmp_path, form):
    source = (FIXTURE / "abba_2lock" / "rust" / "scope_named.rs").read_text()
    if form == "builder_scoped":
        source = source.replace("s.spawn(", "thread::Builder::new().spawn_scoped(s, ")
        source = source.replace("; 21 });", "; 21 }).unwrap();")
    elif form == "opaque_macro":
        source = "macro_rules! opaque { (worker => $e:expr) => { $e }; }\n" + source
        source = source.replace("let t1 = s.spawn(", "let t1 = opaque!(worker => s.spawn(").replace("let t2 = s.spawn(", "let t2 = opaque!(worker => s.spawn(").replace("; 21 });", "; 21 }));")
    else:
        source = "struct Custom; impl Custom { fn spawn(&self, f: impl FnOnce()) { f(); } }\n" + source
        source = source.replace("fn main() {", "fn main() { Custom.spawn(|| {});")
    task_dir = FIXTURE / "abba_2lock"
    result = RustOracle(terminal=cli.read_terminal(task_dir), task_dir=task_dir,
                        layers=("O1", "O2", "O4"), stress_runs=1, monitor_runs=1).evaluate(source, tmp_path)
    assert result.layers["O1"].status == "pass", result.layers["O1"].to_dict()
    o4 = result.layers["O4"]
    assert (o4.status, o4.category) == ("unsupported", "instrument_unsupported"), o4.to_dict()
    assert o4.data["actual_threads"] == 2
    assert "instrument_unsupported" in o4.data["categories"]
