//! `skelnet` — the Skeleton DSL command-line tool.

use std::fs;
use std::process;

use concir::explore::contract::ContractSpec;
use concir::explore::{verify_program, EngineKind};

use skel::check::{self, Requirements};
use skel::error::{self, Origin, Severity, SkError};
use skel::feedback::{self, Mapper};
use skel::lower;
use skel::span::SourceFile;
use skel::{fmt as skelfmt, parse_source};

const EXIT_OK: i32 = 0;
const EXIT_DIAG: i32 = 1;
const EXIT_USAGE: i32 = 2;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        usage();
    }
    let code = match args[1].as_str() {
        "parse" => cmd_parse(&args[2..]),
        "fmt" => cmd_fmt(&args[2..]),
        "lower" => cmd_lower(&args[2..]),
        "check" => cmd_check(&args[2..]),
        "verify" => cmd_verify(&args[2..]),
        "--help" | "-h" | "help" => usage(),
        other => {
            eprintln!("skelnet: unknown command `{other}`");
            usage();
        }
    };
    process::exit(code);
}

fn usage() -> ! {
    eprintln!(
        "usage:\n  \
         skelnet parse  <f.skel> [--json]\n  \
         skelnet fmt    <f.skel> [--check]\n  \
         skelnet lower  <f.skel> -o <f.cir.json> [--map <f.map.json>]\n  \
         skelnet check  <f.skel> [--reqs requirements.json] [--json]\n  \
         skelnet verify <f.skel> <contract.json> [--engine petri|interp] [--json]"
    );
    process::exit(EXIT_USAGE);
}

fn read_file(path: &str) -> String {
    match fs::read_to_string(path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("skelnet: cannot read '{path}': {e}");
            process::exit(EXIT_USAGE);
        }
    }
}

fn flag_value(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1).cloned())
}

fn has_flag(args: &[String], name: &str) -> bool {
    args.iter().any(|a| a == name)
}

fn first_positional(args: &[String]) -> Option<&String> {
    args.iter().find(|a| !a.starts_with('-'))
}

fn positional_all(args: &[String]) -> Vec<&String> {
    args.iter().filter(|a| !a.starts_with('-')).collect()
}

fn print_errors(file: &SourceFile, errors: &[SkError], json: bool) {
    if json {
        let out: Vec<&SkError> = errors.iter().collect();
        println!(
            "{}",
            serde_json::to_string_pretty(&out).expect("serialize diagnostics")
        );
    } else {
        eprint!("{}", error::render_all(file, errors));
    }
}

fn parse_frontend(path: &str) -> (skel::ast::File, SourceFile, String, Vec<SkError>) {
    let text = read_file(path);
    let (ast, errors) = parse_source(path, &text);
    let file = SourceFile::new(path.to_string(), text.clone());
    (ast, file, text, errors)
}

fn has_frontend_error(errors: &[SkError]) -> bool {
    errors
        .iter()
        .any(|e| e.is_error() && e.origin == Origin::Skel && e.severity == Severity::Error)
}

fn cmd_parse(args: &[String]) -> i32 {
    let Some(path) = first_positional(args) else {
        usage();
    };
    let (ast, file, _text, errors) = parse_frontend(path);
    if has_flag(args, "--json") {
        println!(
            "{}",
            serde_json::to_string_pretty(&ast).expect("serialize AST")
        );
    } else {
        println!("{ast:#?}");
    }
    print_errors(&file, &errors, false);
    if has_frontend_error(&errors) {
        EXIT_DIAG
    } else {
        EXIT_OK
    }
}

fn cmd_fmt(args: &[String]) -> i32 {
    let Some(path) = first_positional(args) else {
        usage();
    };
    let (ast, file, text, errors) = parse_frontend(path);
    if has_frontend_error(&errors) {
        print_errors(&file, &errors, false);
        return EXIT_DIAG;
    }
    let formatted = skelfmt::fmt_file(&ast);
    if has_flag(args, "--check") {
        if formatted == text {
            EXIT_OK
        } else {
            eprintln!("skelnet: `{path}` is not canonically formatted");
            EXIT_DIAG
        }
    } else {
        print!("{formatted}");
        EXIT_OK
    }
}

fn cmd_lower(args: &[String]) -> i32 {
    let Some(path) = first_positional(args) else {
        usage();
    };
    let out = flag_value(args, "-o").or_else(|| flag_value(args, "--out"));
    let Some(out) = out else {
        eprintln!("skelnet lower: missing `-o <file>`");
        usage();
    };
    let (ast, file, text, mut errors) = parse_frontend(path);
    if !has_frontend_error(&errors) {
        errors.extend(check::check(&ast, None));
    }
    if has_frontend_error(&errors) {
        print_errors(&file, &errors, false);
        return EXIT_DIAG;
    }
    match lower::lower(&ast, path, &text) {
        Ok(lowered) => {
            let cir = serde_json::to_string_pretty(&lowered.program).expect("serialize program");
            if let Err(e) = fs::write(&out, cir + "\n") {
                eprintln!("skelnet: cannot write '{out}': {e}");
                return EXIT_USAGE;
            }
            if let Some(map_path) = flag_value(args, "--map") {
                let map = serde_json::to_string_pretty(&lowered.map).expect("serialize map");
                if let Err(e) = fs::write(&map_path, map + "\n") {
                    eprintln!("skelnet: cannot write '{map_path}': {e}");
                    return EXIT_USAGE;
                }
            }
            EXIT_OK
        }
        Err(errs) => {
            print_errors(&file, &errs, false);
            EXIT_DIAG
        }
    }
}

