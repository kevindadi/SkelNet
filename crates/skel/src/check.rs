//! Skeleton front-end checks (`S1xx`/`S2xx`). ConcIR-checkable properties are
//! deliberately not re-implemented here.

use std::collections::{BTreeSet, HashMap, HashSet};

use crate::ast::*;
use crate::error::SkError;
use crate::span::Span;

/// Requirement ids parsed from `--reqs requirements.json`.
#[derive(Debug, Clone, Default)]
pub struct Requirements {
    pub ids: BTreeSet<u64>,
}

impl Requirements {
    /// Collect every `R<n>` string anywhere in a requirements document.
    pub fn from_json(value: &serde_json::Value) -> Self {
        let mut ids = BTreeSet::new();
        collect_req_ids(value, &mut ids);
        Requirements { ids }
    }
}

fn collect_req_ids(value: &serde_json::Value, ids: &mut BTreeSet<u64>) {
    match value {
        serde_json::Value::String(s) => {
            if let Some(n) = s.strip_prefix('R').and_then(|r| r.parse::<u64>().ok()) {
                ids.insert(n);
            }
        }
        serde_json::Value::Array(a) => {
            for v in a {
                collect_req_ids(v, ids);
            }
        }
        serde_json::Value::Object(o) => {
            for v in o.values() {
                collect_req_ids(v, ids);
            }
        }
        _ => {}
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResKind {
    Mutex,
    Condvar,
    Semaphore,
    Channel,
    Shared,
    Atomic,
}

#[derive(Debug, Clone)]
pub struct ResInfo {
    pub kind: ResKind,
    pub ty: Option<Ty>,
    pub span: Span,
    /// Condvar: the bound mutex name as written.
    pub bound: Option<String>,
    pub guarded_by: Option<String>,
}

#[derive(Debug, Clone)]
pub struct FnInfo {
    pub name: String,
    pub params: Vec<(String, Ty)>,
    pub ret: Option<Ty>,
    pub is_extern: bool,
    pub span: Span,
}

#[derive(Debug, Clone, Default)]
pub struct ModuleInfo {
    pub name: String,
    pub resources: HashMap<String, ResInfo>,
    pub fns: HashMap<String, FnInfo>,
    pub span: Span,
}

/// Value types used for front-end checking and local inference.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ty {
    Bool,
    Int,
    Bounded(i64, i64),
    Handle,
    Void,
}

impl Ty {
    pub fn display(&self) -> String {
        match self {
            Ty::Bool => "Bool".into(),
            Ty::Int => "Int".into(),
            Ty::Bounded(lo, hi) => format!("Int[{lo}..={hi}]"),
            Ty::Handle => "spawn handle".into(),
            Ty::Void => "()".into(),
        }
    }

    pub fn is_int(&self) -> bool {
        matches!(self, Ty::Int | Ty::Bounded(..))
    }
}

pub fn ty_of_type(t: &Type) -> Ty {
    match t {
        Type::Bool => Ty::Bool,
        Type::Int => Ty::Int,
        Type::BoundedInt { lo, hi } => Ty::Bounded(*lo, *hi),
    }
}

/// Widen a resource base type for local inference: bounded `Int` becomes `Int`.
pub fn widen(t: Ty) -> Ty {
    match t {
        Ty::Bounded(..) => Ty::Int,
        other => other,
    }
}

/// Build the module/resource/function tables (also used by lowering).
pub fn build(file: &File) -> Vec<ModuleInfo> {
    let mut modules = Vec::new();
    for m in &file.modules {
        let mut info = ModuleInfo {
            name: m.name.clone(),
            span: m.span,
            ..Default::default()
        };
        for item in &m.items {
            match &item.kind {
                ItemKind::Resource(r) => {
                    let (kind, ty, bound, guarded_by) = match &r.kind {
                        ResourceKind::Mutex => (ResKind::Mutex, None, None, None),
                        ResourceKind::Condvar { bound } => {
                            (ResKind::Condvar, None, Some(bound.text()), None)
                        }
                        ResourceKind::Semaphore { .. } => (ResKind::Semaphore, None, None, None),
                        ResourceKind::Channel { .. } => (ResKind::Channel, None, None, None),
                        ResourceKind::Shared {
                            ty, guarded_by, ..
                        } => (
                            ResKind::Shared,
                            Some(ty_of_type(ty)),
                            None,
                            guarded_by.as_ref().map(|n| n.text()),
                        ),
                        ResourceKind::Atomic { ty, .. } => {
                            (ResKind::Atomic, Some(ty_of_type(ty)), None, None)
                        }
                    };
                    info.resources.insert(
                        r.name.clone(),
                        ResInfo {
                            kind,
                            ty,
                            span: r.span,
                            bound,
                            guarded_by,
                        },
                    );
                }
                ItemKind::Fn(f) => {
                    info.fns.insert(
                        f.name.clone(),
                        FnInfo {
                            name: f.name.clone(),
                            params: f
                                .params
                                .iter()
                                .map(|p| (p.name.clone(), ty_of_type(&p.ty)))
                                .collect(),
                            ret: f.ret.as_ref().map(ty_of_type),
                            is_extern: false,
                            span: f.span,
                        },
                    );
                }
                ItemKind::ExternFn(e) => {
                    info.fns.insert(
                        e.name.clone(),
                        FnInfo {
                            name: e.name.clone(),
                            params: Vec::new(),
                            ret: None,
                            is_extern: true,
                            span: e.span,
                        },
                    );
                }
            }
        }
        modules.push(info);
    }
    modules
}

pub fn resolve_module<'a>(modules: &'a [ModuleInfo], name: &str) -> Option<usize> {
    modules.iter().position(|m| m.name == name)
}

