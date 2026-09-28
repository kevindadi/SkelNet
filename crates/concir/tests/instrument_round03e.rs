use concir::instrument::{wrap, Resource, Wrapped};

fn spawns(w: &Wrapped) -> Vec<&Resource> {
    w.resources.iter().filter(|r| r.kind == "Spawn").collect()
}

#[test]
fn function_path_thread_entry() {
    let w = wrap("fn main() { let hs = vec![thread::spawn(workers::t1), thread::spawn(t2)]; }").unwrap();
    for (r, name) in spawns(&w).iter().zip(["t1", "t2"]) {
        assert_eq!(r.display.as_deref(), Some(name));
        assert_eq!(r.entry.as_deref(), Some(name));
        assert_eq!(r.unique_entry, Some(true));
        assert_eq!(r.name_source.as_deref(), Some("callee"));
    }
    assert_eq!(spawns(&w).len(), 2);
}

#[test]
fn function_path_bare_entry() {
    let w = wrap("use std::thread::spawn; fn main() { let h = spawn(workers::t1); }").unwrap();
    let r = spawns(&w)[0];
    assert_eq!(r.entry.as_deref(), Some("t1"));
    assert_eq!(r.unique_entry, Some(true));
    assert_eq!(r.name_source.as_deref(), Some("callee"));
    assert_eq!(r.binding.as_deref(), Some("h"));
}

#[test]
fn function_path_scope_entry() {
    let w = wrap("fn main() { thread::scope(|s| { s.spawn(workers::t1); }); }").unwrap();
    let r = spawns(&w)[0];
    assert_eq!(r.entry.as_deref(), Some("t1"));
    assert_eq!(r.unique_entry, Some(true));
    assert_eq!(r.name_source.as_deref(), Some("callee"));
}

#[test]
fn typed_handle_bindings() {
    for src in [
        "fn main() { let mut t1: thread::JoinHandle<()> = (thread::spawn(|| { first(); second(); })); }",
        "fn main() { thread::scope(|s| { let t1: thread::ScopedJoinHandle<'_, ()> = s.spawn(|| { first(); second(); }); }); }",
    ] {
        let w = wrap(src).unwrap();
        let r = spawns(&w)[0];
        assert_eq!(r.binding.as_deref(), Some("t1"));
        assert_eq!(r.display.as_deref(), Some("t1"));
        assert_eq!(r.name_source.as_deref(), Some("binding"));
    }
}

#[test]
fn chained_results_are_not_handle_bindings() {
    for chain in ["join().unwrap()", "thread().id()"] {
        let w = wrap(&format!("fn main() {{ let result = thread::spawn(|| {{}}).{chain}; }}")).unwrap();
        let r = spawns(&w)[0];
        assert!(r.binding.is_none());
        assert_eq!(r.display.as_deref(), Some("spawn0"));
        assert_eq!(r.name_source.as_deref(), Some("index"));
    }
    let w = wrap("fn main() { thread::scope(|s| { let result = s.spawn(|| { first(); second(); }).join(); }); }").unwrap();
    let r = spawns(&w)[0];
    assert!(r.binding.is_none());
    assert_eq!(r.display.as_deref(), Some("first"));
    assert_eq!(r.name_source.as_deref(), Some("first_call"));
}

#[test]
fn glob_imports_spawn_and_scope() {
    let w = wrap("use std::thread::*; fn main() { spawn(|| {}); scope(|s| { s.spawn(|| {}); }); }").unwrap();
    assert_eq!(spawns(&w).len(), 2);
    assert!(w.annotated.contains("cir_trace::scope("));
    assert!(!w.annotated.contains(".spawn("));
}

#[test]
fn glob_shadowing_is_independent_of_item_order() {
    for items in [
        "use std::thread::*; fn spawn() {}",
        "fn spawn() {} use std::thread::*;",
        "use std::thread::*; use custom::spawn;",
        "use custom::spawn; use std::thread::*;",
    ] {
        for src in [format!("{items} fn main() {{ spawn(); }}"), format!("fn main() {{ {items} spawn(); }}")] {
            let w = wrap(&src).unwrap();
            assert!(spawns(&w).is_empty(), "{src}");
        }
    }
    let w = wrap("use std::thread::*; fn main() { let spawn = custom; spawn(); }").unwrap();
    assert!(spawns(&w).is_empty());
}

#[test]
fn glob_does_not_leak() {
    let w = wrap("fn main() { { use std::thread::*; spawn(|| {}); } spawn(); }").unwrap();
    assert_eq!(spawns(&w).len(), 1);
    assert!(w.annotated.contains("} spawn();"));
}

#[test]
fn unparsed_macro_qualifies_imported_calls() {
    for import in ["use std::thread::spawn;", "use std::thread::*;"] {
        let w = wrap(&format!("{import} macro_rules! go {{ ($f:expr) => {{ [spawn($f)] }}; }} fn main() {{}}")).unwrap();
        assert!(w.annotated.contains("[std::thread::spawn($f)]"), "{}", w.annotated);
        assert!(w.limitations.iter().any(|l| l.contains("unrewritten spawn in unparsed macro body")));
        assert!(spawns(&w).is_empty());
    }
    let w = wrap("use std::thread::*; macro_rules! go { ($f:expr) => { scope($f) }; } fn main() {}").unwrap();
    assert!(w.annotated.contains("std::thread::scope($f)"));
    assert!(w.limitations.iter().any(|l| l.contains("unrewritten scope")));
}

#[test]
fn unparsed_macro_does_not_qualify_similar_or_qualified_names() {
    let w = wrap("use std::thread::*; macro_rules! go { ($f:expr) => { spawn_worker($f); __skelnet_serial_spawn($f); thing.spawn($f); thread::spawn($f); $spawn($f); }; } fn main() {}").unwrap();
    assert!(!w.annotated.contains("std::thread::spawn"));
    assert!(w.annotated.contains("spawn_worker($f); __skelnet_serial_spawn($f)"));
    let w = wrap("use std::thread::*; fn spawn() {} macro_rules! go { ($f:expr) => { spawn($f) }; } fn main() {}").unwrap();
    assert!(!w.annotated.contains("std::thread::spawn"));
}

#[test]
fn nested_sync_imports_are_pruned() {
    let w = wrap("use std::{sync::{Arc, Mutex, Condvar}, thread}; fn main() {}").unwrap();
    assert!(w.annotated.contains("use std::{sync::{Arc}, thread};"));
    assert_eq!(w.annotated.matches("use cir_trace::sync::{Mutex, Condvar};").count(), 1);
    assert!(!w.annotated.contains("sync::{Arc, Mutex"));
    let w = wrap("mod m { use std::{sync::{Mutex, Condvar}, thread}; } fn main() {}").unwrap();
    assert!(w.annotated.contains("use crate::cir_trace::sync::{Mutex, Condvar};"));
    syn::parse_file(&w.annotated).unwrap();
}

#[test]
fn legacy_sync_import_spelling_is_preserved() {
    let w = wrap("use std::sync::{Arc, Mutex}; mod m { use std::sync::Mutex; } fn main() {}").unwrap();
    assert!(w.annotated.contains("use std::sync::{Arc};"));
    assert!(w.annotated.contains("mod m { use crate::cir_trace::sync::{Mutex}; }"));
}

#[test]
fn nested_sync_import_preserves_visibility_and_attributes() {
    let w = wrap("mod locks { #[allow(unused_imports)] pub use std::{sync::Mutex}; } fn main() { let a = locks::Mutex::new(()); }").unwrap();
    assert!(w.annotated.contains("#[allow(unused_imports)] pub use crate::cir_trace::sync::{Mutex};"));
}