fn cmd_check(args: &[String]) -> i32 {
    let Some(path) = first_positional(args) else {
        usage();
    };
    let json = has_flag(args, "--json");
    let (ast, file, text, mut errors) = parse_frontend(path);
    let reqs = load_reqs(args);
    if !has_frontend_error(&errors) {
        errors.extend(check::check(&ast, reqs.as_ref()));
    }
    if has_frontend_error(&errors) {
        if json {
            let out = serde_json::json!({
                "valid": false, "unmapped": 0, "diagnostics": errors,
                "support_error": serde_json::Value::Null,
            });
            println!("{}", serde_json::to_string_pretty(&out).expect("serialize"));
        } else {
            print_errors(&file, &errors, false);
        }
        return EXIT_DIAG;
    }
    let lowered = match lower::lower(&ast, path, &text) {
        Ok(l) => l,
        Err(errs) => {
            if json {
                let out = serde_json::json!({
                    "valid": false, "unmapped": 0, "diagnostics": errs,
                    "support_error": serde_json::Value::Null,
                });
                println!("{}", serde_json::to_string_pretty(&out).expect("serialize"));
            } else {
                print_errors(&file, &errs, false);
            }
            return EXIT_DIAG;
        }
    };
    let mapper = Mapper::new(&lowered.program, &lowered.map);
    let validation = concir::validate::validate(&lowered.program);
    let (mapped, unmapped) = mapper.map_validation(&validation);
    let support = concir::sem::program::lower(&lowered.program);
    let support_err = support.as_ref().err().map(|e| format!("{e:?}"));
    if json {
        let out = serde_json::json!({
            "valid": validation.valid && support.is_ok(),
            "unmapped": unmapped,
            "diagnostics": mapped,
            "support_error": support_err,
        });
        println!("{}", serde_json::to_string_pretty(&out).expect("serialize"));
    } else {
        for d in &mapped {
            let at = d
                .skel
                .as_ref()
                .map(|s| format!("{}:{}", path, s.line))
                .unwrap_or_else(|| "<unmapped>".to_string());
            eprintln!("{}[{}]: {} ({at})", d.severity, d.code, d.message);
        }
        if let Some(e) = &support_err {
            eprintln!("support error: {e}");
        }
    }
    if !validation.valid || support.is_err() {
        EXIT_DIAG
    } else {
        EXIT_OK
    }
}

fn cmd_verify(args: &[String]) -> i32 {
    let positional = positional_all(args);
    let (Some(path), Some(contract_path)) = (positional.first(), positional.get(1)) else {
        usage();
    };
    let json = has_flag(args, "--json");
    let engine = match flag_value(args, "--engine").as_deref() {
        Some("interp") => EngineKind::Interpreter,
        _ => EngineKind::Petri,
    };
    let (ast, file, text, mut errors) = parse_frontend(path);
    if !has_frontend_error(&errors) {
        errors.extend(check::check(&ast, None));
    }
    if has_frontend_error(&errors) {
        print_errors(&file, &errors, json);
        return EXIT_DIAG;
    }
    let lowered = match lower::lower(&ast, path, &text) {
        Ok(l) => l,
        Err(errs) => {
            print_errors(&file, &errs, json);
            return EXIT_DIAG;
        }
    };
    let contract_text = read_file(contract_path);
    let contract_value: serde_json::Value = match serde_json::from_str(&contract_text) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("skelnet: cannot parse contract: {e}");
            return EXIT_USAGE;
        }
    };
    let spec: ContractSpec = match serde_json::from_str(&contract_text) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("skelnet: cannot parse contract: {e}");
            return EXIT_USAGE;
        }
    };
    let report = verify_program(&lowered.program, &spec, engine);
    let mapper = Mapper::new(&lowered.program, &lowered.map);
    let reqs = feedback::contract_property_reqs(&contract_value);
    let fb = mapper.map_verify(&report, &reqs, &file);
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&fb).expect("serialize feedback")
        );
    } else {
        println!("{}", fb.outcome);
        for p in &fb.properties {
            println!("  {}: {} - {}", p.id, p.outcome, p.detail);
        }
        for ce in &fb.counterexamples {
            eprintln!("{}", feedback::render_counterexample(ce));
        }
        for d in &fb.diagnostics {
            let at = d
                .skel
                .as_ref()
                .map(|s| format!("{}:{}", path, s.line))
                .unwrap_or_else(|| "<unmapped>".to_string());
            eprintln!("{}[{}]: {} ({at})", d.severity, d.code, d.message);
        }
    }
    match report.outcome.as_str() {
        "PASS" => EXIT_OK,
        _ => EXIT_DIAG,
    }
}

fn load_reqs(args: &[String]) -> Option<Requirements> {
    flag_value(args, "--reqs").map(|p| {
        let doc = read_file(&p);
        match serde_json::from_str::<serde_json::Value>(&doc) {
            Ok(v) => Requirements::from_json(&v),
            Err(e) => {
                eprintln!("skelnet: cannot parse '{p}': {e}");
                process::exit(EXIT_USAGE);
            }
        }
    })
}