fn resolve_resource<'a>(
    modules: &'a [ModuleInfo],
    cur: usize,
    name: &Name,
) -> Option<&'a ResInfo> {
    let (mi, ident) = match &name.module {
        Some(m) => (resolve_module(modules, m)?, name.ident.as_str()),
        None => (cur, name.ident.as_str()),
    };
    modules[mi].resources.get(ident)
}

fn resolve_fn<'a>(modules: &'a [ModuleInfo], cur: usize, name: &Name) -> Option<&'a FnInfo> {
    let (mi, ident) = match &name.module {
        Some(m) => (resolve_module(modules, m)?, name.ident.as_str()),
        None => (cur, name.ident.as_str()),
    };
    modules[mi].fns.get(ident)
}

pub fn check(file: &File, reqs: Option<&Requirements>) -> Vec<SkError> {
    let mut c = Checker {
        modules: build(file),
        errors: Vec::new(),
        tag_numbers: BTreeSet::new(),
        module: 0,
    };
    c.check_module_duplicates(file);
    c.collect_tags(file);
    for (mi, m) in file.modules.iter().enumerate() {
        c.module = mi;
        c.check_module_duplicates_in(m);
        for item in &m.items {
            match &item.kind {
                ItemKind::Resource(r) => c.check_resource(item, r),
                ItemKind::Fn(f) => c.check_fn(f),
                ItemKind::ExternFn(_) => {}
            }
        }
    }
    if let Some(reqs) = reqs {
        c.check_requirements(file, reqs);
    }
    c.errors
}

struct Checker {
    modules: Vec<ModuleInfo>,
    errors: Vec<SkError>,
    tag_numbers: BTreeSet<u64>,
    module: usize,
}

struct FnCtx {
    ret: Option<Ty>,
    scopes: Vec<HashMap<String, Ty>>,
    locks: Vec<String>,
    loop_depth: usize,
}

impl FnCtx {
    fn lookup_local(&self, name: &str) -> Option<Ty> {
        for scope in self.scopes.iter().rev() {
            if let Some(t) = scope.get(name) {
                return Some(*t);
            }
        }
        None
    }
}

impl Checker {
    fn err(&mut self, code: &str, span: Span, msg: impl Into<String>) {
        self.errors.push(SkError::error(code, span, msg));
    }

    fn warn(&mut self, code: &str, span: Span, msg: impl Into<String>) {
        self.errors.push(SkError::warning(code, Some(span), msg, None));
    }

    fn check_module_duplicates(&mut self, file: &File) {
        let mut seen: HashSet<&str> = HashSet::new();
        for m in &file.modules {
            if !seen.insert(&m.name) {
                self.err("S102", m.span, format!("duplicate module `{}`", m.name));
            }
        }
    }

