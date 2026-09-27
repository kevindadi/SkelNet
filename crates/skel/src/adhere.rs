//! Skeleton adherence report (`skelnet adhere`) — a human-review tool only.
//!
//! Extracts the synchronous operation sequence from Rust with `syn`, aligns it
//! per function with the skeleton's expected sequence, and classifies each
//! skeleton statement. It is intentionally heuristic (the reference Rust uses
//! its own names); it is never wired into run/eval/report.

use std::collections::BTreeMap;

use proc_macro2::Span;
use serde::Serialize;
use syn::spanned::Spanned;
use syn::visit::Visit;
use syn::{Expr, ExprCall, ExprMethodCall, ItemFn, Stmt as SynStmt};

use crate::ast::*;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct AdhereOp {
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    pub line: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct StmtStatus {
    pub dsl_line: u32,
    pub dsl_kind: String,
    pub dsl_name: Option<String>,
    pub status: String, // matched | missing | reordered | nesting_mismatch
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rust_line: Option<u32>,
}

#[derive(Debug, Clone, Serialize)]
pub struct FnAdherence {
    pub function: String,
    pub matched_rust_fn: Option<String>,
    pub dsl_lock_depth: usize,
    pub rust_lock_count: usize,
    pub statements: Vec<StmtStatus>,
    pub dsl_ops: Vec<AdhereOp>,
    pub rust_ops: Vec<AdhereOp>,
}

#[derive(Debug, Clone, Serialize)]
pub struct AdhereReport {
    pub skel: String,
    pub rust: String,
    pub functions: Vec<FnAdherence>,
    pub extra_rust_ops: Vec<AdhereOp>,
}

pub fn adhere(skel_file: &str, skel: &File, rust_text: &str) -> AdhereReport {
    let rust_fns = collect_rust_fns(rust_text);
    let mut functions = Vec::new();
    let mut consumed: BTreeMap<String, usize> = BTreeMap::new();
    for m in &skel.modules {
        for item in &m.items {
            let ItemKind::Fn(f) = &item.kind else { continue };
            let (dsl_ops, dsl_depth) = dsl_ops(&f.body);
            if dsl_ops.is_empty() {
                continue;
            }
            // Align by name, else by order of sync-bearing Rust functions.
            let rust_name = if rust_fns.contains_key(&f.name) {
                Some(f.name.clone())
            } else {
                None
            };
            let rust_ops = match &rust_name {
                Some(n) => rust_fns.get(n).cloned().unwrap_or_default(),
                None => Vec::new(),
            };
            let (statements, rust_used) =
                classify(&dsl_ops, &rust_ops, dsl_depth, &rust_fns, &mut consumed);
            functions.push(FnAdherence {
                function: format!("{}::{}", m.name, f.name),
                matched_rust_fn: rust_name,
                dsl_lock_depth: dsl_depth,
                rust_lock_count: rust_ops.iter().filter(|o| o.kind == "lock").count(),
                statements,
                dsl_ops,
                rust_ops: rust_used,
            });
        }
    }
    let _ = skel_file;
    AdhereReport {
        skel: skel_file.to_string(),
        rust: "<rust>".to_string(),
        functions,
        extra_rust_ops: Vec::new(),
    }
}

fn classify(
    dsl: &[AdhereOp],
    rust: &[AdhereOp],
    dsl_depth: usize,
    rust_fns: &BTreeMap<String, Vec<AdhereOp>>,
    consumed: &mut BTreeMap<String, usize>,
) -> (Vec<StmtStatus>, Vec<AdhereOp>) {
    // If no named Rust function matched, fall back to the next unconsumed Rust
    // function (in file order) that carries sync operations.
    let rust = if rust.is_empty() {
        let mut chosen: Option<(String, Vec<AdhereOp>)> = None;
        for (name, ops) in rust_fns {
            if consumed.get(name).copied().unwrap_or(0) == 0 && !ops.is_empty() {
                chosen = Some((name.clone(), ops.clone()));
                break;
            }
        }
        match chosen {
            Some((name, ops)) => {
                *consumed.entry(name).or_insert(0) += 1;
                ops
            }
            None => Vec::new(),
        }
    } else {
        rust.to_vec()
    };

    let mut statuses = Vec::new();
    let mut cursor = 0usize;
    let rust_lock_count = rust.iter().filter(|o| o.kind == "lock").count();
    let nesting_mismatch = dsl_depth >= 2 && rust_lock_count < dsl_depth;
    for (i, d) in dsl.iter().enumerate() {
        // Greedy in-order match on kind.
        let mut found = None;
        for j in cursor..rust.len() {
            if rust[j].kind == d.kind {
                found = Some(j);
                break;
            }
        }
        let status = match found {
            Some(j) => {
                let reordered = j != cursor;
                cursor = j + 1;
                if reordered {
                    "reordered"
                } else if i == 0 && nesting_mismatch {
                    "nesting_mismatch"
                } else {
                    "matched"
                }
            }
            None => {
                if nesting_mismatch {
                    "nesting_mismatch"
                } else {
                    "missing"
                }
            }
        };
        statuses.push(StmtStatus {
            dsl_line: d.line,
            dsl_kind: d.kind.clone(),
            dsl_name: d.name.clone(),
            status: status.to_string(),
            rust_line: found.map(|j| rust[j].line),
        });
    }
    (statuses, rust)
}

fn dsl_ops(block: &Block) -> (Vec<AdhereOp>, usize) {
    let mut ops = Vec::new();
    let mut depth = 0usize;
    let mut max_depth = 0usize;
    walk_dsl(block, &mut depth, &mut max_depth, &mut ops);
    (ops, max_depth)
}

fn walk_dsl(block: &Block, depth: &mut usize, max: &mut usize, ops: &mut Vec<AdhereOp>) {
    for s in &block.stmts {
        match &s.core {
            StmtCore::Lock { name, body } => {
                ops.push(AdhereOp {
                    kind: "lock".into(),
                    name: Some(name.text()),
                    line: s.span.line,
                });
                *depth += 1;
                *max = (*max).max(*depth);
                walk_dsl(body, depth, max, ops);
                *depth -= 1;
            }
            StmtCore::Permit { name, body } => {
                ops.push(AdhereOp {
                    kind: "permit".into(),
                    name: Some(name.text()),
                    line: s.span.line,
                });
                walk_dsl(body, depth, max, ops);
            }
            StmtCore::Scope { spawns } => {
                for sp in spawns {
                    ops.push(AdhereOp {
                        kind: "spawn".into(),
                        name: Some(sp.name.text()),
                        line: sp.span.line,
                    });
                }
            }
            StmtCore::If { then, els, .. } => {
                walk_dsl(then, depth, max, ops);
                if let Some(Else::Block(b)) = els {
                    walk_dsl(b, depth, max, ops);
                }
                if let Some(Else::If(s)) = els {
                    let b = Block { stmts: vec![(**s).clone()], span: s.span, close_span: s.span };
                    walk_dsl(&b, depth, max, ops);
                }
            }
            StmtCore::While { body, .. } | StmtCore::Loop { body } => {
                walk_dsl(body, depth, max, ops);
            }
            StmtCore::Method { recv, call } => {
                let kind = match call {
                    MethodCall::Send(_) => "send",
                    MethodCall::Recv => "recv",
                    MethodCall::Store(_) => "atomic_store",
                    MethodCall::NotifyOne => "notify_one",
                    MethodCall::NotifyAll => "notify_all",
                    MethodCall::Wait => "wait",
                    MethodCall::Post => "post",
                    MethodCall::Take => "take",
                    MethodCall::Join => "join",
                };
                ops.push(AdhereOp {
                    kind: kind.into(),
                    name: Some(recv.text()),
                    line: s.span.line,
                });
            }
            StmtCore::Let { rhs, .. } => {
                let op = match rhs {
                    Rhs::Recv { recv } => Some(("recv", recv.text())),
                    Rhs::Load { recv } => Some(("atomic_load", recv.text())),
                    Rhs::Cas { recv, .. } => Some(("cas", recv.text())),
                    Rhs::Spawn { call } => Some(("spawn", call.name.text())),
                    _ => None,
                };
                if let Some((kind, name)) = op {
                    ops.push(AdhereOp { kind: kind.into(), name: Some(name), line: s.span.line });
                }
            }
            _ => {}
        }
    }
}

// ── Rust extraction ──────────────────────────────────────────────────

fn collect_rust_fns(text: &str) -> BTreeMap<String, Vec<AdhereOp>> {
    let mut out = BTreeMap::new();
    let Ok(file) = syn::parse_file(text) else {
        return out;
    };
    for item in &file.items {
        if let syn::Item::Fn(f) = item {
            let mut c = RustCollector { ops: Vec::new() };
            c.visit_item_fn(f);
            out.insert(f.sig.ident.to_string(), c.ops);
        }
    }
    out
}

struct RustCollector {
    ops: Vec<AdhereOp>,
}

fn line_of(span: Span) -> u32 {
    span.start().line as u32
}

fn receiver_text(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(p) => Some(
            p.path
                .segments
                .iter()
                .map(|s| s.ident.to_string())
                .collect::<Vec<_>>()
                .join("::"),
        ),
        Expr::Field(f) => receiver_text(&f.base),
        Expr::MethodCall(m) => receiver_text(&m.receiver),
        _ => None,
    }
}

