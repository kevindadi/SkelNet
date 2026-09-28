"""Round 3e: real instrument/build/run/monitor regressions; all outputs in tmp_path."""
import json
from pathlib import Path

import pytest

from round03_helpers import rust_tools
from skelnet import cli
from skelnet.oracle import RustOracle
from skelnet.rusttools.monitor import binding_of, residual_spawns

FIXTURE = Path(__file__).parent / "fixtures" / "round03d" / "abba_2lock"


def _run(source, tmp_path, expected=("pass", None), named=True):
    result = RustOracle(terminal=cli.read_terminal(FIXTURE), task_dir=FIXTURE,
                        layers=("O1", "O2", "O4"), stress_runs=1, monitor_runs=1).evaluate(source, tmp_path)
    assert result.layers["O1"].status == "pass", result.layers["O1"].to_dict()
    assert result.layers["O2"].status == "pass", result.layers["O2"].to_dict()
    o4 = result.layers["O4"]
    assert (o4.status, o4.category) == expected, o4.to_dict()
    assert o4.data["actual_threads"] == 2, o4.to_dict()
    mapping = {binding_of(k): v for k, v in o4.data["mapping"].items()}
    assert mapping["a"] == "main::a" and mapping["b"] == "main::b", mapping
    if named:
        assert mapping["t1"] == "main::t1" and mapping["t2"] == "main::t2", mapping
    inst = tmp_path / "o4" / "instrumented"
    doc = json.loads((inst / "resources.json").read_text())
    annotated = (inst / "annotated.rs").read_text()
    events = [json.loads(line) for line in (tmp_path / "o4" / "traces" / "run0.jsonl").read_text().splitlines()]
    if expected[1] == "instrument_unsupported":
        assert residual_spawns(annotated)
        assert "instrument_unsupported" in o4.data["categories"]
    else:
        assert residual_spawns(annotated) == []
        assert "instrument_unsupported" not in o4.data["categories"]
    # RustOracle intentionally removes target/ after evaluation. Its archived
    # real subprocess results prove that the annotated build and run succeeded.
    calls = result.details["tool_calls"]
    project = str(tmp_path / "o4" / "project")
    builds = [c for c in calls if c["cwd"] == project and "build" in c["argv"]]
    runs = [c for c in calls if Path(c["argv"][0]).name == "o4_probe"]
    assert len(builds) == len(runs) == 1
    assert all(c["returncode"] == 0 and not c["timed_out"] for c in builds + runs)
    return doc, events


PATH_SOURCE = """use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
static A: OnceLock<Arc<Mutex<()>>> = OnceLock::new();
static B: OnceLock<Arc<Mutex<()>>> = OnceLock::new();
fn t1() { let _ga = A.get().unwrap().lock().unwrap(); let _gb = B.get().unwrap().lock().unwrap(); }
fn t2() { let _ga = A.get().unwrap().lock().unwrap(); let _gb = B.get().unwrap().lock().unwrap(); }
fn main() {
    let a = Arc::new(Mutex::new(())); let b = Arc::new(Mutex::new(()));
    let _ = A.set(a); let _ = B.set(b);
    let hs = vec![thread::spawn(t1), thread::spawn(t2)];
    for h in hs { h.join().unwrap(); }
    println!("DONE t1=1 t2=1");
}
"""


@rust_tools
@pytest.mark.parametrize("form", ["thread", "bare", "scope"])
def test_function_path_real_o4(tmp_path, form):
    source = PATH_SOURCE
    if form == "bare":
        source = "use std::thread::spawn;\n" + source.replace("thread::spawn(", "spawn(")
    elif form == "scope":
        source = source.replace("    let hs =", "    thread::scope(|s| { let hs =").replace("thread::spawn(", "s.spawn(").replace("    println!", "    });\n    println!")
    doc, _ = _run(source, tmp_path)
    resources = [r for r in doc["resources"] if r["kind"] == "Spawn"]
    assert len(resources) == 2
    for r, name in zip(resources, ("t1", "t2")):
        assert (r["entry"], r["unique_entry"], r["name_source"]) == (name, True, "callee")