    fn check_module_duplicates_in(&mut self, m: &Module) {
        let mut res: HashSet<&str> = HashSet::new();
        let mut fns: HashSet<&str> = HashSet::new();
        for item in &m.items {
            match &item.kind {
                ItemKind::Resource(r) => {
                    if !res.insert(&r.name) {
                        self.err(
                            "S102",
                            r.span,
                            format!("duplicate resource `{}` in module `{}`", r.name, m.name),
                        );
                    }
                }
                ItemKind::Fn(f) => {
                    if !fns.insert(&f.name) {
                        self.err(
                            "S102",
                            f.span,
                            format!("duplicate function `{}` in module `{}`", f.name, m.name),
                        );
                    }
                }
                ItemKind::ExternFn(e) => {
                    if !fns.insert(&e.name) {
                        self.err(
                            "S102",
                            e.span,
                            format!("duplicate function `{}` in module `{}`", e.name, m.name),
                        );
                    }
                }
            }
        }
    }

    fn collect_tags(&mut self, file: &File) {
        fn item_tags(tags: &[Tag], out: &mut BTreeSet<u64>, errs: &mut Vec<SkError>) {
            for t in tags {
                match t.n {
                    Some(n) => {
                        out.insert(n);
                    }
                    None => errs.push(SkError::error(
                        "S109",
                        t.span,
                        format!("`@{}` is not a valid requirement tag", t.raw),
                    ).with_hint("tags must look like `@R1`, `@R2`, ...")),
                }
            }
        }
        fn block_tags(b: &Block, out: &mut BTreeSet<u64>, errs: &mut Vec<SkError>) {
            for s in &b.stmts {
                item_tags(&s.tags, out, errs);
                match &s.core {
                    StmtCore::Lock { body, .. }
                    | StmtCore::Permit { body, .. }
                    | StmtCore::While { body, .. }
                    | StmtCore::Loop { body, .. } => block_tags(body, out, errs),
                    StmtCore::If { then, els, .. } => {
                        block_tags(then, out, errs);
                        match els {
                            Some(Else::Block(b)) => block_tags(b, out, errs),
                            Some(Else::If(s)) => {
                                item_tags(&s.tags, out, errs);
                                if let StmtCore::If { then, els, .. } = &s.core {
                                    block_tags(then, out, errs);
                                    if let Some(Else::Block(b)) = els {
                                        block_tags(b, out, errs);
                                    }
                                    if let Some(Else::If(inner)) = els {
                                        item_tags(&inner.tags, out, errs);
                                    }
                                }
                            }
                            None => {}
                        }
                    }
                    _ => {}
                }
            }
        }
        for m in &file.modules {
            for item in &m.items {
                item_tags(&item.tags, &mut self.tag_numbers, &mut self.errors);
                if let ItemKind::Fn(f) = &item.kind {
                    block_tags(&f.body, &mut self.tag_numbers, &mut self.errors);
                }
            }
        }
    }

    fn check_requirements(&mut self, file: &File, reqs: &Requirements) {
        for id in &reqs.ids {
            if !self.tag_numbers.contains(id) {
                self.warn(
                    "S201",
                    file.span,
                    format!("requirement R{id} has no `@R{id}` annotation in the skeleton"),
                );
            }
        }
        // S202: annotated ids not in the requirements document.
        let annotated = self.tag_numbers.clone();
        for n in annotated {
            if !reqs.ids.contains(&n) {
                self.warn(
                    "S202",
                    file.span,
                    format!("`@R{n}` references a requirement id not present in requirements.json"),
                );
            }
        }
    }

    fn check_resource(&mut self, item: &Item, r: &ResourceDecl) {
        match &r.kind {
            ResourceKind::Condvar { bound } => {
                let Some(info) = resolve_resource(&self.modules, self.module, bound) else {
                    self.err(
                        "S101",
                        bound.span,
                        format!("condvar `{}` is bound to undefined name `{}`", r.name, bound.text()),
                    );
                    return;
                };
                if info.kind != ResKind::Mutex {
                    self.err(
                        "S103",
                        bound.span,
                        format!("condvar `{}` must be bound to a mutex, but `{}` is a {}", r.name, bound.text(), kind_name(info.kind)),
                    );
                }
                let _ = item;
            }
            ResourceKind::Shared { ty, init, guarded_by } => {
                self.check_init(ty, init, r.span);
                if let Some(g) = guarded_by {
                    let Some(info) = resolve_resource(&self.modules, self.module, g) else {
                        self.err(
                            "S101",
                            g.span,
                            format!("`guarded_by {}` refers to an undefined resource", g.text()),
                        );
                        return;
                    };
                    if info.kind != ResKind::Mutex {
                        self.err(
                            "S103",
                            g.span,
                            format!("`guarded_by {}` must name a mutex, but it is a {}", g.text(), kind_name(info.kind)),
                        );
                    }
                }
            }
            ResourceKind::Atomic { ty, init } => {
                self.check_init(ty, init, r.span);
            }
            ResourceKind::Semaphore { count } => {
                if *count < 0 {
                    self.err("S108", r.span, format!("semaphore `{}` has a negative initial count", r.name));
                }
            }
            ResourceKind::Channel { .. } | ResourceKind::Mutex => {}
        }
    }

