"""T7: the three artificial mutant families (snapshot per family)."""

from skelnet.rusttools.mutants import generate_mutants

FIXED = """use std::sync::{Arc, Mutex};
use std::thread;

fn t1(a: Arc<Mutex<()>>) { let _ = a.lock(); }

fn main() {
    let a = Arc::new(Mutex::new(()));
    let h = thread::spawn(move || t1(a));
    h.join().unwrap();
    println!("DONE");
}
"""


def test_print_only_snapshot():
    mutants = generate_mutants(FIXED, terminal="DONE t1=1 t2=1")
    assert mutants["print_only"]["source"] == (
        'fn main() {\n    println!("DONE t1=1 t2=1");\n}\n')


def test_serialized_snapshot():
    source = generate_mutants(FIXED)["serialized"]["source"]
    assert source is not None
    assert "thread::spawn(" not in source
    assert "__skelnet_serial_spawn(" in source
    assert "mod __skelnet_serial" in source


def test_global_lock_snapshot():
    source = generate_mutants(FIXED)["global_lock"]["source"]
    assert source is not None
    assert "__SKELNET_GLOBAL_LOCK" in source
    assert "lock().unwrap();" in source
    assert source.count("__SKELNET_GLOBAL_LOCK.lock().unwrap()") == 1


def test_scope_is_mutant_unsupported():
    mutants = generate_mutants("fn main() { std::thread::scope(|s| {}); }\n")
    assert mutants["serialized"]["source"] is None
    assert mutants["global_lock"]["source"] is None
    assert mutants["serialized"]["reason"] == "thread::scope"
