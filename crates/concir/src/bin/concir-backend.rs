//! `concir-backend`: run the non-LLM backend.
//!
//! Subcommands:
//!   check   <program.json>                         static validation
//!   explore <program.json> [contract.json] [interp|petri]   checked verification
//!   run     <program.json>                         list enabled steps from the initial state
//!   support <program.json>                         print the supportability report
//!   schema                                          print the JSON schema
//!   codegen <program.json> --out <dir>              emit a Rust project skeleton
//!   conform <program.json> <trace.jsonl>            reconcile a runtime trace
//!   monitor --contract <c.json> --traces <dir>      runtime monitor report
//!
//! Exit codes (documented, stable):
//!   0 PASS
//!   1 FAIL
//!   2 usage / input error
//!   3 UNKNOWN
//!   4 INVALID (static, semantic, or configuration)
//!   5 UNSUPPORTED

use std::env;
use std::fs;
use std::process;

use concir::ast::Program;
use concir::explore::contract::ContractSpec;
use concir::explore::{verify_program, EngineKind};
use concir::interp::Interpreter;
use concir::sem::outcome::{AnalysisBounds, Outcome};
use concir::sem::program;
use concir::sem::system::TransitionSystem;
use concir::validate;

const EXIT_FAIL: i32 = 1;
const EXIT_USAGE: i32 = 2;
const EXIT_UNKNOWN: i32 = 3;
const EXIT_INVALID: i32 = 4;
const EXIT_UNSUPPORTED: i32 = 5;

fn usage() -> ! {
    eprintln!(
        "usage:\n  \
         concir-backend check   <program.json>\n  \
         concir-backend explore <program.json> [contract.json] [interp|petri]\n  \
         concir-backend run     <program.json>\n  \
         concir-backend support <program.json>\n  \
         concir-backend schema\n  \
         concir-backend codegen <program.json> --out <dir>\n  \
         concir-backend conform <program.json> <trace.jsonl> [--lenient-unlock] [--attempt-events] [--op-resource]\n  \
         concir-backend monitor --contract <contract.json> [--resources <resources.json>] --traces <dir> [--mapping <mapping.json>]\n\n\
         exit codes: 0 pass, 1 fail, 2 usage, 3 unknown, 4 invalid, 5 unsupported"
    );
    process::exit(EXIT_USAGE);
}

fn read(path: &str) -> String {
    match fs::read_to_string(path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error reading '{path}': {e}");
            process::exit(EXIT_USAGE);
        }
    }
}

/// Add `binary_sha256` and `git_rev` to a JSON object output so experiment
/// records are bound to the producing binary.
fn versioned(mut value: serde_json::Value) -> serde_json::Value {
    if let Some(obj) = value.as_object_mut() {
        obj.insert(
            "binary_sha256".into(),
            serde_json::Value::String(concir::hash::binary_sha256()),
        );
        obj.insert(
            "git_rev".into(),
            serde_json::Value::String(concir::hash::git_rev().to_string()),
        );
    }
    value
}

fn parse_program(path: &str) -> Program {
    match serde_json::from_str(&read(path)) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("JSON parse error in '{path}': {e}");
            process::exit(EXIT_USAGE);
        }
    }
}

fn parse_contract(path: Option<&String>) -> ContractSpec {
    let text = match path {
        Some(p) => read(p),
        None => {
            r#"{ "name": "default", "properties": [ { "kind": "deadlock_free", "id": "no-deadlock" } ] }"#
                .to_string()
        }
    };
    match serde_json::from_str(&text) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("contract parse error: {e}");
            process::exit(EXIT_USAGE);
        }
    }
}

fn outcome_exit(outcome: Outcome) -> i32 {
    match outcome {
        Outcome::Pass => 0,
        Outcome::Fail => EXIT_FAIL,
        Outcome::Unknown => EXIT_UNKNOWN,
        Outcome::Invalid => EXIT_INVALID,
        Outcome::Unsupported => EXIT_UNSUPPORTED,
    }
}

fn engine_kind(s: Option<&String>) -> EngineKind {
    match s.map(String::as_str) {
        Some("interp") => EngineKind::Interpreter,
        _ => EngineKind::Petri,
    }
}

