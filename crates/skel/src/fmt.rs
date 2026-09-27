//! Canonical pretty-printer. Guarantees `parse(fmt(parse(x))) == parse(x)`
//! (AST compared ignoring spans).

use crate::ast::*;

pub fn fmt_file(file: &File) -> String {
    let mut p = Printer {
        out: String::new(),
        indent: 0,
    };
    p.out.push_str(&format!("skeleton {};\n", file.name));
    let single_main = file.implicit_main && file.modules.len() == 1;
    if single_main {
        for item in &file.modules[0].items {
            p.out.push('\n');
            p.item(item);
        }
    } else {
        for m in &file.modules {
            p.out.push('\n');
            p.module(m);
        }
    }
    p.out
}

struct Printer {
    out: String,
    indent: usize,
}

impl Printer {
    fn line(&mut self, s: &str) {
        self.pad();
        self.out.push_str(s);
        self.out.push('\n');
    }

    fn pad(&mut self) {
        for _ in 0..self.indent {
            self.out.push_str("    ");
        }
    }

    fn tags(&mut self, tags: &[Tag]) {
        for t in tags {
            self.out.push_str(&format!("@{} ", t.raw));
        }
    }

    fn module(&mut self, m: &Module) {
        self.line(&format!("module {} {{", m.name));
        self.indent += 1;
        for item in &m.items {
            self.item(item);
        }
        self.indent -= 1;
        self.line("}");
    }

    fn item(&mut self, item: &Item) {
        self.tags(&item.tags);
        match &item.kind {
            ItemKind::Resource(r) => {
                let text = resource_text(r);
                self.line(&text);
            }
            ItemKind::Fn(f) => {
                let params = f
                    .params
                    .iter()
                    .map(|p| format!("{}: {}", p.name, p.ty.display()))
                    .collect::<Vec<_>>()
                    .join(", ");
                let ret = f
                    .ret
                    .as_ref()
                    .map(|t| format!(" -> {}", t.display()))
                    .unwrap_or_default();
                self.out.push_str(&format!("fn {}({}){} {{", f.name, params, ret));
                self.out.push('\n');
                self.indent += 1;
                for s in &f.body.stmts {
                    self.stmt(s);
                }
                self.indent -= 1;
                self.line("}");
            }
            ItemKind::ExternFn(e) => {
                self.line(&format!("extern fn {}();", e.name));
            }
        }
    }

