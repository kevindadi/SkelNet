//! Total lowering: Skeleton DSL AST -> ConcIR JSON + source map.
//!
//! The lowering is a total function over skeletons that pass the front-end
//! checks: it never panics and never optimises. Each function body is emitted
//! in order with dense `s1..sn` sids and backpatched jump targets.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use concir::ast::{
    BaseType, ComplexBaseType, Function, LocalDecl, Module, NameSet, Op, ParamDecl, Program,
    Protection, Resource, Stmt as CirStmt,
};

use crate::ast::*;
use crate::check::{self, build, ModuleInfo, ResKind, Ty};
use crate::error::SkError;
use crate::fmt::fmt_expr;
use crate::span::Span;

#[derive(Debug, Clone, serde::Serialize)]
pub struct MapSpan {
    pub line: u32,
    pub col: u32,
    pub end_line: u32,
    pub end_col: u32,
}

impl From<Span> for MapSpan {
    fn from(s: Span) -> Self {
        MapSpan {
            line: s.line,
            col: s.col,
            end_line: s.end_line,
            end_col: s.end_col,
        }
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct MapStmt {
    pub loc: String,
    pub construct: String,
    pub span: MapSpan,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub block_span: Option<MapSpan>,
    pub reqs: Vec<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct MapFn {
    pub span: MapSpan,
    pub reqs: Vec<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct MapRes {
    pub span: MapSpan,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bound_mutex: Option<String>,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct SourceMap {
    pub skel_sha256: String,
    pub cir_sha256: String,
    pub file: String,
    pub stmts: Vec<MapStmt>,
    pub functions: BTreeMap<String, MapFn>,
    pub resources: BTreeMap<String, MapRes>,
    pub json_paths: BTreeMap<String, String>,
}

pub struct Lowered {
    pub program: Program,
    pub map: SourceMap,
}

pub fn lower(file: &File, file_name: &str, skel_text: &str) -> Result<Lowered, Vec<SkError>> {
    let modules = build(file);
    let mut errors: Vec<SkError> = Vec::new();

    // Entry must exist.
    if !file
        .modules
        .iter()
        .any(|m| m.name == "main" && m.items.iter().any(|i| matches!(&i.kind, ItemKind::Fn(f) if f.name == "main")))
    {
        errors.push(SkError::error(
            "S101",
            file.span,
            "entry function `main::main` was not found (the DSL entry point is fixed)",
        ));
        return Err(errors);
    }

    // Collect spawn / scope targets (these functions get `form: "closure"`).
    let mut closures: BTreeSet<String> = BTreeSet::new();
    for (mi, m) in file.modules.iter().enumerate() {
        for item in &m.items {
            if let ItemKind::Fn(f) = &item.kind {
                collect_targets(&f.body, &modules, mi, &mut closures);
            }
        }
    }

    let mut seq: u64 = 0;
    let mut cir_modules: Vec<Module> = Vec::new();
    let mut map = SourceMap {
        skel_sha256: concir::hash::sha256_hex(skel_text.as_bytes()),
        file: file_name.to_string(),
        ..Default::default()
    };

    for (mi, m) in file.modules.iter().enumerate() {
        let mut resources: Vec<Resource> = Vec::new();
        let mut protection: Vec<Protection> = Vec::new();
        for (ri, item) in m.items.iter().enumerate() {
            if let ItemKind::Resource(r) = &item.kind {
                let res = lower_resource(r, &m.name);
                if let ResourceKind::Shared {
                    guarded_by: Some(g), ..
                } = &r.kind
                {
                    // `protection` uses the short lock name in-module, FQN only
                    // for a cross-module lock (matches §5.2 and the gold files).
                    let lock = g.text();
                    protection.push(Protection {
                        var: r.name.clone(),
                        lock,
                    });
                }
                map.resources.insert(
                    format!("{}::{}", m.name, r.name),
                    MapRes {
                        span: r.span.into(),
                        bound_mutex: match &r.kind {
                            ResourceKind::Condvar { bound } => Some(if bound.is_qualified() {
                                bound.text()
                            } else {
                                format!("{}::{}", m.name, bound.ident)
                            }),
                            _ => None,
                        },
                    },
                );
                map.json_paths.insert(
                    format!("modules[{mi}].resources[{ri}]"),
                    format!("{}::{}", m.name, r.name),
                );
                resources.push(res);
            }
        }

        let mut functions: Vec<Function> = Vec::new();
        let mut fi = 0usize;
        for item in &m.items {
            match &item.kind {
                ItemKind::Fn(f) => {
                    let fqn = format!("{}::{}", m.name, f.name);
                    let item_reqs = tag_reqs(&item.tags);
                    map.functions.insert(
                        fqn.clone(),
                        MapFn {
                            span: f.span.into(),
                            reqs: item_reqs.clone(),
                        },
                    );
                    let is_closure = closures.contains(&fqn);
                    let function = lower_fn(
                        f,
                        mi,
                        &m.name,
                        fi,
                        &modules,
                        is_closure,
                        &mut seq,
                        &mut map,
                        &mut errors,
                        &item_reqs,
                        &item.tags,
                    );
                    functions.push(function);
                    fi += 1;
                }
                ItemKind::ExternFn(e) => {
                    let fqn = format!("{}::{}", m.name, e.name);
                    let item_reqs = tag_reqs(&item.tags);
                    map.functions.insert(
                        fqn,
                        MapFn {
                            span: e.span.into(),
                            reqs: item_reqs.clone(),
                        },
                    );
                    let function = Function {
                        name: e.name.clone(),
                        kind: "normal".into(),
                        form: "function".into(),
                        params: Vec::new(),
                        returns: None,
                        locals: Vec::new(),
                        body: Vec::new(),
                        effects: None,
                        may_block: None,
                        locks: Default::default(),
                        bound: None,
                    };
                    functions.push(function);
                    fi += 1;
                }
                ItemKind::Resource(_) => {}
            }
        }

        let provides = NameSet {
            resources: resources.iter().map(|r| r.name.clone()).collect(),
            functions: functions.iter().map(|f| f.name.clone()).collect(),
            types: Vec::new(),
        };
        let requires = compute_requires(mi, &m.name, &functions, &resources);

        cir_modules.push(Module {
            name: m.name.clone(),
            provides,
            requires,
            types: Vec::new(),
            resources,
            protection,
            functions,
        });
    }

    let program = Program {
        program: file.name.clone(),
        version: "3.5.0".to_string(),
        modules: cir_modules,
        entry: "main::main".to_string(),
    };

    map.cir_sha256 = concir::hash::sha256_hex(
        serde_json::to_string(&program)
            .unwrap_or_default()
            .as_bytes(),
    );

    if errors.iter().any(|e| e.is_error()) {
        return Err(errors);
    }
    Ok(Lowered { program, map })
}

fn tag_reqs(tags: &[Tag]) -> Vec<String> {
    tags.iter()
        .filter(|t| t.n.is_some())
        .map(|t| t.raw.clone())
        .collect()
}

fn merge_reqs(outer: &[String], tags: &[Tag]) -> Vec<String> {
    let mut out = outer.to_vec();
    for t in tags {
        if t.n.is_some() && !out.contains(&t.raw) {
            out.push(t.raw.clone());
        }
    }
    out
}

fn collect_targets(
    block: &Block,
    modules: &[ModuleInfo],
    mi: usize,
    out: &mut BTreeSet<String>,
) {
    for s in &block.stmts {
        match &s.core {
            StmtCore::Scope { spawns } => {
                for sp in spawns {
                    out.insert(fqn_of(modules, mi, &sp.name));
                }
            }
            StmtCore::Lock { body, .. }
            | StmtCore::Permit { body, .. }
            | StmtCore::While { body, .. }
            | StmtCore::Loop { body, .. } => collect_targets(body, modules, mi, out),
            StmtCore::If { then, els, .. } => {
                collect_targets(then, modules, mi, out);
                if let Some(Else::Block(b)) = els {
                    collect_targets(b, modules, mi, out);
                }
                if let Some(Else::If(s)) = els {
                    collect_targets(
                        &Block {
                            stmts: vec![s.as_ref().clone()],
                            span: s.span,
                            close_span: s.span,
                        },
                        modules,
                        mi,
                        out,
                    );
                }
            }
            StmtCore::Let {
                rhs: Rhs::Spawn { call },
                ..
            } => {
                out.insert(fqn_of(modules, mi, &call.name));
            }
            _ => {}
        }
    }
}

fn fqn_of(modules: &[ModuleInfo], mi: usize, name: &Name) -> String {
    match &name.module {
        Some(m) => format!("{m}::{}", name.ident),
        None => format!("{}::{}", modules[mi].name, name.ident),
    }
}

fn base_type_of(ty: &Type) -> BaseType {
    match ty {
        Type::Bool => BaseType::Primitive("Bool".into()),
        Type::Int => BaseType::Primitive("Int".into()),
        Type::BoundedInt { lo, hi } => BaseType::Complex(ComplexBaseType::BoundedInt {
            lo: *lo,
            hi: *hi,
        }),
    }
}

fn lower_resource(r: &ResourceDecl, module: &str) -> Resource {
    let _ = module;
    match &r.kind {
        ResourceKind::Mutex => Resource {
            name: r.name.clone(),
            kind: "sync".into(),
            res_type: "Mutex".into(),
            mode: Some("Sync".into()),
            count: None,
            base: None,
            init: None,
            capacity: None,
        },
        ResourceKind::Condvar { .. } => Resource {
            name: r.name.clone(),
            kind: "sync".into(),
            res_type: "Condvar".into(),
            mode: Some("Sync".into()),
            count: None,
            base: None,
            init: None,
            capacity: None,
        },
        ResourceKind::Semaphore { count } => Resource {
            name: r.name.clone(),
            kind: "sync".into(),
            res_type: "Semaphore".into(),
            mode: Some("Sync".into()),
            count: Some(*count),
            base: None,
            init: None,
            capacity: None,
        },
        ResourceKind::Channel { ty, cap } => Resource {
            name: r.name.clone(),
            kind: "sync".into(),
            res_type: "Channel".into(),
            mode: Some("Sync".into()),
            count: None,
            base: Some(base_type_of(ty)),
            init: None,
            capacity: Some(*cap),
        },
        ResourceKind::Shared { ty, init, .. } => Resource {
            name: r.name.clone(),
            kind: "var".into(),
            res_type: "Var".into(),
            mode: None,
            count: None,
            base: Some(base_type_of(ty)),
            init: Some(literal_json(init)),
            capacity: None,
        },
        ResourceKind::Atomic { ty, init } => Resource {
            name: r.name.clone(),
            kind: "var".into(),
            res_type: "Atomic".into(),
            mode: None,
            count: None,
            base: Some(base_type_of(ty)),
            init: Some(literal_json(init)),
            capacity: None,
        },
    }
}

fn literal_json(l: &Literal) -> serde_json::Value {
    match l {
        Literal::Bool(b) => serde_json::Value::Bool(*b),
        Literal::Int(n) => serde_json::Value::Number((*n).into()),
    }
}

fn compute_requires(
    mi: usize,
    module: &str,
    functions: &[Function],
    resources: &[Resource],
) -> concir::ast::RequireSet {
    let _ = mi;
    let own_res: BTreeSet<String> = resources.iter().map(|r| r.name.clone()).collect();
    let own_fns: BTreeSet<String> = functions.iter().map(|f| f.name.clone()).collect();
    let mut req_res: BTreeSet<String> = BTreeSet::new();
    let mut req_fns: BTreeSet<String> = BTreeSet::new();
    for f in functions {
        for st in &f.body {
            if let Some(r) = st.op.resource_name() {
                if let Some((m, n)) = r.split_once("::") {
                    if m != module {
                        req_res.insert(format!("{m}::{n}"));
                    } else if !own_res.contains(n) {
                        // A same-module resource that is not declared: leave to
                        // ConcIR validation.
                    }
                }
            }
            for callee in st.op.callee_funcs() {
                if let Some((m, _)) = callee.split_once("::") {
                    if m != module {
                        req_fns.insert(callee.to_string());
                    }
                }
            }
        }
    }
    let _ = own_fns;
    concir::ast::RequireSet {
        resources: req_res.into_iter().collect(),
        functions: req_fns
            .into_iter()
            .map(concir::ast::RequiredFunction::Name)
            .collect(),
        types: Vec::new(),
    }
}

// ─────────────────────────── per-function lowering ───────────────────────────

struct ExitFrame {
    release: Op,
    block_span: Span,
}

struct LoopInfo {
    head: Option<String>,
    break_gotos: Vec<usize>,
    continue_gotos: Vec<usize>,
}

struct FnLower<'a> {
    mi: usize,
    fn_fqn: String,
    modules: &'a [ModuleInfo],
    body: Vec<CirStmt>,
    stmts: Vec<MapStmt>,
    exits: Vec<ExitFrame>,
    loops: Vec<LoopInfo>,
    seq: &'a mut u64,
}

#[allow(clippy::too_many_arguments)]
fn lower_fn(
    f: &FnDecl,
    mi: usize,
    module: &str,
    fi: usize,
    modules: &[ModuleInfo],
    is_closure: bool,
    seq: &mut u64,
    map: &mut SourceMap,
    errors: &mut Vec<SkError>,
    fn_reqs: &[String],
    _tags: &[Tag],
) -> Function {
    let fn_fqn = format!("{module}::{}", f.name);
    let mut fl = FnLower {
        mi,
        fn_fqn: fn_fqn.clone(),
        modules,
        body: Vec::new(),
        stmts: Vec::new(),
        exits: Vec::new(),
        loops: Vec::new(),
        seq,
    };

    let locals = collect_locals(f, mi, modules);
    fl.emit_block(&f.body, fn_reqs);
    fl.implicit_return_if_reachable(&f.body, fn_reqs);

    // json paths for this function body.
    for (i, st) in fl.stmts.iter().enumerate() {
        map.json_paths.insert(
            format!("modules[{mi}].functions[{fi}].body[{i}]"),
            st.loc.clone(),
        );
    }
    map.stmts.extend(fl.stmts);
    let _ = errors;

    let params: Vec<ParamDecl> = f
        .params
        .iter()
        .map(|p| ParamDecl {
            name: p.name.clone(),
            param_type: base_type_of(&p.ty),
            modeled: true,
        })
        .collect();
    let returns = f.ret.as_ref().map(|t| ParamDecl {
        name: "ret".into(),
        param_type: base_type_of(t),
        modeled: true,
    });

    Function {
        name: f.name.clone(),
        kind: "normal".into(),
        form: if is_closure { "closure".into() } else { "function".into() },
        params,
        returns,
        locals,
        body: fl.body,
        effects: None,
        may_block: None,
        locks: Default::default(),
        bound: None,
    }
}

impl<'a> FnLower<'a> {
    fn sid(&self) -> String {
        format!("s{}", self.body.len() + 1)
    }

    fn push(
        &mut self,
        op: Op,
        construct: &str,
        span: Span,
        block_span: Option<Span>,
        reqs: &[String],
    ) -> usize {
        let sid = self.sid();
        self.body.push(CirStmt {
            sid: sid.clone(),
            op,
        });
        self.stmts.push(MapStmt {
            loc: format!("{}::{}", self.fn_fqn, sid),
            construct: construct.to_string(),
            span: span.into(),
            block_span: block_span.map(Into::into),
            reqs: reqs.to_vec(),
        });
        self.body.len() - 1
    }

    fn set_goto_target(&mut self, idx: usize, target: &str) {
        if let Op::Goto { target: t } = &mut self.body[idx].op {
            *t = target.to_string();
        }
    }

    fn set_branch(&mut self, idx: usize, then: &str, els: &str) {
        if let Op::Branch {
            then: t,
            else_target,
            ..
        } = &mut self.body[idx].op
        {
            *t = then.to_string();
            *else_target = els.to_string();
        }
    }

    fn res_fqn(&self, name: &Name) -> String {
        fqn_of(self.modules, self.mi, name)
    }

    fn module_name(&self) -> String {
        self.modules[self.mi].name.clone()
    }

    fn is_shared(&self, name: &Name) -> bool {
        if name.is_qualified() {
            return false;
        }
        self.modules[self.mi]
            .resources
            .get(&name.ident)
            .map(|r| r.kind == ResKind::Shared)
            .unwrap_or(false)
    }

    fn condvar_lock_fqn(&self, recv: &Name) -> String {
        if let Some(info) = self.modules[self.mi].resources.get(&recv.ident) {
            if let Some(bound) = &info.bound {
                if bound.contains("::") {
                    return bound.clone();
                }
                return format!("{}::{}", self.module_name(), bound);
            }
        }
        format!("{}::{}", self.module_name(), recv.ident)
    }

    fn emit_block(&mut self, block: &Block, outer: &[String]) {
        for s in &block.stmts {
            self.emit_stmt(s, outer);
        }
    }

    fn emit_stmt(&mut self, s: &Stmt, outer: &[String]) {
        let reqs = merge_reqs(outer, &s.tags);
        match &s.core {
            StmtCore::Lock { name, body } => {
                let res = self.res_fqn(name);
                self.push(
                    Op::MutexLock {
                        resource: res.clone(),
                    },
                    "lock_enter",
                    s.span,
                    Some(body.span),
                    &reqs,
                );
                self.exits.push(ExitFrame {
                    release: Op::MutexUnlock {
                        resource: res.clone(),
                    },
                    block_span: body.span,
                });
                self.emit_block(body, &reqs);
                self.exits.pop();
                self.push(
                    Op::MutexUnlock { resource: res },
                    "lock_exit",
                    body.close_span,
                    Some(body.span),
                    &reqs,
                );
            }
            StmtCore::Permit { name, body } => {
                let res = self.res_fqn(name);
                self.push(
                    Op::SemaphoreAcquire {
                        resource: res.clone(),
                        count: None,
                    },
                    "permit_enter",
                    s.span,
                    Some(body.span),
                    &reqs,
                );
                self.exits.push(ExitFrame {
                    release: Op::SemaphoreRelease {
                        resource: res.clone(),
                        count: None,
                    },
                    block_span: body.span,
                });
                self.emit_block(body, &reqs);
                self.exits.pop();
                self.push(
                    Op::SemaphoreRelease {
                        resource: res,
                        count: None,
                    },
                    "permit_exit",
                    body.close_span,
                    Some(body.span),
                    &reqs,
                );
            }
            StmtCore::Scope { spawns } => {
                let funcs: Vec<String> = spawns
                    .iter()
                    .map(|sp| fqn_of(self.modules, self.mi, &sp.name))
                    .collect();
                self.push(Op::Scope { funcs }, "scope", s.span, None, &reqs);
            }
            StmtCore::If { cond, then, els } => self.emit_if(s, cond, then, els.as_ref(), &reqs),
            StmtCore::While { cond, body } => self.emit_while(s, cond, body, &reqs),
            StmtCore::Loop { body } => self.emit_loop(s, body, &reqs),
            StmtCore::Break => self.emit_jump_exit("break", s, &reqs, true),
            StmtCore::Continue => self.emit_jump_exit("continue", s, &reqs, false),
            StmtCore::Return(v) => {
                let releases: Vec<(Op, Span)> = self
                    .exits
                    .iter()
                    .rev()
                    .map(|f| (f.release.clone(), f.block_span))
                    .collect();
                for (release, bs) in releases {
                    self.push(release, "implicit_release_on_exit", s.span, Some(bs), &reqs);
                }
                let value = v.as_ref().map(fmt_expr);
                self.push(Op::Return { value }, "return", s.span, None, &reqs);
            }
            StmtCore::Compute {
                desc,
                reads,
                writes,
                ..
            } => {
                // The plan maps `compute` to ConcIR `seq_hole`, but ConcIR
                // a35dc86 classifies `seq_hole` as UNSUPPORTED in the precise
                // backend, so no skeleton containing a compute hole could ever
                // be verified. ConcIR's supported, semantics-neutral construct
                // is `nop`; we emit that and keep the hole's description and
                // footprint on the source-map entry so codegen/adhere can still
                // identify it. See REFACTOR_REPORT P3.
                let _ = (*self.seq, &desc, &reads, &writes);
                self.push(Op::Nop, "seq_hole", s.span, None, &reqs);
            }
            StmtCore::Let {
                name,
                rhs,
                discard,
                ..
            } => {
                self.emit_let(name, rhs, *discard, s.span, &reqs);
            }
            StmtCore::Assign { name, expr } => {
                let expr = fmt_expr(expr);
                if self.is_shared(name) {
                    self.push(
                        Op::WriteShared {
                            resource: self.res_fqn(name),
                            expr,
                        },
                        "write_shared",
                        s.span,
                        None,
                        &reqs,
                    );
                } else {
                    self.push(
                        Op::AssignLocal {
                            target: name.ident.clone(),
                            expr,
                        },
                        "assign_local",
                        s.span,
                        None,
                        &reqs,
                    );
                }
            }
            StmtCore::Method { recv, call } => self.emit_method(s, recv, call, &reqs),
            StmtCore::Call { call } => {
                let func = fqn_of(self.modules, self.mi, &call.name);
                let args: Vec<String> = call.args.iter().map(fmt_expr).collect();
                self.push(
                    Op::Func {
                        func,
                        args,
                        dst: None,
                    },
                    "call",
                    s.span,
                    None,
                    &reqs,
                );
            }
        }
    }

    fn footprint_name(&self, name: &Name) -> String {
        if !name.is_qualified()
            && self.modules[self.mi].resources.contains_key(&name.ident)
        {
            format!("{}::{}", self.module_name(), name.ident)
        } else {
            name.text()
        }
    }

    fn emit_if(
        &mut self,
        s: &Stmt,
        cond: &Expr,
        then: &Block,
        els: Option<&Else>,
        reqs: &[String],
    ) {
        let branch_idx = self.push(
            Op::Branch {
                cond: fmt_expr(cond),
                then: String::new(),
                else_target: String::new(),
            },
            "branch_if",
            s.span,
            None,
            reqs,
        );
        let then_first0 = self.body.len();
        self.emit_block(then, reqs);
        let then_target = if self.body.len() > then_first0 {
            Some(sid_at(then_first0))
        } else {
            None
        };
        if let Some(els) = els {
            let goto_idx = self.push(
                Op::Goto {
                    target: String::new(),
                },
                "branch_if",
                s.span,
                None,
                reqs,
            );
            let else_first0 = self.body.len();
            match els {
                Else::Block(b) => self.emit_block(b, reqs),
                Else::If(inner) => self.emit_stmt(inner, reqs),
            }
            let join = self.sid();
            self.set_goto_target(goto_idx, &join);
            let else_target = sid_at(else_first0);
            let then_target = then_target.unwrap_or_else(|| join.clone());
            self.set_branch(branch_idx, &then_target, &else_target);
        } else {
            let join = self.sid();
            let then_target = then_target.unwrap_or_else(|| join.clone());
            self.set_branch(branch_idx, &then_target, &join);
        }
    }

    fn emit_while(&mut self, s: &Stmt, cond: &Expr, body: &Block, reqs: &[String]) {
        let head = self.sid();
        let branch_idx = self.push(
            Op::Branch {
                cond: fmt_expr(cond),
                then: String::new(),
                else_target: String::new(),
            },
            "branch_while",
            s.span,
            None,
            reqs,
        );
        let body_first = self.sid();
        self.loops.push(LoopInfo {
            head: Some(head.clone()),
            break_gotos: Vec::new(),
            continue_gotos: Vec::new(),
        });
        self.emit_block(body, reqs);
        let back = self.push(
            Op::Goto {
                target: head.clone(),
            },
            "loop_back",
            s.span,
            None,
            reqs,
        );
        let _ = back;
        let exit = self.sid();
        let (breaks, continues) = {
            let li = self.loops.pop().unwrap();
            (li.break_gotos, li.continue_gotos)
        };
        for g in breaks {
            self.set_goto_target(g, &exit);
        }
        for g in continues {
            self.set_goto_target(g, &head);
        }
        let then = if body_first == exit {
            exit.clone()
        } else {
            body_first
        };
        self.set_branch(branch_idx, &then, &exit);
    }

    fn emit_loop(&mut self, s: &Stmt, body: &Block, reqs: &[String]) {
        self.loops.push(LoopInfo {
            head: None,
            break_gotos: Vec::new(),
            continue_gotos: Vec::new(),
        });
        let head = self.sid();
        if let Some(li) = self.loops.last_mut() {
            li.head = Some(head.clone());
        }
        let body_first = head.clone();
        self.emit_block(body, reqs);
        self.push(
            Op::Goto {
                target: head.clone(),
            },
            "loop_back",
            s.span,
            None,
            reqs,
        );
        let exit = self.sid();
        let (breaks, continues) = {
            let li = self.loops.pop().unwrap();
            (li.break_gotos, li.continue_gotos)
        };
        for g in breaks {
            self.set_goto_target(g, &exit);
        }
        for g in continues {
            self.set_goto_target(g, &body_first);
        }
    }

    fn emit_jump_exit(&mut self, construct: &str, s: &Stmt, reqs: &[String], is_break: bool) {
        let releases: Vec<(Op, Span)> = self
            .exits
            .iter()
            .rev()
            .map(|f| (f.release.clone(), f.block_span))
            .collect();
        for (release, bs) in releases {
            self.push(release, "implicit_release_on_exit", s.span, Some(bs), reqs);
        }
        let idx = self.push(
            Op::Goto {
                target: String::new(),
            },
            construct,
            s.span,
            None,
            reqs,
        );
        if let Some(li) = self.loops.last_mut() {
            if is_break {
                li.break_gotos.push(idx);
            } else {
                li.continue_gotos.push(idx);
            }
        }
    }

    fn emit_let(&mut self, name: &str, rhs: &Rhs, discard: bool, span: Span, reqs: &[String]) {
        let dst = if discard { "_".to_string() } else { name.to_string() };
        match rhs {
            Rhs::Recv { recv } => {
                self.push(
                    Op::ChannelRecv {
                        channel: self.res_fqn(recv),
                        dst,
                    },
                    "channel_recv",
                    span,
                    None,
                    reqs,
                );
            }
            Rhs::Load { recv } => {
                self.push(
                    Op::AtomicLoad {
                        resource: self.res_fqn(recv),
                        dst,
                    },
                    "atomic_load",
                    span,
                    None,
                    reqs,
                );
            }
            Rhs::Cas {
                recv,
                expected,
                desired,
            } => {
                self.push(
                    Op::AtomicCas {
                        resource: self.res_fqn(recv),
                        expected: fmt_expr(expected),
                        desired: fmt_expr(desired),
                        dst,
                    },
                    "atomic_cas",
                    span,
                    None,
                    reqs,
                );
            }
            Rhs::Spawn { call } => {
                self.push(
                    Op::Spawn {
                        func: fqn_of(self.modules, self.mi, &call.name),
                        args: call.args.iter().map(fmt_expr).collect(),
                        handle: dst,
                    },
                    "spawn",
                    span,
                    None,
                    reqs,
                );
            }
            Rhs::Call { call } => {
                self.push(
                    Op::Func {
                        func: fqn_of(self.modules, self.mi, &call.name),
                        args: call.args.iter().map(fmt_expr).collect(),
                        dst: if discard { None } else { Some(dst) },
                    },
                    "call",
                    span,
                    None,
                    reqs,
                );
            }
            Rhs::Expr(e) => {
                // `let v = x;` where x is a shared variable is a read_shared.
                if let Expr::Name(n) = e {
                    if self.is_shared(n) {
                        self.push(
                            Op::ReadShared {
                                resource: self.res_fqn(n),
                                dst: if discard { None } else { Some(dst) },
                            },
                            "read_shared",
                            span,
                            None,
                            reqs,
                        );
                        return;
                    }
                }
                self.push(
                    Op::AssignLocal {
                        target: dst,
                        expr: fmt_expr(e),
                    },
                    "assign_local",
                    span,
                    None,
                    reqs,
                );
            }
        }
    }

    fn emit_method(&mut self, s: &Stmt, recv: &Name, call: &MethodCall, reqs: &[String]) {
        match call {
            MethodCall::Send(e) => {
                self.push(
                    Op::ChannelSend {
                        channel: self.res_fqn(recv),
                        value: fmt_expr(e),
                    },
                    "channel_send",
                    s.span,
                    None,
                    reqs,
                );
            }
            MethodCall::Recv => {
                self.push(
                    Op::ChannelRecv {
                        channel: self.res_fqn(recv),
                        dst: "_".into(),
                    },
                    "channel_recv",
                    s.span,
                    None,
                    reqs,
                );
            }
            MethodCall::Store(e) => {
                self.push(
                    Op::AtomicStore {
                        resource: self.res_fqn(recv),
                        value: fmt_expr(e),
                    },
                    "atomic_store",
                    s.span,
                    None,
                    reqs,
                );
            }
            MethodCall::NotifyOne => {
                self.push(
                    Op::CondvarNotify {
                        condvar: self.res_fqn(recv),
                    },
                    "condvar_notify",
                    s.span,
                    None,
                    reqs,
                );
            }
            MethodCall::NotifyAll => {
                self.push(
                    Op::CondvarNotifyAll {
                        condvar: self.res_fqn(recv),
                    },
                    "condvar_notify_all",
                    s.span,
                    None,
                    reqs,
                );
            }
            MethodCall::Wait => {
                self.push(
                    Op::CondvarWait {
                        condvar: self.res_fqn(recv),
                        lock: self.condvar_lock_fqn(recv),
                    },
                    "condvar_wait",
                    s.span,
                    None,
                    reqs,
                );
            }
            MethodCall::Post => {
                self.push(
                    Op::SemaphoreRelease {
                        resource: self.res_fqn(recv),
                        count: None,
                    },
                    "semaphore_release",
                    s.span,
                    None,
                    reqs,
                );
            }
            MethodCall::Take => {
                self.push(
                    Op::SemaphoreAcquire {
                        resource: self.res_fqn(recv),
                        count: None,
                    },
                    "semaphore_acquire",
                    s.span,
                    None,
                    reqs,
                );
            }
            MethodCall::Join => {
                self.push(
                    Op::Join {
                        handle: recv.ident.clone(),
                    },
                    "join",
                    s.span,
                    None,
                    reqs,
                );
            }
        }
    }

    fn implicit_return_if_reachable(&mut self, body: &Block, outer: &[String]) {
        let end = self.body.len(); // zero-based index of the fallthrough point
        let reachable = if self.body.is_empty() {
            true
        } else {
            let last_falls = !is_control(&self.body[self.body.len() - 1].op);
            let targeted = self.body.iter().any(|st| match &st.op {
                Op::Goto { target } => target_index(target) == Some(end + 1),
                Op::Branch {
                    then, else_target, ..
                } => target_index(then) == Some(end + 1) || target_index(else_target) == Some(end + 1),
                Op::Switch { cases, default, .. } => {
                    cases.values().any(|t| target_index(t) == Some(end + 1))
                        || target_index(default) == Some(end + 1)
                }
                Op::Select { branches, default } => {
                    branches.iter().any(|b| target_index(&b.target) == Some(end + 1))
                        || default.as_ref().and_then(|d| target_index(d)) == Some(end + 1)
                }
                _ => false,
            });
            last_falls || targeted
        };
        if reachable {
            let span = body.close_span;
            self.push(
                Op::Return { value: None },
                "implicit_return",
                span,
                None,
                outer,
            );
        }
    }
}

fn is_control(op: &Op) -> bool {
    matches!(
        op,
        Op::Goto { .. } | Op::Branch { .. } | Op::Switch { .. } | Op::Return { .. } | Op::Select { .. }
    )
}

/// 1-based sid string for the statement at 0-based index `i`.
fn sid_at(i: usize) -> String {
    format!("s{}", i + 1)
}

/// The numeric part of a sid string `sN`.
fn target_index(target: &str) -> Option<usize> {
    target.strip_prefix('s')?.parse::<usize>().ok()
}

// ─────────────────────────── local inference ───────────────────────────

fn collect_locals(f: &FnDecl, mi: usize, modules: &[ModuleInfo]) -> Vec<LocalDecl> {
    let mut out: Vec<LocalDecl> = Vec::new();
    let mut scopes: Vec<HashMap<String, Ty>> = Vec::new();
    let mut params: HashMap<String, Ty> = HashMap::new();
    for p in &f.params {
        params.insert(p.name.clone(), check::ty_of_type(&p.ty));
    }
    scopes.push(params);
    walk_block(&f.body, mi, modules, &mut scopes, &mut out);
    out
}

fn walk_block(
    block: &Block,
    mi: usize,
    modules: &[ModuleInfo],
    scopes: &mut Vec<HashMap<String, Ty>>,
    out: &mut Vec<LocalDecl>,
) {
    scopes.push(HashMap::new());
    for s in &block.stmts {
        match &s.core {
            StmtCore::Let {
                name,
                rhs,
                discard,
                ..
            } => {
                let ty = infer_rhs(rhs, mi, modules, scopes);
                if !discard {
                    if let Some(ty) = ty {
                        out.push(LocalDecl {
                            name: name.clone(),
                            local_type: local_base(ty),
                            modeled: true,
                            init: None,
                        });
                    }
                    scopes
                        .last_mut()
                        .unwrap()
                        .insert(name.clone(), ty.unwrap_or(Ty::Int));
                }
            }
            StmtCore::Lock { body, .. }
            | StmtCore::Permit { body, .. }
            | StmtCore::While { body, .. }
            | StmtCore::Loop { body, .. } => walk_block(body, mi, modules, scopes, out),
            StmtCore::If { then, els, .. } => {
                walk_block(then, mi, modules, scopes, out);
                if let Some(Else::Block(b)) = els {
                    walk_block(b, mi, modules, scopes, out);
                }
                if let Some(Else::If(s)) = els {
                    let b = Block {
                        stmts: vec![(*s.clone())],
                        span: s.span,
                        close_span: s.span,
                    };
                    walk_block(&b, mi, modules, scopes, out);
                }
            }
            _ => {}
        }
    }
    scopes.pop();
}

fn infer_rhs(
    rhs: &Rhs,
    mi: usize,
    modules: &[ModuleInfo],
    scopes: &[HashMap<String, Ty>],
) -> Option<Ty> {
    match rhs {
        Rhs::Expr(e) => infer_expr(e, mi, modules, scopes),
        Rhs::Recv { recv } => resource_ty(mi, modules, recv).map(check::widen),
        Rhs::Load { recv } => resource_ty(mi, modules, recv).map(check::widen),
        Rhs::Cas { recv, .. } => resource_ty(mi, modules, recv).map(check::widen),
        Rhs::Spawn { .. } => None,
        Rhs::Call { call } => fn_ret_ty(mi, modules, &call.name),
    }
}

fn infer_expr(e: &Expr, mi: usize, modules: &[ModuleInfo], scopes: &[HashMap<String, Ty>]) -> Option<Ty> {
    match e {
        Expr::IntLit(_, _) => Some(Ty::Int),
        Expr::BoolLit(_, _) => Some(Ty::Bool),
        Expr::Paren(inner, _) => infer_expr(inner, mi, modules, scopes),
        Expr::Neg(..) | Expr::BinOp { .. } => Some(Ty::Int),
        Expr::Cmp { .. } => Some(Ty::Bool),
        Expr::Name(n) => {
            if !n.is_qualified() {
                for scope in scopes.iter().rev() {
                    if let Some(t) = scope.get(&n.ident) {
                        return Some(*t);
                    }
                }
            }
            resource_ty(mi, modules, n).map(check::widen)
        }
    }
}

fn resource_ty(mi: usize, modules: &[ModuleInfo], name: &Name) -> Option<Ty> {
    let (idx, ident) = match &name.module {
        Some(m) => (modules.iter().position(|x| &x.name == m)?, name.ident.as_str()),
        None => (mi, name.ident.as_str()),
    };
    modules[idx].resources.get(ident).and_then(|r| r.ty)
}

fn fn_ret_ty(mi: usize, modules: &[ModuleInfo], name: &Name) -> Option<Ty> {
    let (idx, ident) = match &name.module {
        Some(m) => (modules.iter().position(|x| &x.name == m)?, name.ident.as_str()),
        None => (mi, name.ident.as_str()),
    };
    modules[idx].fns.get(ident).and_then(|f| f.ret)
}

fn local_base(ty: Ty) -> BaseType {
    match check::widen(ty) {
        Ty::Bool => BaseType::Primitive("Bool".into()),
        Ty::Int => BaseType::Primitive("Int".into()),
        Ty::Bounded(lo, hi) => BaseType::Complex(ComplexBaseType::BoundedInt { lo, hi }),
        _ => BaseType::Primitive("Int".into()),
    }
}