fn flag_value(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1).cloned())
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        usage();
    }
    match args[1].as_str() {
        "schema" => {
            let value = concir::schema::schema();
            println!("{}", serde_json::to_string_pretty(&value).expect("serialize"));
        }
        "codegen" => {
            let path = args.get(2).unwrap_or_else(|| usage());
            let out = flag_value(&args, "--out")
                .or_else(|| args.get(3).cloned())
                .unwrap_or_else(|| usage());
            let program = parse_program(path);
            let sem = match program::lower(&program) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("cannot lower program: {e}");
                    process::exit(EXIT_INVALID);
                }
            };
            match concir::codegen::generate(&sem) {
                Ok(generated) => {
                    if let Err(e) =
                        concir::codegen::write_project(std::path::Path::new(&out), &generated)
                    {
                        eprintln!("cannot write codegen output: {e}");
                        process::exit(EXIT_USAGE);
                    }
                    println!(
                        "{}",
                        serde_json::to_string_pretty(&versioned(
                            serde_json::to_value(&generated.map).expect("serialize")
                        ))
                        .expect("serialize")
                    );
                }
                Err(e) => {
                    eprintln!("codegen unsupported: {e}");
                    process::exit(EXIT_UNSUPPORTED);
                }
            }
        }
        "conform" => {
            let path = args.get(2).unwrap_or_else(|| usage());
            let trace_path = args.get(3).unwrap_or_else(|| usage());
            let lenient_unlock = args.iter().any(|a| a == "--lenient-unlock");
            let attempt_events = args.iter().any(|a| a == "--attempt-events");
            let op_resource = args.iter().any(|a| a == "--op-resource");
            let program = parse_program(path);
            let sem = match program::lower(&program) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("cannot lower program: {e}");
                    process::exit(EXIT_INVALID);
                }
            };
            let mut events: Vec<(String, String, String, String)> = Vec::new();
            for line in read(trace_path).lines() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }
                let v: serde_json::Value = match serde_json::from_str(line) {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("bad trace line: {e}");
                        process::exit(EXIT_USAGE);
                    }
                };
                let t = v.get("t").and_then(|x| x.as_str()).unwrap_or("");
                let sid = v.get("sid").and_then(|x| x.as_str()).unwrap_or("");
                let op = v.get("op").and_then(|x| x.as_str()).unwrap_or("");
                let res = v.get("r").and_then(|x| x.as_str()).unwrap_or("");
                events.push((t.to_string(), sid.to_string(), op.to_string(), res.to_string()));
            }
            let result = concir::conform::conform_events(&sem, &events, lenient_unlock,
                                                         attempt_events, op_resource);
            println!(
                "{}",
                serde_json::to_string_pretty(&versioned(
                    serde_json::to_value(&result).expect("serialize")
                ))
                .expect("serialize")
            );
            if result.status != "conformant" {
                process::exit(EXIT_FAIL);
            }
        }
        "monitor" => {
            let contract_path = flag_value(&args, "--contract").unwrap_or_else(|| usage());
            let traces_path = flag_value(&args, "--traces").unwrap_or_else(|| usage());
            let contract: serde_json::Value = match serde_json::from_str(&read(&contract_path)) {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("contract parse error: {e}");
                    process::exit(EXIT_USAGE);
                }
            };
            let parse_value = |path: &str| -> serde_json::Value {
                match serde_json::from_str(&read(path)) {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("JSON parse error in '{path}': {e}");
                        process::exit(EXIT_USAGE);
                    }
                }
            };
            let mut rust_names = match flag_value(&args, "--resources") {
                Some(p) => concir::monitor::load_resources(&parse_value(&p)),
                None => Vec::new(),
            };
            let overrides = match flag_value(&args, "--mapping") {
                Some(p) => concir::monitor::load_overrides(&parse_value(&p)),
                None => std::collections::BTreeMap::new(),
            };
            let traces = match concir::monitor::load_traces(std::path::Path::new(&traces_path)) {
                Ok(t) => t,
                Err(e) => {
                    eprintln!("cannot load traces: {e}");
                    process::exit(EXIT_USAGE);
                }
            };
            if rust_names.is_empty() {
                rust_names = concir::monitor::resources_from_traces(&traces);
            }
            let report = concir::monitor::monitor(&contract, &rust_names, &overrides, &traces);
            println!(
                "{}",
                serde_json::to_string_pretty(&versioned(
                    serde_json::to_value(&report).expect("serialize")
                ))
                .expect("serialize")
            );
            if report.status == "fail" {
                process::exit(EXIT_FAIL);
            }
        }
        "check" => {
            let path = args.get(2).unwrap_or_else(|| usage());
            let program = parse_program(path);
            let report = validate::validate(&program);
            println!(
                "{}",
                serde_json::to_string_pretty(&report).expect("serialize")
            );
            if !report.valid {
                process::exit(EXIT_INVALID);
            }
        }
        "support" => {
            let path = args.get(2).unwrap_or_else(|| usage());
            let program = parse_program(path);
            let sem = match program::lower(&program) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("cannot lower program: {e}");
                    process::exit(EXIT_INVALID);
                }
            };
            let unsupported = sem.unsupported();
            let out = serde_json::json!({
                "supported": unsupported.is_empty(),
                "unsupported": unsupported,
            });
            println!("{}", serde_json::to_string_pretty(&out).expect("serialize"));
            if !unsupported.is_empty() {
                process::exit(EXIT_UNSUPPORTED);
            }
        }
        "run" => {
            let path = args.get(2).unwrap_or_else(|| usage());
            let program = parse_program(path);
            let sem = match program::lower(&program) {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("cannot lower program: {e}");
                    process::exit(EXIT_INVALID);
                }
            };
            let it = Interpreter::new(&sem, AnalysisBounds::default());
            let init = match it.initial() {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("initial state error: {e}");
                    process::exit(EXIT_INVALID);
                }
            };
            match it.successors(&init) {
                Ok(en) => {
                    let labels: Vec<String> =
                        en.steps.iter().map(|s| s.label.canonical()).collect();
                    println!(
                        "{}",
                        serde_json::to_string_pretty(&labels).expect("serialize")
                    );
                }
                Err(e) => {
                    eprintln!("step error: {e}");
                    process::exit(EXIT_INVALID);
                }
            }
        }
        "explore" => {
            let path = args.get(2).unwrap_or_else(|| usage());
            let spec = parse_contract(args.get(3));
            let engine = engine_kind(args.get(4));
            let program = parse_program(path);
            let report = verify_program(&program, &spec, engine);
            println!(
                "{}",
                serde_json::to_string_pretty(&versioned(
                    serde_json::to_value(&report).expect("serialize")
                ))
                .expect("serialize")
            );
            let code = outcome_exit(report.outcome);
            if code != 0 {
                process::exit(code);
            }
        }
        _ => usage(),
    }
}