    fn stmt(&mut self, stmt: &Stmt) {
        match &stmt.core {
            StmtCore::Lock { name, body } => {
                self.tags(&stmt.tags);
                self.pad();
                self.out.push_str(&format!("lock {} {{\n", name.text()));
                self.indent += 1;
                for s in &body.stmts {
                    self.stmt(s);
                }
                self.indent -= 1;
                self.line("}");
            }
            StmtCore::Permit { name, body } => {
                self.tags(&stmt.tags);
                self.pad();
                self.out.push_str(&format!("permit {} {{\n", name.text()));
                self.indent += 1;
                for s in &body.stmts {
                    self.stmt(s);
                }
                self.indent -= 1;
                self.line("}");
            }
            StmtCore::Scope { spawns } => {
                self.tags(&stmt.tags);
                if spawns.is_empty() {
                    self.line("scope { }");
                } else {
                    self.line("scope {");
                    self.indent += 1;
                    for sp in spawns {
                        self.line(&format!("spawn {}();", sp.name.text()));
                    }
                    self.indent -= 1;
                    self.line("}");
                }
            }
            StmtCore::If { cond, then, els } => {
                self.tags(&stmt.tags);
                self.pad();
                self.out
                    .push_str(&format!("if {} {{\n", fmt_expr(cond)));
                self.indent += 1;
                for s in &then.stmts {
                    self.stmt(s);
                }
                self.indent -= 1;
                match els {
                    None => self.line("}"),
                    Some(Else::Block(b)) => {
                        self.pad();
                        self.out.push_str("} else {\n");
                        self.indent += 1;
                        for s in &b.stmts {
                            self.stmt(s);
                        }
                        self.indent -= 1;
                        self.line("}");
                    }
                    Some(Else::If(inner)) => {
                        // `else if` continues on the same line.
                        self.pad();
                        self.out.push_str("} else ");
                        self.else_if(inner);
                    }
                }
            }
            StmtCore::While { cond, body } => {
                self.tags(&stmt.tags);
                self.pad();
                self.out
                    .push_str(&format!("while {} {{\n", fmt_expr(cond)));
                self.indent += 1;
                for s in &body.stmts {
                    self.stmt(s);
                }
                self.indent -= 1;
                self.line("}");
            }
            StmtCore::Loop { body } => {
                self.tags(&stmt.tags);
                self.pad();
                self.line("loop {");
                self.indent += 1;
                for s in &body.stmts {
                    self.stmt(s);
                }
                self.indent -= 1;
                self.line("}");
            }
            StmtCore::Break => {
                self.tags(&stmt.tags);
                self.line("break;");
            }
            StmtCore::Continue => {
                self.tags(&stmt.tags);
                self.line("continue;");
            }
            StmtCore::Return(v) => {
                self.tags(&stmt.tags);
                match v {
                    Some(e) => self.line(&format!("return {};", fmt_expr(e))),
                    None => self.line("return;"),
                }
            }
            StmtCore::Compute {
                desc,
                reads,
                writes,
                ..
            } => {
                self.tags(&stmt.tags);
                let mut s = format!("compute {}", quote(desc));
                if !reads.is_empty() {
                    s.push_str(&format!(
                        " reads({})",
                        reads.iter().map(|n| n.text()).collect::<Vec<_>>().join(", ")
                    ));
                }
                if !writes.is_empty() {
                    s.push_str(&format!(
                        " writes({})",
                        writes.iter().map(|n| n.text()).collect::<Vec<_>>().join(", ")
                    ));
                }
                s.push(';');
                self.line(&s);
            }
            StmtCore::Let {
                name, ty, rhs, ..
            } => {
                self.tags(&stmt.tags);
                let ty = ty
                    .as_ref()
                    .map(|t| format!(": {}", t.display()))
                    .unwrap_or_default();
                self.line(&format!("let {}{} = {};", name, ty, fmt_rhs(rhs)));
            }
            StmtCore::Assign { name, expr } => {
                self.tags(&stmt.tags);
                self.line(&format!("{} = {};", name.text(), fmt_expr(expr)));
            }
            StmtCore::Method { recv, call } => {
                self.tags(&stmt.tags);
                self.line(&format!("{}.{};", recv.text(), fmt_method(call)));
            }
            StmtCore::Call { call } => {
                self.tags(&stmt.tags);
                self.line(&format!("{};", fmt_call(call)));
            }
        }
    }

    /// Print `if ...` for an `else if` chain continuation (leading `if`).
    fn else_if(&mut self, stmt: &Stmt) {
        if let StmtCore::If { cond, then, els } = &stmt.core {
            self.tags(&stmt.tags);
            self.out.push_str(&format!("if {} {{\n", fmt_expr(cond)));
            self.indent += 1;
            for s in &then.stmts {
                self.stmt(s);
            }
            self.indent -= 1;
            match els {
                None => self.line("}"),
                Some(Else::Block(b)) => {
                    self.pad();
                    self.out.push_str("} else {\n");
                    self.indent += 1;
                    for s in &b.stmts {
                        self.stmt(s);
                    }
                    self.indent -= 1;
                    self.line("}");
                }
                Some(Else::If(inner)) => {
                    self.pad();
                    self.out.push_str("} else ");
                    self.else_if(inner);
                }
            }
        } else {
            // The grammar only produces `if` on the `else` branch.
            self.stmt(stmt);
        }
    }
}