    fn check_init(&mut self, ty: &Type, init: &Literal, span: Span) {
        match (ty, init) {
            (Type::Bool, Literal::Bool(_)) => {}
            (Type::Bool, Literal::Int(_)) => self.err(
                "S108",
                span,
                "initializer is an integer but the declared type is `Bool`",
            ),
            (Type::Int, Literal::Bool(_)) => self.err(
                "S108",
                span,
                "initializer is a boolean but the declared type is `Int`",
            ),
            (Type::Int, Literal::Int(_)) => {}
            (Type::BoundedInt { lo, hi }, Literal::Bool(_)) => self.err(
                "S108",
                span,
                format!("initializer is a boolean but the declared type is `Int[{lo}..={hi}]`"),
            ),
            (Type::BoundedInt { lo, hi }, Literal::Int(n)) => {
                if n < lo || n > hi {
                    self.err(
                        "S108",
                        span,
                        format!("initializer {n} is outside the declared range Int[{lo}..={hi}]"),
                    );
                }
            }
        }
    }

    fn check_fn(&mut self, f: &FnDecl) {
        let mut scopes: Vec<HashMap<String, Ty>> = vec![HashMap::new()];
        for p in &f.params {
            if scopes[0].contains_key(&p.name) {
                self.err("S102", p.span, format!("duplicate parameter `{}`", p.name));
            }
            scopes[0].insert(p.name.clone(), ty_of_type(&p.ty));
        }
        let ret = f.ret.as_ref().map(ty_of_type);
        let mut ctx = FnCtx {
            ret,
            scopes,
            locks: Vec::new(),
            loop_depth: 0,
        };
        self.check_block(&mut ctx, &f.body);
    }

    fn check_block(&mut self, ctx: &mut FnCtx, block: &Block) {
        ctx.scopes.push(HashMap::new());
        for s in &block.stmts {
            self.check_stmt(ctx, s);
        }
        ctx.scopes.pop();
    }