INLINE = """use std::sync::{Arc, Mutex};
use std::thread;
fn main() {
    let mut a = Arc::new(Mutex::new(())); let b = Arc::new(Mutex::new(()));
    // PROBE
    thread::scope(|s| {
        let t1 = s.spawn(|| { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); });
        let t2 = s.spawn(|| { let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap(); });
        t1.join().unwrap(); t2.join().unwrap();
    });
    // AFTER
    println!("DONE t1=1 t2=1");
}
"""


@rust_tools
@pytest.mark.parametrize("form", ["thread", "scope"])
def test_typed_binding_real_o4(tmp_path, form):
    if form == "scope":
        source = INLINE.replace("let t1 =", "let mut t1: thread::ScopedJoinHandle<'_, ()> =").replace("let t2 =", "let t2: thread::ScopedJoinHandle<'_, ()> =")
    else:
        source = INLINE.replace("    thread::scope(|s| {", "    let (a1,b1) = (Arc::clone(&a),Arc::clone(&b));")
        source = source.replace("let t1 = s.spawn(||", "let mut t1: thread::JoinHandle<()> = thread::spawn(move ||")
        source = source.replace("let t2 = s.spawn(||", "let t2: thread::JoinHandle<()> = thread::spawn(move ||")
        source = source.replace("let _ga = a.lock().unwrap(); let _gb = b.lock().unwrap();", "let _ga = a1.lock().unwrap(); let _gb = b1.lock().unwrap();", 1)
        source = source.replace("    });\n    // AFTER", "    // AFTER")
    doc, _ = _run(source, tmp_path)
    for r in [r for r in doc["resources"] if r["kind"] == "Spawn"]:
        assert r["binding"] == r["display"] and r["name_source"] == "binding"


@rust_tools
def test_join_result_is_not_binding_real_o4(tmp_path):
    source = (FIXTURE / "rust" / "push_fn.rs").read_text()
    source = "fn after() {}\n" + source
    source = source.replace("handles.push(thread::spawn(move || t1(a1, b1)));", "let result = thread::spawn(move || { t1(a1,b1); after(); }).join().unwrap();")
    # Leave the second push to give the otherwise unused Vec a concrete type.
    doc, _ = _run(source, tmp_path)
    first = next(r for r in doc["resources"] if r["kind"] == "Spawn")
    assert "binding" not in first
    assert first["name_source"] == "first_call"


@rust_tools
@pytest.mark.parametrize("form", ["push", "scope"])
def test_glob_real_o4(tmp_path, form):
    source = (FIXTURE / "rust" / "push_fn.rs").read_text() if form == "push" else INLINE
    source = source.replace("use std::thread;", "use std::thread::*;").replace("thread::spawn(", "spawn(").replace("thread::scope(", "scope(")
    _run(source, tmp_path)


@rust_tools
@pytest.mark.parametrize("shadow", ["fn_before", "fn_after", "import", "let"])
def test_glob_shadow_real_o4(tmp_path, shadow):
    source = (FIXTURE / "rust" / "push_fn.rs").read_text()
    if shadow == "fn_before":
        items = "fn spawn() {} use std::thread::*;"
    elif shadow == "fn_after":
        items = "use std::thread::*; fn spawn() {}"
    elif shadow == "import":
        items = "mod own { pub fn spawn() {} } use own::spawn; use std::thread::*;"
    else:
        items = "use std::thread::*; let spawn = || {};"
    source = source.replace("fn main() {", f"fn main() {{ {items} spawn();")
    _run(source, tmp_path)


@rust_tools
@pytest.mark.parametrize("import_form", ["named", "glob"])
def test_unparsed_bare_spawn_real_o4(tmp_path, import_form):
    source = (FIXTURE / "rust" / "push_fn.rs").read_text()
    source = source.replace("thread::spawn(", "go!(").replace("use std::thread;", "use std::thread::" + ("spawn;" if import_form == "named" else "*;"))
    source = "macro_rules! go { ($f:expr) => { spawn($f) }; }\n" + source
    doc, _ = _run(source, tmp_path, ("unsupported", "instrument_unsupported"), named=False)
    assert any("unrewritten spawn in unparsed macro body" in note for note in doc["limitations"])


