//! Front-end (P2) acceptance: per-code positive/negative checks, fmt round-trip,
//! and a CLI smoke test.

use skel::check::{self, Requirements};
use skel::fmt::fmt_file;
use skel::span::SourceFile;
use skel::parse_source;

const VALID_ABBA: &str = r#"
skeleton abba_2lock;

mutex a;
mutex b;

@R1
fn main() {
    scope { spawn t1(); spawn t2(); }
}

@R2 @R4
fn t1() {
    lock a { lock b { compute "update both records"; } }
}

@R3 @R4
fn t2() {
    lock a { lock b { compute "update both records"; } }
}
"#;

const VALID_CONDVAR: &str = r#"
skeleton bare_wait;

mutex m;
condvar cv for m;
shared ready: Bool = false guarded_by m;

fn main() { scope { spawn waiter(); spawn notifier(); } }

@R4 @R6
fn waiter() {
    lock m {
        while ready == false { cv.wait(); }
    }
}

@R3
fn notifier() {
    lock m {
        ready = true;
        cv.notify_one();
    }
}
"#;

const VALID_MIXED: &str = r#"
skeleton mixed;

atomic c: Int[0..=2] = 0;
semaphore s = 2;
channel ch: Int cap 0;

fn main() {
    scope { spawn w1(); spawn w2(); }
}

fn w2() { }

fn w1() {
    loop {
        let l = c.load();
        let r = c.cas(l, l + 1);
        if r == l { break; }
    }
    s.take();
    s.post();
    permit s { compute "work"; }
    ch.send(1);
    let v = ch.recv();
    let _ = v;
}
"#;

fn parse_errors(src: &str) -> Vec<skel::error::SkError> {
    let (_f, errs) = parse_source("test.skel", src);
    errs
}

fn check_errors(src: &str) -> Vec<skel::error::SkError> {
    let (f, errs) = parse_source("test.skel", src);
    assert!(
        !errs.iter().any(|e| e.is_error()),
        "unexpected parse errors: {:?}",
        errs.iter().map(|e| &e.message).collect::<Vec<_>>()
    );
    check::check(&f, None)
}

fn codes(src: &str) -> Vec<String> {
    check_errors(src).iter().map(|e| e.code.clone()).collect()
}

#[test]
fn valid_programs_have_no_errors() {
    for src in [VALID_ABBA, VALID_CONDVAR, VALID_MIXED] {
        let (f, errs) = parse_source("t.skel", src);
        assert!(!errs.iter().any(|e| e.is_error()), "{errs:?}");
        let errs = check::check(&f, None);
        assert!(
            !errs.iter().any(|e| e.is_error()),
            "unexpected checks: {:?}",
            errs.iter().map(|e| (&e.code, &e.message)).collect::<Vec<_>>()
        );
    }
}

// ── S001 lexer ───────────────────────────────────────────────────────
#[test]
fn s001_lex_error_negative() {
    assert!(parse_errors("skeleton t;\nfn main() { let x = \"oops; }\n")
        .iter()
        .any(|e| e.code == "S001"));
}

#[test]
fn s001_lex_error_positive() {
    assert!(!parse_errors(VALID_MIXED).iter().any(|e| e.code == "S001"));
}

// ── S002 out-of-subset ───────────────────────────────────────────────
#[test]
fn s002_reserved_word_negative_and_hint() {
    let errs = parse_errors("skeleton t;\nrwlock r;\n");
    let e = errs.iter().find(|e| e.code == "S002").expect("S002");
    assert!(e.hint.as_deref().unwrap_or("").contains("mutex"));
}

#[test]
fn s002_reserved_word_positive() {
    assert!(!parse_errors(VALID_ABBA).iter().any(|e| e.code == "S002"));
}

// ── S003 syntax ──────────────────────────────────────────────────────
#[test]
fn s003_syntax_negative() {
    assert!(parse_errors("skeleton t;\nfn main() { let = 1; }\n")
        .iter()
        .any(|e| e.code == "S003"));
}

#[test]
fn s003_syntax_positive() {
    assert!(!parse_errors(VALID_ABBA).iter().any(|e| e.code == "S003"));
}

// ── S101 undefined ───────────────────────────────────────────────────
#[test]
fn s101_undefined_negative() {
    assert!(codes("skeleton t;\nfn main() { let x = nope; }\n").contains(&"S101".to_string()));
}