    fn check_stmt(&mut self, ctx: &mut FnCtx, s: &Stmt) {
        match &s.core {
            StmtCore::Lock { name, body } => {
                match resolve_resource(&self.modules, self.module, name) {
                    None => self.err("S101", name.span, format!("undefined resource `{}`", name.text())),
                    Some(info) if info.kind != ResKind::Mutex => self.err(
                        "S103",
                        name.span,
                        format!("`lock {}` requires a mutex, but it is a {}", name.text(), kind_name(info.kind)),
                    ),
                    Some(_) => {}
                }
                let key = self.resource_key(name);
                ctx.locks.push(key);
                self.check_block(ctx, body);
                ctx.locks.pop();
            }
            StmtCore::Permit { name, body } => {
                match resolve_resource(&self.modules, self.module, name) {
                    None => self.err("S101", name.span, format!("undefined resource `{}`", name.text())),
                    Some(info) if info.kind != ResKind::Semaphore => self.err(
                        "S103",
                        name.span,
                        format!("`permit {}` requires a semaphore, but it is a {}", name.text(), kind_name(info.kind)),
                    ),
                    Some(_) => {}
                }
                ctx.scopes.push(HashMap::new());
                for st in &body.stmts {
                    self.check_stmt(ctx, st);
                }
                ctx.scopes.pop();
            }
            StmtCore::Scope { spawns } => {
                for sp in spawns {
                    match resolve_fn(&self.modules, self.module, &sp.name) {
                        None => {
                            if resolve_resource(&self.modules, self.module, &sp.name).is_some() {
                                self.err(
                                    "S106",
                                    sp.name.span,
                                    format!(
                                        "`scope` spawn target `{}` is not a `fn`",
                                        sp.name.text()
                                    ),
                                );
                            } else {
                                self.err(
                                    "S101",
                                    sp.name.span,
                                    format!(
                                        "undefined function `{}` in `scope spawn`",
                                        sp.name.text()
                                    ),
                                );
                            }
                        }
                        Some(_) => {}
                    }
                }
            }
            StmtCore::If { cond, then, els } => {
                self.check_cond(ctx, cond);
                self.check_block(ctx, then);
                match els {
                    Some(Else::Block(b)) => self.check_block(ctx, b),
                    Some(Else::If(s)) => self.check_stmt(ctx, s),
                    None => {}
                }
            }
            StmtCore::While { cond, body } => {
                self.check_cond(ctx, cond);
                ctx.loop_depth += 1;
                self.check_block(ctx, body);
                ctx.loop_depth -= 1;
            }
            StmtCore::Loop { body } => {
                ctx.loop_depth += 1;
                self.check_block(ctx, body);
                ctx.loop_depth -= 1;
            }
            StmtCore::Break | StmtCore::Continue => {
                if ctx.loop_depth == 0 {
                    self.err(
                        "S105",
                        s.span,
                        "`break`/`continue` may only appear inside a loop",
                    );
                }
            }
            StmtCore::Return(v) => {
                if let Some(e) = v {
                    let t = self.expr_ty(ctx, e);
                    if t != Ty::Void {
                        self.assignable(ctx.ret, t, e.span(), "return value");
                    }
                } else if let Some(ret) = ctx.ret {
                    if ret != Ty::Void {
                        self.err(
                            "S108",
                            s.span,
                            format!("function returns `{}` but this `return` has no value", ret.display()),
                        );
                    }
                }
            }
            StmtCore::Compute { reads, writes, .. } => {
                for n in reads.iter().chain(writes.iter()) {
                    self.check_value_name(ctx, n);
                }
            }
            StmtCore::Let {
                name,
                name_span,
                ty,
                rhs,
                discard,
            } => {
                let rhs_ty = self.rhs_ty(ctx, rhs);
                let final_ty = match ty {
                    Some(t) => {
                        let declared = ty_of_type(t);
                        if rhs_ty != Ty::Void {
                            self.assignable(Some(declared), rhs_ty, rhs_span(rhs), "local initializer");
                        }
                        declared
                    }
                    None => rhs_ty,
                };
                if !discard {
                    if ctx.lookup_local(name).is_some() {
                        // Shadowing is allowed by Rust semantics, but a repeat
                        // in the same scope is a duplicate definition.
                        if ctx.scopes.last().map(|s| s.contains_key(name)).unwrap_or(false) {
                            self.err("S102", *name_span, format!("duplicate local `{name}`"));
                        }
                    }
                    ctx.scopes
                        .last_mut()
                        .unwrap()
                        .insert(name.clone(), final_ty);
                }
            }
            StmtCore::Assign { name, expr } => {
                let rhs_ty = self.expr_ty(ctx, expr);
                if let Some(local) = ctx.lookup_local(&name.ident).filter(|_| !name.is_qualified()) {
                    if local == Ty::Handle {
                        self.err(
                            "S108",
                            name.span,
                            format!("`{}` is a spawn handle and cannot be assigned", name.text()),
                        );
                    }
                    if rhs_ty != Ty::Void {
                        self.assignable(Some(local), rhs_ty, expr.span(), "assignment");
                    }
                } else {
                    match resolve_resource(&self.modules, self.module, name) {
                        None => self.err("S101", name.span, format!("undefined name `{}`", name.text())),
                        Some(info) if !matches!(info.kind, ResKind::Shared) => self.err(
                            "S103",
                            name.span,
                            format!(
                                "`{}` is not assignable with `=` (it is a {}); use `.store()` for atomics",
                                name.text(),
                                kind_name(info.kind)
                            ),
                        ),
                        Some(info) => {
                            if let Some(base) = info.ty {
                                if rhs_ty != Ty::Void {
                                    self.assignable(Some(base), rhs_ty, expr.span(), "assignment");
                                }
                            }
                        }
                    }
                }
            }
            StmtCore::Method { recv, call } => {
                self.check_method(ctx, recv, call, s.span);
            }
            StmtCore::Call { call } => {
                self.check_call(ctx, call);
            }
        }
    }