@rust_tools
def test_unparsed_bare_scope_real_o4(tmp_path):
    source = "use std::thread::*; macro_rules! go { ($f:expr) => { scope($f) }; }\n" + INLINE
    source = source.replace("thread::scope(", "go!(")
    doc, _ = _run(source, tmp_path, ("unsupported", "instrument_unsupported"), named=False)
    assert any("unrewritten scope in unparsed macro body" in note for note in doc["limitations"])


@rust_tools
@pytest.mark.parametrize("feature", ["nested_import", "public_nested_import", "debug_mutex", "debug_condvar", "once_set_unwrap", "default_mutex", "try_lock", "into_inner", "get_mut", "is_poisoned", "wait_timeout", "wait_timeout_while"])
def test_wrapper_api_real_o4(tmp_path, feature):
    source = INLINE
    expected = ("pass", None)
    if feature == "nested_import":
        source = source.replace("use std::sync::{Arc, Mutex};\nuse std::thread;", "use std::{sync::{Arc, Mutex}, thread};")
    elif feature == "public_nested_import":
        source = source.replace("use std::sync::{Arc, Mutex};", "use std::sync::Arc; mod locks { pub use std::{sync::Mutex}; }")
        source = source.replace("Mutex::new(", "locks::Mutex::new(")
    elif feature == "debug_mutex":
        source = "#[derive(Debug)] struct S<T> { m: Mutex<T> }\n" + source
        source = source.replace("// PROBE", 'let _ = format!("{:?}", a);')
    elif feature == "debug_condvar":
        source = "use std::sync::Condvar; #[derive(Debug)] struct S { cv: Condvar }\n" + source
    elif feature == "once_set_unwrap":
        source = PATH_SOURCE.replace("let _ = A.set(a); let _ = B.set(b);", "A.set(a).unwrap(); B.set(b).unwrap();")
    elif feature == "default_mutex":
        source = "#[derive(Default)] struct S { m: Mutex<u64> }\n" + source.replace("// PROBE", "let _: S = Default::default();")
    elif feature == "try_lock":
        source = source.replace("// PROBE", "{ let guard = a.try_lock().unwrap(); assert!(matches!(a.try_lock(), Err(std::sync::TryLockError::WouldBlock))); drop(guard); }")
    elif feature == "into_inner":
        source = source.replace("// AFTER", "assert_eq!(Arc::try_unwrap(a).unwrap().into_inner().unwrap(), ());")
    elif feature == "get_mut":
        source = source.replace("// PROBE", "assert_eq!(*Arc::get_mut(&mut a).unwrap().get_mut().unwrap(), ());")
    elif feature == "is_poisoned":
        source = source.replace("// PROBE", "assert!(!a.is_poisoned());")
    else:
        source = "use std::sync::Condvar; use std::time::Duration;\n" + source
        args = "a.lock().unwrap(), Duration::ZERO" + (", |_| false" if feature == "wait_timeout_while" else "")
        source = source.replace("// PROBE", f"let cv = Condvar::new(); let (g, timed) = cv.{feature}({args}).unwrap(); let _ = timed.timed_out(); drop(g);")
        # This API probe intentionally adds a Condvar to the two-lock contract.
        # Compilation/execution must succeed; O4 correctly reports extra_sync.
        expected = ("fail", "design_loss")
    _, events = _run(source, tmp_path, expected)
    if feature in ("try_lock", "wait_timeout", "wait_timeout_while"):
        main_ops = [event["op"] for event in events if event["t"] == "t0"]
        assert main_ops.count("mutex_lock") == 1
        assert main_ops.count("mutex_unlock") == 1
        assert main_ops.count("condvar_wait") == (0 if feature == "try_lock" else 1)