#[test]
fn s101_undefined_positive() {
    assert!(!codes(VALID_CONDVAR).contains(&"S101".to_string()));
}

// ── S102 duplicate ───────────────────────────────────────────────────
#[test]
fn s102_duplicate_negative() {
    assert!(codes("skeleton t;\nmutex m;\nmutex m;\n").contains(&"S102".to_string()));
}

#[test]
fn s102_duplicate_positive() {
    assert!(!codes(VALID_ABBA).contains(&"S102".to_string()));
}

// ── S103 kind mismatch ───────────────────────────────────────────────
#[test]
fn s103_kind_mismatch_negative() {
    assert!(codes("skeleton t;\nsemaphore s = 1;\nfn main() { lock s { } }\n")
        .contains(&"S103".to_string()));
}

#[test]
fn s103_kind_mismatch_positive() {
    assert!(!codes(VALID_ABBA).contains(&"S103".to_string()));
}

// ── S104 wait outside bound lock ─────────────────────────────────────
#[test]
fn s104_wait_outside_lock_negative() {
    let src = "skeleton t;\nmutex m;\ncondvar cv for m;\nfn main() { cv.wait(); }\n";
    let errs = check_errors(src);
    let e = errs.iter().find(|e| e.code == "S104").expect("S104");
    assert!(e.hint.as_deref().unwrap_or("").contains("lock m"));
}

#[test]
fn s104_wait_inside_lock_positive() {
    assert!(!codes(VALID_CONDVAR).contains(&"S104".to_string()));
}

// ── S105 break/continue outside loop ─────────────────────────────────
#[test]
fn s105_break_outside_loop_negative() {
    assert!(codes("skeleton t;\nfn main() { break; }\n").contains(&"S105".to_string()));
}

#[test]
fn s105_break_inside_loop_positive() {
    let src = "skeleton t;\nfn main() { loop { break; } }\n";
    assert!(!codes(src).contains(&"S105".to_string()));
}

// ── S106 scope spawn target not fn ───────────────────────────────────
#[test]
fn s106_scope_target_not_fn_negative() {
    assert!(
        codes("skeleton t;\nmutex m;\nfn main() { scope { spawn m(); } }\n")
            .contains(&"S106".to_string())
    );
}

#[test]
fn s106_scope_target_fn_positive() {
    assert!(!codes(VALID_ABBA).contains(&"S106".to_string()));
}

// ── S107 join on non-spawn ───────────────────────────────────────────
#[test]
fn s107_join_non_handle_negative() {
    assert!(codes("skeleton t;\nfn main() { let x = 1; x.join(); }\n")
        .contains(&"S107".to_string()));
}

#[test]
fn s107_join_handle_positive() {
    let src = "skeleton t;\nfn worker() { }\nfn main() { let h = spawn worker(); h.join(); }\n";
    assert!(!codes(src).contains(&"S107".to_string()));
}

// ── S108 type / bounds ───────────────────────────────────────────────
#[test]
fn s108_type_negative() {
    assert!(codes("skeleton t;\nshared x: Bool = 1;\n").contains(&"S108".to_string()));
    assert!(codes("skeleton t;\natomic c: Int[0..=2] = 5;\n").contains(&"S108".to_string()));
    assert!(codes("skeleton t;\nfn main() { let x: Bool = 1; let _ = x; }\n")
        .contains(&"S108".to_string()));
}

#[test]
fn s108_type_positive() {
    assert!(!codes(VALID_MIXED).contains(&"S108".to_string()));
}

// ── S109 bad tag ─────────────────────────────────────────────────────
#[test]
fn s109_bad_tag_negative() {
    assert!(check_errors("skeleton t;\n@R fn main() { }\n")
        .iter()
        .any(|e| e.code == "S109"));
}

#[test]
fn s109_bad_tag_positive() {
    let errs = parse_errors(VALID_ABBA);
    assert!(!errs.iter().any(|e| e.code == "S109"));
    assert!(!check_errors(VALID_ABBA).iter().any(|e| e.code == "S109"));
}

// ── S201/S202 requirement tags ───────────────────────────────────────
#[test]
fn s201_missing_requirement_negative() {
    let (f, _e) = parse_source("t.skel", "skeleton t;\n@R1 fn main() { }\n");
    let reqs = Requirements {
        ids: [1u64, 2].into_iter().collect(),
    };
    let errs = check::check(&f, Some(&reqs));
    assert!(errs.iter().any(|e| e.code == "S201" && !e.is_error()));
}