    fn check_cond(&mut self, ctx: &mut FnCtx, cond: &Expr) {
        let t = self.expr_ty(ctx, cond);
        if t != Ty::Void && t != Ty::Bool {
            self.err(
                "S108",
                cond.span(),
                format!("condition must be `Bool`, found `{}`", t.display()),
            );
        }
    }

    fn check_method(&mut self, ctx: &mut FnCtx, recv: &Name, call: &MethodCall, span: Span) {
        // `join` takes a spawn handle (a local), not a resource.
        if matches!(call, MethodCall::Join) {
            let local = ctx.lookup_local(&recv.ident).filter(|_| !recv.is_qualified());
            match local {
                Some(Ty::Handle) => {}
                Some(_) => self.err(
                    "S107",
                    recv.span,
                    format!(
                        "`.join()` requires a spawn handle, but `{}` is not one",
                        recv.text()
                    ),
                ),
                None => {
                    if resolve_resource(&self.modules, self.module, recv).is_some() {
                        self.err(
                            "S107",
                            recv.span,
                            format!("`.join()` requires a spawn handle, but `{}` is a resource", recv.text()),
                        );
                    } else {
                        self.err(
                            "S101",
                            recv.span,
                            format!("undefined handle `{}`", recv.text()),
                        );
                    }
                }
            }
            return;
        }
        let info = resolve_resource(&self.modules, self.module, recv).cloned();
        let Some(info) = info else {
            self.err("S101", recv.span, format!("undefined name `{}`", recv.text()));
            return;
        };
        match call {
            MethodCall::Send(e) => {
                if info.kind != ResKind::Channel {
                    self.err("S103", span, format!("`send` requires a channel, but `{}` is a {}", recv.text(), kind_name(info.kind)));
                } else {
                    let t = self.expr_ty(ctx, e);
                    self.check_payload(info.ty, t, e.span());
                }
            }
            MethodCall::Recv => {
                if info.kind != ResKind::Channel {
                    self.err("S103", span, format!("`recv` requires a channel, but `{}` is a {}", recv.text(), kind_name(info.kind)));
                }
            }
            MethodCall::Store(e) => {
                if info.kind != ResKind::Atomic {
                    self.err("S103", span, format!("`store` requires an atomic, but `{}` is a {}", recv.text(), kind_name(info.kind)));
                } else {
                    let t = self.expr_ty(ctx, e);
                    self.check_payload(info.ty, t, e.span());
                }
            }
            MethodCall::NotifyOne | MethodCall::NotifyAll => {
                if info.kind != ResKind::Condvar {
                    self.err("S103", span, format!("`notify` requires a condvar, but `{}` is a {}", recv.text(), kind_name(info.kind)));
                }
            }
            MethodCall::Wait => {
                if info.kind != ResKind::Condvar {
                    self.err("S103", span, format!("`wait` requires a condvar, but `{}` is a {}", recv.text(), kind_name(info.kind)));
                    return;
                }
                let bound = info.bound.clone().unwrap_or_default();
                let key = self.resource_key(&Name {
                    module: None,
                    ident: bound,
                    span: recv.span,
                });
                if !ctx.locks.contains(&key) {
                    let bound_text = info.bound.clone().unwrap_or_default();
                    self.errors.push(
                        SkError::error(
                            "S104",
                            span,
                            format!(
                                "`{}.wait()` must be inside `lock {} {{ ... }}` ({} is bound to {})",
                                recv.text(),
                                bound_text,
                                recv.text(),
                                bound_text
                            ),
                        )
                        .with_hint(format!(
                            "wrap the wait loop in `lock {bound_text} {{ while ready == false {{ {}.wait(); }} }}`",
                            recv.text()
                        )),
                    );
                }
            }
            MethodCall::Post | MethodCall::Take => {
                if info.kind != ResKind::Semaphore {
                    self.err("S103", span, format!("`{}` requires a semaphore, but `{}` is a {}", call.name(), recv.text(), kind_name(info.kind)));
                }
            }
            MethodCall::Join => unreachable!("join handled before resource lookup"),
        }
    }

