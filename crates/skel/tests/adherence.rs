//! P6 acceptance: deterministic snapshots for `skelnet codegen` and
//! `skelnet adhere` (human-review tool).

use std::path::PathBuf;

use skel::adhere::{adhere, render_markdown};
use skel::check;
use skel::codegen::codegen;
use skel::lower;
use skel::parse_source;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}

fn fixed_rs_tasks() -> Vec<PathBuf> {
    let root = repo_root();
    let mut out = Vec::new();
    for entry in walk(&root.join("benchmarks/tasks")) {
        if entry.file_name().and_then(|s| s.to_str()) == Some("fixed.rs") {
            if let Some(task) = entry.parent().and_then(|p| p.parent()) {
                out.push(task.to_path_buf());
            }
        }
    }
    out.sort();
    out
}

fn walk(dir: &std::path::Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let Ok(read) = std::fs::read_dir(dir) else { return out };
    for e in read.flatten() {
        let p = e.path();
        if p.is_dir() {
            out.extend(walk(&p));
        } else {
            out.push(p);
        }
    }
    out
}

#[test]
fn codegen_abba_snapshot() {
    let root = repo_root();
    let skel_path = root.join("benchmarks/tasks/lock-order/abba_2lock/gold.skel");
    let src = std::fs::read_to_string(&skel_path).unwrap();
    let (ast, _e) = parse_source("gold.skel", &src);
    let lowered = lower::lower(&ast, "gold.skel", &src).unwrap();
    let out = codegen(&lowered.program, &lowered.map).unwrap();
    insta::assert_snapshot!("codegen_abba", out.main_rs);
}

#[test]
fn adhere_snapshots() {
    let root = repo_root();
    for task in fixed_rs_tasks() {
        let skel_path = task.join("gold.skel");
        let rust_path = task.join("rust/fixed.rs");
        if !skel_path.exists() {
            continue;
        }
        let skel_src = std::fs::read_to_string(&skel_path).unwrap();
        let rust_src = std::fs::read_to_string(&rust_path).unwrap();
        let (ast, _e) = parse_source(&skel_path.to_string_lossy(), &skel_src);
        // Pass a repository-relative path so snapshots are machine-independent.
        let rel = task.strip_prefix(&root).unwrap().join("gold.skel");
        let report = adhere(&rel.to_string_lossy(), &ast, &rust_src);
        let md = render_markdown(&report);
        let name = task
            .strip_prefix(root.join("benchmarks/tasks"))
            .unwrap()
            .to_string_lossy()
            .replace('/', "_");
        insta::with_settings!({snapshot_suffix => name.as_str()}, {
            insta::assert_snapshot!("adhere", md);
        });
    }
}

#[test]
fn codegen_is_deterministic_and_annotated() {
    let root = repo_root();
    let skel_path = root.join("benchmarks/tasks/condvar/bare_wait_no_predicate/gold.skel");
    let src = std::fs::read_to_string(&skel_path).unwrap();
    let (ast, _e) = parse_source("gold.skel", &src);
    let lowered = lower::lower(&ast, "gold.skel", &src).unwrap();
    let a = codegen(&lowered.program, &lowered.map).unwrap().main_rs;
    let b = codegen(&lowered.program, &lowered.map).unwrap().main_rs;
    assert_eq!(a, b);
    assert!(a.contains("// skel:L"));
    assert!(a.contains("@R"));
}

#[test]
fn check_used_for_adhere_does_not_require_backend() {
    // adhere only parses; it must work even if the skeleton would not verify.
    let src = "skeleton t;\nmutex a;\nfn main() { }\nfn w() { lock a { } }\n";
    let (ast, _e) = parse_source("t.skel", src);
    assert!(!check::check(&ast, None).iter().any(|e| e.is_error()));
}
