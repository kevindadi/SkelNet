//! R3d: expression traversal, lexical scopes, loop sites and naming provenance.
use concir::instrument::{wrap, Resource, Wrapped};

fn spawns(w: &Wrapped) -> Vec<&Resource> {
    w.resources.iter().filter(|r| r.kind == "Spawn").collect()
}

fn check(body: &str, count: usize) -> Wrapped {
    let w = wrap(body).unwrap();
    assert_eq!(w.annotated.matches("cir_trace::spawn(").count(), count, "{}", w.annotated);
    assert_eq!(spawns(&w).len(), count);
    assert!(!w.annotated.contains("thread::spawn("), "{}", w.annotated);
    syn::parse_file(&w.annotated).unwrap();
    w
}

macro_rules! expression_test {
    ($name:ident, $body:literal, $count:literal) => {
        #[test]
        fn $name() { check($body, $count); }
    };
}
expression_test!(push_expression, "fn main() { hs.push(thread::spawn(|| {})); }", 1);
expression_test!(vec_macro, "fn main() { let hs = vec![thread::spawn(|| {}), std::thread::spawn(|| {})]; }", 2);
expression_test!(nested_macro, "fn main() { consume!(vec![thread::spawn(|| {})]); }", 1);
expression_test!(map_closure, "fn main() { let hs = (0..3).map(|_| thread::spawn(|| {})).collect::<Vec<_>>(); }", 1);
expression_test!(return_expression, "fn worker() { return thread::spawn(|| {}); } fn main() {}", 1);
expression_test!(if_branches, "fn main() { let h = if flag { thread::spawn(|| {}) } else { thread::spawn(|| {}) }; }", 2);
expression_test!(match_branches, "fn main() { match flag { true => thread::spawn(|| {}), false => thread::spawn(|| {}) }; }", 2);
expression_test!(function_argument, "fn main() { consume(thread::spawn(|| {})); }", 1);
expression_test!(outside_main, "fn worker() { thread::spawn(|| {}); } fn main() {}", 1);
expression_test!(nested_once_without_binding, "fn main() { consume(thread::spawn(|| { thread::spawn(|| {}); })); }", 2);
expression_test!(imported_spawn, "use std::thread::spawn; fn main() { spawn(|| {}); }", 1);
expression_test!(group_imported_spawn, "use std::thread::{self, spawn}; fn main() { spawn(|| {}); thread::spawn(|| {}); }", 2);
expression_test!(local_imported_spawn, "fn main() { use std::thread::spawn; spawn(|| {}); }", 1);

#[test]
fn user_spawn_is_not_a_thread() {
    let w = check("fn spawn() {} fn main() { spawn(); __skelnet_serial_spawn(|| {}); }", 0);
    assert!(w.annotated.contains("spawn(); __skelnet_serial_spawn("));
}

#[test]
fn imported_spawn_does_not_leak_or_override_shadow() {
    let w = check("fn main() { { use std::thread::spawn; spawn(|| {}); } spawn(); }", 1);
    assert!(w.annotated.contains("} spawn();"));
    let w = check("use std::thread::spawn; fn main() { let spawn = custom; spawn(); }", 0);
    assert!(w.annotated.contains("spawn();"));
}

fn check_scope(src: &str, scopes: usize, threads: usize) -> Wrapped {
    let w = wrap(src).unwrap();
    assert_eq!(w.annotated.matches("cir_trace::scope(").count(), scopes, "{}", w.annotated);
    assert_eq!(w.annotated.matches("cir_trace::scope_spawn(").count(), threads);
    assert_eq!(spawns(&w).len(), threads);
    assert!(!w.annotated.contains("thread::scope"));
    assert!(!w.annotated.contains(".spawn("));
    assert!(!w.limitations.iter().any(|l| l.contains("scope")), "{:?}", w.limitations);
    syn::parse_file(&w.annotated).unwrap();
    w
}

