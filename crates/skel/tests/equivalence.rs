//! P4 acceptance: every migrated gold.skel, lowered and explored, reproduces
//! the frozen BASELINE outcome, completion flag and per-property outcomes.
//! `BASELINE_EXT.json` covers tasks added after the frozen baseline.

use std::path::PathBuf;

use concir::explore::contract::ContractSpec;
use concir::explore::{verify_program, EngineKind};

use skel::check;
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

fn tasks_dir() -> PathBuf {
    repo_root().join("benchmarks/tasks")
}

/// BASELINE names that no longer live at `tasks/<name>`.
///
/// `condvar/same_cv_different_locks` moved to `boundary/` (D9). Its frozen
/// baseline is a ConcIR program that waits on one condvar under two locks
/// (UNSUPPORTED); the DSL replacement lives in `condvar/two_cv_two_locks`.
fn relocated_dir(task: &str) -> Option<&'static str> {
    match task {
        "condvar/same_cv_different_locks" => Some("boundary/same_cv_different_locks"),
        _ => None,
    }
}

fn run_task(task: &str, gold: &str) -> (String, bool, Vec<(String, String)>) {
    let root = repo_root();
    let dir = root.join("benchmarks/tasks").join(task);
    let skel_path = dir.join("gold.skel");
    let src = std::fs::read_to_string(&skel_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", skel_path.display()));
    let (ast, perrs) = parse_source(&skel_path.to_string_lossy(), &src);
    assert!(
        !perrs.iter().any(|e| e.is_error()),
        "{task}: parse errors: {:?}",
        perrs.iter().map(|e| &e.message).collect::<Vec<_>>()
    );
    let cerrs = check::check(&ast, None);
    assert!(
        !cerrs.iter().any(|e| e.is_error()),
        "{task}: check errors: {:?}",
        cerrs.iter().map(|e| (&e.code, &e.message)).collect::<Vec<_>>()
    );
    let lowered = lower::lower(&ast, "gold.skel", &src).unwrap_or_else(|e| {
        panic!("{task}: lower failed: {:?}", e.iter().map(|x| &x.message).collect::<Vec<_>>())
    });
    let contract: ContractSpec = serde_json::from_str(
        &std::fs::read_to_string(dir.join("contract.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(gold_task_gold(task), gold);
    let report = verify_program(&lowered.program, &contract, EngineKind::Petri);
    let props = report
        .properties
        .iter()
        .map(|p| (p.id.clone(), p.outcome.as_str().to_string()))
        .collect();
    (report.outcome.as_str().to_string(), report.complete, props)
}

/// Explore a task's shipped ConcIR gold directly, on the same code path as
/// `concir-backend explore` (`verify_program`). Used for relocated tasks whose
/// directory has no `gold.skel`.
fn run_cir_task(task: &str) -> (String, bool, Vec<(String, String)>) {
    let dir = tasks_dir().join(task);
    let cir_path = dir.join("gold.cir.json");
    let cir = std::fs::read_to_string(&cir_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", cir_path.display()));
    let program: concir::ast::Program = serde_json::from_str(&cir)
        .unwrap_or_else(|e| panic!("{task}: parse gold.cir.json: {e}"));
    let contract: ContractSpec = serde_json::from_str(
        &std::fs::read_to_string(dir.join("contract.json")).unwrap(),
    )
    .unwrap();
    let report = verify_program(&program, &contract, EngineKind::Petri);
    let props = report
        .properties
        .iter()
        .map(|p| (p.id.clone(), p.outcome.as_str().to_string()))
        .collect();
    (report.outcome.as_str().to_string(), report.complete, props)
}

fn gold_task_gold(_task: &str) -> String {
    "gold.cir.json".to_string()
}

fn baseline_properties(entry: &serde_json::Value) -> Vec<(String, String)> {
    entry["properties"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| {
            (
                p["id"].as_str().unwrap().to_string(),
                p["outcome"].as_str().unwrap().to_string(),
            )
        })
        .collect()
}

#[test]
fn gold_skels_match_baseline() {
    let root = repo_root();
    let baseline: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(root.join("benchmarks/BASELINE.json")).unwrap(),
    )
    .unwrap();
    let mut checked = 0;
    for entry in baseline["tasks"].as_array().unwrap() {
        let task = entry["task"].as_str().unwrap();
        if task.starts_with("boundary/") {
            continue; // handled separately (UNSUPPORTED / UNKNOWN below)
        }
        let want_outcome = entry["outcome"].as_str().unwrap();
        let want_complete = entry["complete"].as_bool().unwrap();
        let want = baseline_properties(entry);
        let (outcome, complete, props) = match relocated_dir(task) {
            Some(dir) => run_cir_task(dir),
            None => run_task(task, "gold.cir.json"),
        };
        assert_eq!(outcome, want_outcome, "{task}: outcome");
        assert_eq!(complete, want_complete, "{task}: complete");
        assert_eq!(props, want, "{task}: per-property outcomes");
        checked += 1;
    }
    // 27 baseline tasks - 3 boundary (async/rwlock have no gold.skel;
    // unbounded_int is checked by `unbounded_int_is_unknown`) = 24 compared
    // here: 23 by lowering and verifying gold.skel, plus the relocated
    // `condvar/same_cv_different_locks`, whose shipped gold.cir.json is explored
    // directly.
    assert_eq!(checked, 24, "expected 24 comparable tasks, got {checked}");
}

#[test]
fn unbounded_int_is_unknown() {
    let (outcome, complete, props) = run_task("boundary/unbounded_int_unknown", "gold.cir.json");
    assert_eq!(outcome, "UNKNOWN");
    assert!(!complete);
    assert_eq!(props, vec![("no-deadlock".to_string(), "UNKNOWN".to_string())]);
}

// ── tasks added after the frozen baseline ─────────────────────────────

fn normalize_json(v: &serde_json::Value) -> serde_json::Value {
    match v {
        serde_json::Value::Object(o) => {
            let mut keys: Vec<&String> = o.keys().collect();
            keys.sort();
            let mut m = serde_json::Map::new();
            for k in keys {
                m.insert(k.clone(), normalize_json(&o[k]));
            }
            serde_json::Value::Object(m)
        }
        serde_json::Value::Array(a) => {
            serde_json::Value::Array(a.iter().map(normalize_json).collect())
        }
        other => other.clone(),
    }
}

#[test]
fn baseline_ext_matches_verify_and_shipped_cir() {
    let root = repo_root();
    let ext: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(root.join("benchmarks/BASELINE_EXT.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(ext["schema_version"], "skelnet-baseline-ext-v1");
    let entries = ext["tasks"].as_array().unwrap();
    assert!(!entries.is_empty(), "BASELINE_EXT has no tasks");
    for entry in entries {
        let task = entry["task"].as_str().unwrap();
        let dir = tasks_dir().join(task);
        let skel_path = dir.join("gold.skel");
        let src = std::fs::read_to_string(&skel_path)
            .unwrap_or_else(|e| panic!("read {}: {e}", skel_path.display()));
        let (ast, perrs) = parse_source(&skel_path.to_string_lossy(), &src);
        assert!(
            !perrs.iter().any(|e| e.is_error()),
            "{task}: parse errors: {:?}",
            perrs.iter().map(|e| &e.message).collect::<Vec<_>>()
        );
        let cerrs = check::check(&ast, None);
        assert!(
            !cerrs.iter().any(|e| e.is_error()),
            "{task}: check errors: {:?}",
            cerrs.iter().map(|e| (&e.code, &e.message)).collect::<Vec<_>>()
        );
        let lowered = lower::lower(&ast, "gold.skel", &src)
            .unwrap_or_else(|e| panic!("{task}: lower failed: {:?}", e));

        // The committed gold.cir.json must be exactly this lowering.
        let cir_path = dir.join("gold.cir.json");
        let cir_value: serde_json::Value = serde_json::from_str(
            &std::fs::read_to_string(&cir_path).unwrap_or_else(|e| panic!("read {}: {e}", cir_path.display())),
        )
        .unwrap();
        assert_eq!(
            normalize_json(&serde_json::to_value(&lowered.program).unwrap()),
            normalize_json(&cir_value),
            "{task}: gold.cir.json is not lower(gold.skel)"
        );

        let contract: ContractSpec = serde_json::from_str(
            &std::fs::read_to_string(dir.join("contract.json")).unwrap(),
        )
        .unwrap();
        let report = verify_program(&lowered.program, &contract, EngineKind::Petri);
        assert_eq!(
            report.outcome.as_str(),
            entry["outcome"].as_str().unwrap(),
            "{task}: outcome"
        );
        assert_eq!(
            report.complete,
            entry["complete"].as_bool().unwrap(),
            "{task}: complete"
        );
        let got: Vec<(String, String)> = report
            .properties
            .iter()
            .map(|p| (p.id.clone(), p.outcome.as_str().to_string()))
            .collect();
        assert_eq!(got, baseline_properties(entry), "{task}: per-property outcomes");
    }
}

// ── boundary tasks without a gold.skel: DSL must reject the constructs ──

fn frontend_codes(src: &str) -> Vec<String> {
    let (ast, mut errs) = parse_source("b.skel", src);
    errs.extend(check::check(&ast, None));
    errs.iter().map(|e| e.code.clone()).collect()
}

#[test]
fn rwlock_is_rejected_with_s002() {
    assert!(frontend_codes("skeleton t;\nrwlock r;\nfn main() { }\n").contains(&"S002".to_string()));
}

#[test]
fn async_and_select_are_rejected_with_s002() {
    for src in [
        "skeleton t;\nfn main() { async f(); }\n",
        "skeleton t;\nfn main() { await h; }\n",
        "skeleton t;\nfn main() { select { } }\n",
    ] {
        assert!(
            frontend_codes(src).contains(&"S002".to_string()),
            "expected S002 for {src:?}"
        );
    }
}

#[test]
fn same_cv_different_locks_direct_translation_is_s104() {
    let path = repo_root().join("benchmarks/tasks/boundary/same_cv_different_locks/direct.skel");
    let src = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let codes = frontend_codes(&src);
    assert!(codes.contains(&"S104".to_string()), "direct.skel codes: {codes:?}");
}

// ── real task files must not smuggle shared state into a compute hole ──

#[test]
fn gold_skels_pass_frontend_without_s110() {
    let mut checked = 0;
    let mut families: Vec<PathBuf> = std::fs::read_dir(tasks_dir())
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.is_dir())
        .collect();
    families.sort();
    for fam in families {
        let mut tasks: Vec<PathBuf> = std::fs::read_dir(&fam)
            .unwrap()
            .map(|e| e.unwrap().path())
            .filter(|p| p.is_dir())
            .collect();
        tasks.sort();
        for task in tasks {
            let skel = task.join("gold.skel");
            if !skel.is_file() {
                continue;
            }
            let src = std::fs::read_to_string(&skel).unwrap();
            let (ast, perrs) = parse_source(&skel.to_string_lossy(), &src);
            assert!(
                !perrs.iter().any(|e| e.is_error()),
                "{}: parse errors: {:?}",
                skel.display(),
                perrs.iter().map(|e| &e.message).collect::<Vec<_>>()
            );
            let errs = check::check(&ast, None);
            let s110: Vec<String> = errs
                .iter()
                .filter(|e| e.code == "S110")
                .map(|e| e.message.clone())
                .collect();
            assert!(
                s110.is_empty(),
                "{}: compute footprint names shared state: {s110:?}",
                skel.display()
            );
            assert!(
                !errs.iter().any(|e| e.is_error()),
                "{}: check errors: {:?}",
                skel.display(),
                errs.iter().map(|e| (&e.code, &e.message)).collect::<Vec<_>>()
            );
            checked += 1;
        }
    }
    assert!(checked >= 24, "expected the real task corpus, checked {checked}");
}