impl<'ast> Visit<'ast> for RustCollector {
    fn visit_expr_method_call(&mut self, node: &'ast ExprMethodCall) {
        let method = node.method.to_string();
        let kind = match method.as_str() {
            "lock" => Some("lock"),
            "wait" | "wait_while" => Some("wait"),
            "notify_one" => Some("notify_one"),
            "notify_all" => Some("notify_all"),
            "send" | "try_send" => Some("send"),
            "recv" | "try_recv" => Some("recv"),
            "load" => Some("atomic_load"),
            "store" => Some("atomic_store"),
            "compare_exchange" | "compare_exchange_weak" | "cas" => Some("cas"),
            "join" => Some("join"),
            "acquire" | "try_acquire" => Some("permit"),
            "post" => Some("post"),
            "take" => Some("take"),
            _ => None,
        };
        if let Some(kind) = kind {
            self.ops.push(AdhereOp {
                kind: kind.into(),
                name: receiver_text(&node.receiver),
                line: line_of(node.span()),
            });
        }
        syn::visit::visit_expr_method_call(self, node);
    }

    fn visit_expr_call(&mut self, node: &'ast ExprCall) {
        if let Expr::Path(p) = &*node.func {
            let segs: Vec<String> = p.path.segments.iter().map(|s| s.ident.to_string()).collect();
            let last = segs.last().map(String::as_str).unwrap_or("");
            if last == "spawn" || segs.iter().any(|s| s == "spawn") {
                self.ops.push(AdhereOp {
                    kind: "spawn".into(),
                    name: None,
                    line: line_of(node.span()),
                });
            } else if last == "scope" {
                self.ops.push(AdhereOp {
                    kind: "scope".into(),
                    name: None,
                    line: line_of(node.span()),
                });
            }
        }
        syn::visit::visit_expr_call(self, node);
    }