    fn check_call(&mut self, ctx: &mut FnCtx, call: &Call) {
        let info = resolve_fn(&self.modules, self.module, &call.name).cloned();
        let Some(info) = info else {
            if resolve_resource(&self.modules, self.module, &call.name).is_some() {
                self.err(
                    "S103",
                    call.name.span,
                    format!("`{}` is not a function", call.name.text()),
                );
            } else {
                self.err(
                    "S101",
                    call.name.span,
                    format!("undefined function `{}`", call.name.text()),
                );
            }
            return;
        };
        if info.params.len() != call.args.len() {
            self.err(
                "S108",
                call.span,
                format!(
                    "`{}` expects {} argument(s), found {}",
                    call.name.text(),
                    info.params.len(),
                    call.args.len()
                ),
            );
        }
        for (i, arg) in call.args.iter().enumerate() {
            let at = self.expr_ty(ctx, arg);
            if let Some((_, pty)) = info.params.get(i) {
                if at != Ty::Void {
                    self.assignable(Some(*pty), at, arg.span(), "argument");
                }
            }
        }
    }

    fn check_value_name(&mut self, ctx: &mut FnCtx, name: &Name) {
        if !name.is_qualified() && ctx.lookup_local(&name.ident).is_some() {
            return;
        }
        if resolve_resource(&self.modules, self.module, name).is_none() {
            // A plain identifier might still be a module-level function used as
            // a name (not a value); compute footprints accept resources only.
            self.err("S101", name.span, format!("undefined name `{}`", name.text()));
        }
    }

    fn rhs_ty(&mut self, ctx: &mut FnCtx, rhs: &Rhs) -> Ty {
        match rhs {
            Rhs::Expr(e) => self.expr_ty(ctx, e),
            Rhs::Recv { recv } => match resolve_resource(&self.modules, self.module, recv) {
                None => {
                    self.err("S101", recv.span, format!("undefined name `{}`", recv.text()));
                    Ty::Void
                }
                Some(info) if info.kind != ResKind::Channel => {
                    self.err("S103", recv.span, format!("`recv` requires a channel, but `{}` is a {}", recv.text(), kind_name(info.kind)));
                    Ty::Void
                }
                Some(info) => widen(info.ty.unwrap_or(Ty::Int)),
            },
            Rhs::Load { recv } => match resolve_resource(&self.modules, self.module, recv) {
                None => {
                    self.err("S101", recv.span, format!("undefined name `{}`", recv.text()));
                    Ty::Void
                }
                Some(info) if info.kind != ResKind::Atomic => {
                    self.err("S103", recv.span, format!("`load` requires an atomic, but `{}` is a {}", recv.text(), kind_name(info.kind)));
                    Ty::Void
                }
                Some(info) => widen(info.ty.unwrap_or(Ty::Int)),
            },
            Rhs::Cas { recv, expected, desired } => {
                match resolve_resource(&self.modules, self.module, recv) {
                    None => {
                        self.err("S101", recv.span, format!("undefined name `{}`", recv.text()));
                        Ty::Void
                    }
                    Some(info) if info.kind != ResKind::Atomic => {
                        self.err("S103", recv.span, format!("`cas` requires an atomic, but `{}` is a {}", recv.text(), kind_name(info.kind)));
                        Ty::Void
                    }
                    Some(info) => {
                        let base = info.ty.unwrap_or(Ty::Int);
                        let et = self.expr_ty(ctx, expected);
                        let dt = self.expr_ty(ctx, desired);
                        self.check_payload(Some(base), et, expected.span());
                        self.check_payload(Some(base), dt, desired.span());
                        widen(base)
                    }
                }
            }
            Rhs::Spawn { call } => {
                self.check_call(ctx, call);
                Ty::Handle
            }
            Rhs::Call { call } => {
                let before = self.errors.len();
                self.check_call(ctx, call);
                let _ = before;
                resolve_fn(&self.modules, self.module, &call.name)
                    .and_then(|f| f.ret)
                    .unwrap_or(Ty::Void)
            }
        }
    }

    fn check_payload(&mut self, base: Option<Ty>, actual: Ty, span: Span) {
        if actual == Ty::Void {
            return;
        }
        if let Some(base) = base {
            self.assignable(Some(base), actual, span, "payload");
        }
    }