fn resource_text(r: &ResourceDecl) -> String {
    match &r.kind {
        ResourceKind::Mutex => format!("mutex {};", r.name),
        ResourceKind::Condvar { bound } => format!("condvar {} for {};", r.name, bound.text()),
        ResourceKind::Semaphore { count } => format!("semaphore {} = {};", r.name, count),
        ResourceKind::Channel { ty, cap } => {
            format!("channel {}: {} cap {};", r.name, ty.display(), cap)
        }
        ResourceKind::Shared {
            ty,
            init,
            guarded_by,
        } => {
            let g = guarded_by
                .as_ref()
                .map(|n| format!(" guarded_by {}", n.text()))
                .unwrap_or_default();
            format!("shared {}: {} = {}{};", r.name, ty.display(), init.display(), g)
        }
        ResourceKind::Atomic { ty, init } => {
            format!("atomic {}: {} = {};", r.name, ty.display(), init.display())
        }
    }
}

fn fmt_method(m: &MethodCall) -> String {
    match m {
        MethodCall::Send(e) => format!("send({})", fmt_expr(e)),
        MethodCall::Recv => "recv()".to_string(),
        MethodCall::Store(e) => format!("store({})", fmt_expr(e)),
        MethodCall::NotifyOne => "notify_one()".to_string(),
        MethodCall::NotifyAll => "notify_all()".to_string(),
        MethodCall::Wait => "wait()".to_string(),
        MethodCall::Post => "post()".to_string(),
        MethodCall::Take => "take()".to_string(),
        MethodCall::Join => "join()".to_string(),
    }
}

fn fmt_rhs(rhs: &Rhs) -> String {
    match rhs {
        Rhs::Expr(e) => fmt_expr(e),
        Rhs::Recv { recv } => format!("{}.recv()", recv.text()),
        Rhs::Load { recv } => format!("{}.load()", recv.text()),
        Rhs::Cas {
            recv,
            expected,
            desired,
        } => format!(
            "{}.cas({}, {})",
            recv.text(),
            fmt_expr(expected),
            fmt_expr(desired)
        ),
        Rhs::Spawn { call } => format!("spawn {}", fmt_call(call)),
        Rhs::Call { call } => fmt_call(call),
    }
}

fn fmt_call(c: &Call) -> String {
    let args = c
        .args
        .iter()
        .map(fmt_expr)
        .collect::<Vec<_>>()
        .join(", ");
    format!("{}({})", c.name.text(), args)
}

/// Expression precedence: higher binds tighter.
fn prec(e: &Expr) -> u8 {
    match e {
        Expr::Cmp { .. } => 1,
        Expr::BinOp { op, .. } => match op {
            BinOp::Add | BinOp::Sub => 2,
            BinOp::Mul | BinOp::Div | BinOp::Mod => 3,
        },
        Expr::Neg(..) => 4,
        _ => 5,
    }
}

fn fmt_expr(e: &Expr) -> String {
    fmt_expr_prec(e, 0)
}

fn fmt_expr_prec(e: &Expr, min: u8) -> String {
    let s = match e {
        Expr::IntLit(n, _) => n.to_string(),
        Expr::BoolLit(b, _) => b.to_string(),
        Expr::Name(n) => n.text(),
        Expr::Neg(inner, _) => format!("-{}", fmt_expr_prec(inner, 4)),
        Expr::Paren(inner, _) => format!("({})", fmt_expr(inner)),
        Expr::BinOp { op, lhs, rhs, .. } => {
            let p = prec(e);
            format!(
                "{} {} {}",
                fmt_expr_prec(lhs, p),
                op.symbol(),
                fmt_expr_prec(rhs, p + 1)
            )
        }
        Expr::Cmp { op, lhs, rhs, .. } => format!(
            "{} {} {}",
            fmt_expr_prec(lhs, 2),
            op.symbol(),
            fmt_expr_prec(rhs, 2)
        ),
    };
    if prec(e) < min {
        format!("({s})")
    } else {
        s
    }
}

fn quote(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            _ => out.push(c),
        }
    }
    out.push('"');
    out
}