#[test]
fn s201_missing_requirement_positive() {
    let (f, _e) = parse_source("t.skel", "skeleton t;\n@R1 @R2 fn main() { }\n");
    let reqs = Requirements {
        ids: [1u64, 2].into_iter().collect(),
    };
    let errs = check::check(&f, Some(&reqs));
    assert!(!errs.iter().any(|e| e.code == "S201"));
}

#[test]
fn s202_unknown_requirement_negative() {
    let (f, _e) = parse_source("t.skel", "skeleton t;\n@R9 fn main() { }\n");
    let reqs = Requirements {
        ids: [1u64].into_iter().collect(),
    };
    let errs = check::check(&f, Some(&reqs));
    assert!(errs.iter().any(|e| e.code == "S202" && !e.is_error()));
}

#[test]
fn s202_unknown_requirement_positive() {
    let (f, _e) = parse_source("t.skel", "skeleton t;\n@R1 fn main() { }\n");
    let reqs = Requirements {
        ids: [1u64].into_iter().collect(),
    };
    let errs = check::check(&f, Some(&reqs));
    assert!(!errs.iter().any(|e| e.code == "S202"));
}

// ── fmt round-trip ───────────────────────────────────────────────────
fn is_span_object(o: &serde_json::Map<String, serde_json::Value>) -> bool {
    ["start", "end", "line", "col", "end_line", "end_col"]
        .iter()
        .all(|k| o.contains_key(*k))
}

fn normalize(v: &serde_json::Value) -> serde_json::Value {
    match v {
        serde_json::Value::Object(o) => {
            if is_span_object(o) {
                return serde_json::Value::Null;
            }
            let mut m = serde_json::Map::new();
            for (k, val) in o {
                if matches!(
                    k.as_str(),
                    "span" | "name_span" | "close_span" | "desc_span"
                ) {
                    m.insert(k.clone(), serde_json::Value::Null);
                    continue;
                }
                m.insert(k.clone(), normalize(val));
            }
            serde_json::Value::Object(m)
        }
        serde_json::Value::Array(a) => serde_json::Value::Array(a.iter().map(normalize).collect()),
        other => other.clone(),
    }
}

fn assert_round_trip(src: &str) {
    let (f1, e1) = parse_source("t.skel", src);
    assert!(!e1.iter().any(|e| e.is_error()), "{e1:?}");
    let out1 = fmt_file(&f1);
    let (f2, e2) = parse_source("t.skel", &out1);
    assert!(!e2.iter().any(|e| e.is_error()), "reparse: {e2:?}\n{out1}");
    let out2 = fmt_file(&f2);
    assert_eq!(out1, out2, "fmt is not idempotent");
    let n1 = normalize(&serde_json::to_value(&f1).unwrap());
    let n2 = normalize(&serde_json::to_value(&f2).unwrap());
    assert_eq!(n1, n2, "AST changed across fmt round-trip\n{out1}");
}

#[test]
fn fmt_round_trip_examples() {
    for src in [VALID_ABBA, VALID_CONDVAR, VALID_MIXED] {
        assert_round_trip(src);
    }
}

// ── CLI smoke test ───────────────────────────────────────────────────
#[test]
fn cli_check_json_and_exit_codes() {
    let bin = env!("CARGO_BIN_EXE_skelnet");
    let dir = std::env::temp_dir().join(format!("skelnet-cli-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let bad = dir.join("bad.skel");
    std::fs::write(&bad, "skeleton t;\nfn main() { lock nope { } }\n").unwrap();
    let out = std::process::Command::new(bin)
        .args(["check", bad.to_str().unwrap(), "--json"])
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(1));
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).expect("json diagnostics");
    assert!(!v["valid"].as_bool().unwrap());
    assert!(v["diagnostics"]
        .as_array()
        .unwrap()
        .iter()
        .any(|e| e["code"] == "S101"));

    let good = dir.join("good.skel");
    std::fs::write(&good, VALID_ABBA).unwrap();
    let out = std::process::Command::new(bin)
        .args(["check", good.to_str().unwrap()])
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(0));
    let _ = SourceFile::new("x", "");
    let _ = std::fs::remove_dir_all(&dir);
}