    fn assignable(&mut self, want: Option<Ty>, got: Ty, span: Span, what: &str) {
        let Some(want) = want else { return };
        if got == Ty::Void {
            return;
        }
        let ok = match (want, got) {
            (Ty::Bool, Ty::Bool) => true,
            (Ty::Int, t) if t.is_int() => true,
            (Ty::Bounded(lo, hi), t) if t.is_int() => match t {
                Ty::Bounded(glo, ghi) => glo >= lo && ghi <= hi,
                _ => true,
            },
            (Ty::Bounded(_, _), Ty::Bool) => false,
            (a, b) => a == b,
        };
        if !ok {
            self.err(
                "S108",
                span,
                format!(
                    "{} has type `{}`, but `{}` is required",
                    what,
                    got.display(),
                    want.display()
                ),
            );
        }
    }

    fn expr_ty(&mut self, ctx: &mut FnCtx, e: &Expr) -> Ty {
        match e {
            Expr::IntLit(_, _) => Ty::Int,
            Expr::BoolLit(_, _) => Ty::Bool,
            Expr::Paren(inner, _) => self.expr_ty(ctx, inner),
            Expr::Neg(inner, span) => {
                let t = self.expr_ty(ctx, inner);
                if t != Ty::Void && !t.is_int() {
                    self.err("S108", *span, format!("unary `-` requires `Int`, found `{}`", t.display()));
                }
                Ty::Int
            }
            Expr::BinOp { lhs, rhs, span, .. } => {
                let l = self.expr_ty(ctx, lhs);
                let r = self.expr_ty(ctx, rhs);
                for t in [l, r] {
                    if t != Ty::Void && !t.is_int() {
                        self.err("S108", *span, format!("arithmetic requires `Int`, found `{}`", t.display()));
                    }
                }
                Ty::Int
            }
            Expr::Cmp { op, lhs, rhs, span } => {
                let l = self.expr_ty(ctx, lhs);
                let r = self.expr_ty(ctx, rhs);
                let ordered = matches!(op, CmpOp::Lt | CmpOp::Le | CmpOp::Gt | CmpOp::Ge);
                if l != Ty::Void && r != Ty::Void {
                    let numeric = l.is_int() && r.is_int();
                    let bools = l == Ty::Bool && r == Ty::Bool;
                    if ordered && !numeric {
                        self.err("S108", *span, "ordered comparison requires `Int` operands");
                    } else if !ordered && !numeric && !bools {
                        self.err("S108", *span, format!("cannot compare `{}` and `{}`", l.display(), r.display()));
                    }
                }
                Ty::Bool
            }
            Expr::Name(name) => self.name_value_ty(ctx, name),
        }
    }

    fn name_value_ty(&mut self, ctx: &mut FnCtx, name: &Name) -> Ty {
        if !name.is_qualified() {
            if let Some(t) = ctx.lookup_local(&name.ident) {
                if t == Ty::Handle {
                    self.err("S108", name.span, format!("`{}` is a spawn handle and cannot appear in an expression", name.text()));
                    return Ty::Void;
                }
                return t;
            }
        }
        match resolve_resource(&self.modules, self.module, name) {
            None => {
                self.err("S101", name.span, format!("undefined name `{}`", name.text()));
                Ty::Void
            }
            Some(info) => match info.kind {
                ResKind::Shared | ResKind::Atomic => info.ty.unwrap_or(Ty::Int),
                other => {
                    self.err("S103", name.span, format!("`{}` is a {} and cannot be used as a value", name.text(), kind_name(other)));
                    Ty::Void
                }
            },
        }
    }

    /// Canonical key for a resource name in the current module or qualified.
    fn resource_key(&self, name: &Name) -> String {
        match &name.module {
            Some(m) => format!("{m}::{}", name.ident),
            None => format!("{}::{}", self.modules[self.module].name, name.ident),
        }
    }
}

fn kind_name(k: ResKind) -> &'static str {
    match k {
        ResKind::Mutex => "mutex",
        ResKind::Condvar => "condvar",
        ResKind::Semaphore => "semaphore",
        ResKind::Channel => "channel",
        ResKind::Shared => "shared variable",
        ResKind::Atomic => "atomic",
    }
}

fn rhs_span(rhs: &Rhs) -> Span {
    match rhs {
        Rhs::Expr(e) => e.span(),
        Rhs::Recv { recv } | Rhs::Load { recv } => recv.span,
        Rhs::Cas { recv, .. } => recv.span,
        Rhs::Spawn { call } | Rhs::Call { call } => call.span,
    }
}
