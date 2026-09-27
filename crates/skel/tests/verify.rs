//! P3 acceptance: lowering mapping rows, early-exit release order, and feedback
//! remapping (`unmapped == 0`, counterexample line numbers, no goal disclosure).

use std::collections::BTreeSet;

use concir::explore::contract::ContractSpec;
use concir::explore::{verify_program, EngineKind};
use skel::check;
use skel::error::SkError;
use skel::feedback::{self, Mapper};
use skel::lower;
use skel::span::SourceFile;
use skel::parse_source;

fn lower_source(src: &str) -> (serde_json::Value, serde_json::Value) {
    let (ast, errs) = parse_source("t.skel", src);
    assert!(
        !errs.iter().any(|e| e.is_error()),
        "parse: {:?}",
        errs.iter().map(|e| &e.message).collect::<Vec<_>>()
    );
    let cerrs: Vec<SkError> = check::check(&ast, None);
    assert!(
        !cerrs.iter().any(|e| e.is_error()),
        "check: {:?}",
        cerrs.iter().map(|e| (&e.code, &e.message)).collect::<Vec<_>>()
    );
    let l = lower::lower(&ast, "t.skel", src).expect("lower");
    (
        serde_json::to_value(&l.program).unwrap(),
        serde_json::to_value(&l.map).unwrap(),
    )
}

fn all_ops(program: &serde_json::Value) -> Vec<serde_json::Value> {
    let mut out = Vec::new();
    for m in program["modules"].as_array().unwrap() {
        for f in m["functions"].as_array().unwrap() {
            for s in f["body"].as_array().unwrap() {
                out.push(s.clone());
            }
        }
    }
    out
}

const BIG: &str = r#"
skeleton big;

mutex m;
condvar cv for m;
semaphore s = 2;
channel ch: Int cap 0;
shared x: Bool = false guarded_by m;
atomic c: Int[0..=2] = 0;
extern fn opaque();

fn main() { scope { spawn w(); } }

fn w() {
    lock m {
        permit s { compute "hole"; }
        cv.wait();
        cv.notify_one();
        cv.notify_all();
        ch.send(1);
        let a = ch.recv();
        let b = c.load();
        c.store(b);
        let r = c.cas(b, b + 1);
        x = true;
        let v = x;
        let l = 1;
        l = 2;
        opaque();
        let h = spawn w();
        h.join();
        s.take();
        s.post();
        if v == true { } else { }
        while x == true { break; }
        loop { continue; }
        let _ = a;
        let _ = b;
        let _ = r;
        let _ = l;
    }
}
"#;