    fn visit_item_fn(&mut self, node: &'ast ItemFn) {
        syn::visit::visit_item_fn(self, node);
    }

    fn visit_stmt(&mut self, node: &'ast SynStmt) {
        syn::visit::visit_stmt(self, node);
    }
}

pub fn render_markdown(report: &AdhereReport) -> String {
    let mut out = String::from("# Skeleton adherence report (human review only)\n\n");
    out.push_str(&format!("skeleton: `{}`\n\n", report.skel));
    for f in &report.functions {
        out.push_str(&format!(
            "## {}\n\nmatched Rust fn: `{}`; DSL lock depth {}; Rust lock calls {}\n\n",
            f.function,
            f.matched_rust_fn.clone().unwrap_or_else(|| "<none>".into()),
            f.dsl_lock_depth,
            f.rust_lock_count
        ));
        out.push_str("| dsl line | statement | status | rust line |\n");
        out.push_str("| --- | --- | --- | --- |\n");
        for s in &f.statements {
            out.push_str(&format!(
                "| {} | {} {} | {} | {} |\n",
                s.dsl_line,
                s.dsl_kind,
                s.dsl_name.clone().unwrap_or_default(),
                s.status,
                s.rust_line.map(|l| l.to_string()).unwrap_or_else(|| "-".into())
            ));
        }
        out.push('\n');
    }
    out
}