#[test]
fn scope_named_handles_and_return_values() {
    let w = check_scope("fn main() { std::thread::scope(|workers| { let t1 = workers.spawn(|| 42); let t2 = workers.spawn(|| 7); assert_eq!(t1.join().unwrap() + t2.join().unwrap(), 49); }); }", 1, 2);
    assert!(w.annotated.contains("scope_spawn(workers, \"t1#"));
    assert_eq!(spawns(&w)[1].display.as_deref(), Some("t2"));
}

#[test]
fn scope_nested_different_and_same_names() {
    for name in ["s", "s2"] {
        check_scope(&format!("fn main() {{ thread::scope(|s| {{ let outer = s.spawn(|| {{ thread::scope(|{name}| {{ {name}.spawn(|| {{}}); }}); }}); }}); }}"), 2, 2);
    }
}

#[test]
fn scope_parameter_in_nested_worker_closure() {
    check_scope("fn main() { thread::scope(|s| { s.spawn(|| { s.spawn(|| {}); }); }); }", 1, 2);
}

#[test]
fn imported_scope() {
    for import in ["use std::thread::scope;", "use std::thread::{self, scope};"] {
        check_scope(&format!("{import} fn main() {{ scope(|s| {{ s.spawn(|| {{}}); }}); }}"), 1, 1);
    }
}

#[test]
fn builder_and_custom_spawn_stay_unsupported() {
    let w = wrap("fn main() { thread::Builder::new().spawn(|| {}); other.spawn(|| {}); }").unwrap();
    assert!(spawns(&w).is_empty());
    assert_eq!(w.annotated.matches(".spawn(").count(), 2);
}

#[test]
fn scope_parameter_shadowing_is_lexical() {
    let w = wrap("fn main() { thread::scope(|s| { { let s = custom; s.spawn(|| {}); } s.spawn(|| {}); let f = |s| s.spawn(|| {}); }); }").unwrap();
    assert_eq!(spawns(&w).len(), 1);
    assert_eq!(w.annotated.matches(".spawn(").count(), 2);
    assert!(w.limitations.iter().any(|l| l.contains("scope parameter")));
}

#[test]
fn unparsed_macro_keeps_limitation_and_residual() {
    let w = wrap("fn main() { custom!(workers => thread::scope(|s| { s.spawn(|| {}); })); }").unwrap();
    assert!(spawns(&w).is_empty());
    assert!(w.annotated.contains("thread::scope"));
    assert!(w.limitations.iter().any(|l| l.contains("unparsed macro")));
    assert!(w.limitations.iter().any(|l| l.contains("thread::scope")));
}

#[test]
fn loop_sites_have_optional_metadata() {
    for body in [
        "for _ in 0..3 { let h = thread::spawn(|| {}); hs.push(h); }",
        "for _ in 0..3 { hs.push(thread::spawn(|| {})); }",
        "let hs = (0..3).map(|_| thread::spawn(|| {})).collect::<Vec<_>>();",
        "while flag { hs.push(thread::spawn(|| {})); }",
        "loop { hs.push(thread::spawn(|| {})); break; }",
    ] {
        let w = check(&format!("fn main() {{ {body} }}"), 1);
        assert_eq!(spawns(&w)[0].in_loop, Some(true), "{body}");
        assert_eq!(serde_json::to_value(spawns(&w)[0]).unwrap()["in_loop"], true);
    }
    let w = check("fn main() { thread::spawn(|| {}); }", 1);
    assert!(serde_json::to_value(spawns(&w)[0]).unwrap().get("in_loop").is_none());
}

#[test]
fn unique_callee_precedes_binding() {
    let w = check("fn main() { let handle = thread::spawn(move || worker()); }", 1);
    let r = spawns(&w)[0];
    assert_eq!(r.display.as_deref(), Some("worker"));
    assert_eq!(r.name_source.as_deref(), Some("callee"));
    assert_eq!(r.binding.as_deref(), Some("handle"));
    assert_eq!(r.unique_entry, Some(true));
}