#[test]
fn mapping_table_covers_each_row() {
    let (program, map) = lower_source(BIG);
    // Resources.
    let mod0 = &program["modules"][0];
    let res: Vec<(String, String)> = mod0["resources"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| {
            (
                r["name"].as_str().unwrap().to_string(),
                r["type"].as_str().unwrap().to_string(),
            )
        })
        .collect();
    assert!(res.contains(&("m".into(), "Mutex".into())));
    assert!(res.contains(&("cv".into(), "Condvar".into())));
    assert!(res.contains(&("s".into(), "Semaphore".into())));
    assert!(res.contains(&("ch".into(), "Channel".into())));
    assert!(res.contains(&("x".into(), "Var".into())));
    assert!(res.contains(&("c".into(), "Atomic".into())));

    let sem = mod0["resources"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["name"] == "s")
        .unwrap();
    assert_eq!(sem["count"], 2);
    let ch = mod0["resources"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["name"] == "ch")
        .unwrap();
    assert_eq!(ch["capacity"], 0);
    assert_eq!(ch["base"], "Int");
    let c = mod0["resources"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["name"] == "c")
        .unwrap();
    assert_eq!(c["base"]["Int"][0], 0);
    assert_eq!(c["base"]["Int"][1], 2);

    // Protection for the shared variable.
    assert_eq!(mod0["protection"][0]["var"], "x");
    assert_eq!(mod0["protection"][0]["lock"], "m");

    let kinds: BTreeSet<String> = all_ops(&program)
        .iter()
        .map(|s| s["kind"].as_str().unwrap().to_string())
        .collect();
    for expected in [
        "mutex_lock",
        "mutex_unlock",
        "semaphore_acquire",
        "semaphore_release",
        "condvar_wait",
        "condvar_notify",
        "condvar_notify_all",
        "channel_send",
        "channel_recv",
        "atomic_load",
        "atomic_store",
        "atomic_cas",
        "write_shared",
        "read_shared",
        "assign_local",
        "call",
        "spawn",
        "join",
        "scope",
        "branch",
        "goto",
        "nop",
    ] {
        assert!(kinds.contains(expected), "missing op `{expected}`: {kinds:?}");
    }

    // extern fn is a body-less function.
    let opaque = mod0["functions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["name"] == "opaque")
        .unwrap();
    assert!(opaque["body"].as_array().unwrap().is_empty());

    // Source map has json_paths and resources.
    assert!(map["resources"]["main::m"]["span"]["line"].is_number());
    assert_eq!(map["resources"]["main::cv"]["bound_mutex"], "main::m");
    assert!(map["json_paths"]
        .as_object()
        .unwrap()
        .keys()
        .any(|k| k.starts_with("modules[0].functions")));
}

#[test]
fn early_exit_releases_inside_out_and_maps() {
    let src = r#"
skeleton t;
mutex a;
mutex b;
shared flag: Bool = false guarded_by a;
fn work() {
    lock a {
        lock b {
            if flag == false { return; }
        }
    }
}
fn main() { }
"#;
    let (program, map) = lower_source(src);
    let work = program["modules"][0]["functions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["name"] == "work")
        .unwrap();
    let body = work["body"].as_array().unwrap();
    // Find the implicit release statements and the return.
    let rel: Vec<(String, String)> = body
        .iter()
        .filter(|s| s["kind"] == "mutex_unlock")
        .enumerate()
        .map(|(i, s)| (format!("{i}"), s["resource"].as_str().unwrap().to_string()))
        .collect();
    // First the lock b unlock, then lock a unlock, then return.
    assert_eq!(rel[0].1, "main::b");
    assert_eq!(rel[1].1, "main::a");
    let ret_idx = body.iter().position(|s| s["kind"] == "return").unwrap();
    assert!(body[..ret_idx].iter().any(|s| s["kind"] == "mutex_unlock"));

    // Both implicit releases are tagged as such and point at the return line.
    let stmts = map["stmts"].as_array().unwrap();
    let implicit: Vec<&serde_json::Value> = stmts
        .iter()
        .filter(|s| s["construct"] == "implicit_release_on_exit")
        .collect();
    assert_eq!(implicit.len(), 2, "{implicit:?}");
    for s in implicit {
        assert!(s["block_span"].is_object());
    }
}

#[test]
fn lowering_is_total_over_generated_valid_skeletons() {
    // A simple property test: many structurally valid skeletons lower without
    // panicking (the lowerer is total over checked input).
    for n in 1..6usize {
        let mut src = String::from("skeleton gen;\nmutex m;\n");
        for i in 0..n {
            src.push_str(&format!("semaphore s{i} = {i};\n"));
        }
        src.push_str("fn main() { scope {");
        for i in 0..n {
            src.push_str(&format!(" spawn w{i}();"));
        }
        src.push_str(" } }\n");
        for i in 0..n {
            src.push_str(&format!(
                "fn w{i}() {{ permit s{i} {{ compute \"h\"; }} lock m {{ if {} == 0 {{ }} }} }}\n",
                i % 2
            ));
        }
        let (ast, perrs) = parse_source("gen.skel", &src);
        assert!(!perrs.iter().any(|e| e.is_error()), "{perrs:?}");
        let cerrs = check::check(&ast, None);
        assert!(
            !cerrs.iter().any(|e| e.is_error()),
            "n={n}: {:?}",
            cerrs.iter().map(|e| (&e.code, &e.message)).collect::<Vec<_>>()
        );
        let lowered = lower::lower(&ast, "gen.skel", &src);
        assert!(lowered.is_ok(), "n={n} lowering failed");
    }
}

#[test]
fn feedback_remap_has_no_unmapped_and_no_goal_leak() {
    let src = r#"
skeleton abba_bug;
mutex a;
mutex b;
fn main() { scope { spawn t1(); spawn t2(); } }
fn t1() { lock a { lock b { } } }
fn t2() { lock b { lock a { } } }
"#;
    let (ast, _e) = parse_source("abba.skel", src);
    let lowered = lower::lower(&ast, "abba.skel", src).expect("lower");
    let contract: ContractSpec = serde_json::from_str(
        r#"{"name":"t","properties":[{"kind":"deadlock_free","id":"no-deadlock"}]}"#,
    )
    .unwrap();
    let report = verify_program(&lowered.program, &contract, EngineKind::Petri);
    assert_eq!(report.outcome.as_str(), "FAIL");
    let file = SourceFile::new("abba.skel", src);
    let mapper = Mapper::new(&lowered.program, &lowered.map);
    let fb = mapper.map_verify(&report, &Default::default(), &file);
    assert_eq!(fb.unmapped, 0, "unmapped feedback: {fb:?}");
    assert!(!fb.counterexamples.is_empty());
    for ce in &fb.counterexamples {
        assert!(!ce.steps.is_empty());
        for st in &ce.steps {
            assert!(st.skel.is_some(), "step has no DSL line: {st:?}");
            assert!(st.skel.as_ref().unwrap().line > 0);
        }
        let text = feedback::render_counterexample(ce);
        assert!(!text.contains("goal"), "counterexample leaks contract goal");
    }
}
