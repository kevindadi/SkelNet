//! `skelnet` — the Skeleton DSL command-line tool.

use std::fs;
use std::process;

use skel::check::{self, Requirements};
use skel::error::{self, Origin, Severity, SkError};
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
        "check" => cmd_check(&args[2..]),
        "--help" | "-h" | "help" => {
            usage();
        }
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
         skelnet parse <f.skel> [--json]\n  \
         skelnet fmt   <f.skel> [--check]\n  \
         skelnet check <f.skel> [--reqs requirements.json] [--json]"
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

fn cmd_parse(args: &[String]) -> i32 {
    let Some(path) = args.first().filter(|a| !a.starts_with('-')) else {
        usage();
    };
    let text = read_file(path);
    let (ast, errors) = parse_source(path, &text);
    if has_flag(args, "--json") {
        println!(
            "{}",
            serde_json::to_string_pretty(&ast).expect("serialize AST")
        );
    } else {
        println!("{ast:#?}");
    }
    let file = SourceFile::new(path.clone(), text);
    print_errors(&file, &errors, false);
    if errors.iter().any(|e| e.is_error()) {
        EXIT_DIAG
    } else {
        EXIT_OK
    }
}

fn cmd_fmt(args: &[String]) -> i32 {
    let Some(path) = args.first().filter(|a| !a.starts_with('-')) else {
        usage();
    };
    let text = read_file(path);
    let (ast, errors) = parse_source(path, &text);
    let file = SourceFile::new(path.clone(), text.clone());
    if errors.iter().any(|e| e.is_error()) {
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

fn cmd_check(args: &[String]) -> i32 {
    let Some(path) = args.first().filter(|a| !a.starts_with('-')) else {
        usage();
    };
    let text = read_file(path);
    let (ast, mut errors) = parse_source(path, &text);
    let reqs = flag_value(args, "--reqs").map(|p| {
        let doc = read_file(&p);
        match serde_json::from_str::<serde_json::Value>(&doc) {
            Ok(v) => Requirements::from_json(&v),
            Err(e) => {
                eprintln!("skelnet: cannot parse '{p}': {e}");
                process::exit(EXIT_USAGE);
            }
        }
    });
    if !errors.iter().any(|e| e.is_error()) {
        errors.extend(check::check(&ast, reqs.as_ref()));
    }
    let file = SourceFile::new(path.clone(), text);
    let json = has_flag(args, "--json");
    print_errors(&file, &errors, json);
    let has_error = errors
        .iter()
        .any(|e| e.is_error() && e.origin == Origin::Skel && e.severity == Severity::Error);
    if has_error {
        EXIT_DIAG
    } else {
        EXIT_OK
    }
}