#[test]
fn binding_precedes_first_call() {
    let w = check("fn main() { let outer = thread::spawn(move || { helper(); worker(); }); }", 1);
    let r = spawns(&w)[0];
    assert_eq!(r.display.as_deref(), Some("outer"));
    assert_eq!(r.entry.as_deref(), Some("helper"));
    assert_eq!(r.name_source.as_deref(), Some("binding"));
    assert_eq!(r.unique_entry, Some(false));
}

#[test]
fn first_call_without_binding() {
    let w = check("fn main() { hs.push(thread::spawn(|| { helper(); worker(); })); }", 1);
    let r = spawns(&w)[0];
    assert_eq!(r.display.as_deref(), Some("helper"));
    assert_eq!(r.name_source.as_deref(), Some("first_call"));
    assert!(r.binding.is_none());
}

#[test]
fn fallback_uses_file_order_not_site_or_container_binding() {
    let w = check("fn worker() { thread::spawn(|| {}); } fn main() { let hs = vec![thread::spawn(|| {}), thread::spawn(|| {})]; }", 3);
    for (i, r) in spawns(&w).iter().enumerate() {
        assert_eq!(r.display.as_deref(), Some(format!("spawn{i}").as_str()));
        assert_eq!(r.name_source.as_deref(), Some("index"));
        assert!(r.binding.is_none());
    }
}

#[test]
fn builtin_paths_are_not_worker_entries() {
    for call in ["clone", "new", "default", "from", "into", "with_capacity", "take", "replace", "swap", "unwrap", "expect"] {
        let w = check(&format!("fn main() {{ let handle = thread::spawn(|| {{ X::{call}(); worker(); }}); }}"), 1);
        let r = spawns(&w)[0];
        assert_eq!(r.display.as_deref(), Some("worker"), "{call}");
        assert_eq!(r.name_source.as_deref(), Some("callee"));
        assert_eq!(r.unique_entry, Some(true));
    }
}

#[test]
fn outer_inline_clone_regression() {
    let w = check("fn main() { let outer = thread::spawn(move || { let a1 = Arc::clone(&a); let x1 = thread::spawn(|| {}); let x2 = thread::spawn(|| {}); x1.join(); x2.join(); }); }", 3);
    let r = spawns(&w)[0];
    assert_eq!(r.display.as_deref(), Some("outer"));
    assert_eq!(r.name_source.as_deref(), Some("binding"));
    assert_eq!(r.binding.as_deref(), Some("outer"));
}

#[test]
fn conditional_scope_parameter_shadowing() {
    let w = wrap("fn main() { thread::scope(|s| { if let Some(s) = other { s.spawn(|| {}); } else { s.spawn(|| {}); } while let Some(s) = other { s.spawn(|| {}); } s.spawn(|| {}); }); }").unwrap();
    assert_eq!(spawns(&w).len(), 2);
    assert_eq!(w.annotated.matches(".spawn(").count(), 2);
}

#[test]
fn module_helper_paths_are_crate_qualified() {
    let w = check("mod worker { fn run() { thread::spawn(|| {}); } } fn main() {}", 1);
    assert!(w.annotated.contains("crate::cir_trace::spawn("));
}

#[test]
fn unsupported_scoped_forms_keep_residual_scope() {
    for source in [
        "use std::thread::scope; fn main() { scope(worker); }",
        "use std::thread::scope; fn main() { scope(|s| { thread::Builder::new().spawn_scoped(s, || {}); }); }",
    ] {
        let w = wrap(source).unwrap();
        assert!(w.annotated.contains("thread::scope("));
        assert!(w.limitations.iter().any(|l| l.contains("thread::scope")));
        assert!(spawns(&w).is_empty());
    }
}

#[test]
fn scope_import_preserves_self_alias() {
    let w = check_scope("use std::thread::{self as threads, scope}; fn main() { scope(|s| { s.spawn(|| {}); }); }", 1, 1);
    assert!(w.annotated.contains("std::thread as threads"));
}
