//! Skeleton DSL abstract syntax tree. Every node carries a [`Span`].

use crate::span::Span;

#[derive(Debug, Clone, serde::Serialize)]
pub struct File {
    /// The `skeleton <name>;` header name.
    pub name: String,
    pub modules: Vec<Module>,
    /// True when no `module` block was written (single implicit `main` module).
    pub implicit_main: bool,
    pub span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Module {
    pub name: String,
    pub items: Vec<Item>,
    pub span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Item {
    pub tags: Vec<Tag>,
    pub kind: ItemKind,
    pub span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum ItemKind {
    Resource(ResourceDecl),
    Fn(FnDecl),
    ExternFn(ExternFn),
}

/// A `@R<n>` requirement tag.
#[derive(Debug, Clone, serde::Serialize)]
pub struct Tag {
    /// The raw identifier after `@` (e.g. `R3`).
    pub raw: String,
    /// The parsed number, when `raw` matches `R[0-9]+`.
    pub n: Option<u64>,
    pub span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct ResourceDecl {
    pub kind: ResourceKind,
    pub name: String,
    /// Span of the whole declaration.
    pub span: Span,
    /// Span of just the declared name.
    pub name_span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum ResourceKind {
    Mutex,
    Condvar { bound: Name },
    Semaphore { count: i64 },
    Channel { ty: Type, cap: i64 },
    Shared {
        ty: Type,
        init: Literal,
        guarded_by: Option<Name>,
    },
    Atomic { ty: Type, init: Literal },
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct FnDecl {
    pub name: String,
    pub name_span: Span,
    pub params: Vec<Param>,
    pub ret: Option<Type>,
    pub body: Block,
    pub span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct ExternFn {
    pub name: String,
    pub name_span: Span,
    pub span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Param {
    pub name: String,
    pub ty: Type,
    pub span: Span,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub enum Type {
    Bool,
    Int,
    BoundedInt { lo: i64, hi: i64 },
}

impl Type {
    pub fn display(&self) -> String {
        match self {
            Type::Bool => "Bool".into(),
            Type::Int => "Int".into(),
            Type::BoundedInt { lo, hi } => format!("Int[{lo}..={hi}]"),
        }
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum Literal {
    Bool(bool),
    Int(i64),
}

impl Literal {
    pub fn display(&self) -> String {
        match self {
            Literal::Bool(b) => b.to_string(),
            Literal::Int(n) => n.to_string(),
        }
    }

    pub fn ty(&self) -> Type {
        match self {
            Literal::Bool(_) => Type::Bool,
            Literal::Int(_) => Type::Int,
        }
    }
}

/// A possibly module-qualified name (`m` or `mod::m`).
#[derive(Debug, Clone, serde::Serialize)]
pub struct Name {
    pub module: Option<String>,
    pub ident: String,
    pub span: Span,
}

impl Name {
    pub fn text(&self) -> String {
        match &self.module {
            Some(m) => format!("{m}::{}", self.ident),
            None => self.ident.clone(),
        }
    }

    pub fn is_qualified(&self) -> bool {
        self.module.is_some()
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Block {
    pub stmts: Vec<Stmt>,
    /// Span of the whole `{ ... }` including braces.
    pub span: Span,
    /// Span of just the closing brace (for `lock_exit` mapping).
    pub close_span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Stmt {
    pub tags: Vec<Tag>,
    pub core: StmtCore,
    pub span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum StmtCore {
    Lock { name: Name, body: Block },
    Permit { name: Name, body: Block },
    Scope { spawns: Vec<SpawnStmt> },
    If { cond: Expr, then: Block, els: Option<Else> },
    While { cond: Expr, body: Block },
    Loop { body: Block },
    Break,
    Continue,
    Return(Option<Expr>),
    Compute {
        desc: String,
        desc_span: Span,
        reads: Vec<Name>,
        writes: Vec<Name>,
    },
    Let {
        name: String,
        name_span: Span,
        ty: Option<Type>,
        rhs: Rhs,
        discard: bool,
    },
    Assign { name: Name, expr: Expr },
    Method { recv: Name, call: MethodCall },
    Call { call: Call },
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SpawnStmt {
    pub name: Name,
    pub span: Span,
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum Else {
    Block(Block),
    If(Box<Stmt>),
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum Rhs {
    Expr(Expr),
    Recv { recv: Name },
    Load { recv: Name },
    Cas { recv: Name, expected: Expr, desired: Expr },
    Spawn { call: Call },
    Call { call: Call },
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum MethodCall {
    Send(Expr),
    Recv,
    Store(Expr),
    NotifyOne,
    NotifyAll,
    Wait,
    Post,
    Take,
    Join,
}

impl MethodCall {
    pub fn name(&self) -> &'static str {
        match self {
            MethodCall::Send(_) => "send",
            MethodCall::Recv => "recv",
            MethodCall::Store(_) => "store",
            MethodCall::NotifyOne => "notify_one",
            MethodCall::NotifyAll => "notify_all",
            MethodCall::Wait => "wait",
            MethodCall::Post => "post",
            MethodCall::Take => "take",
            MethodCall::Join => "join",
        }
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Call {
    pub name: Name,
    pub args: Vec<Expr>,
    pub span: Span,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
}

impl BinOp {
    pub fn symbol(&self) -> &'static str {
        match self {
            BinOp::Add => "+",
            BinOp::Sub => "-",
            BinOp::Mul => "*",
            BinOp::Div => "/",
            BinOp::Mod => "%",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum CmpOp {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl CmpOp {
    pub fn symbol(&self) -> &'static str {
        match self {
            CmpOp::Eq => "==",
            CmpOp::Ne => "!=",
            CmpOp::Lt => "<",
            CmpOp::Le => "<=",
            CmpOp::Gt => ">",
            CmpOp::Ge => ">=",
        }
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub enum Expr {
    IntLit(i64, Span),
    BoolLit(bool, Span),
    Name(Name),
    Neg(Box<Expr>, Span),
    BinOp { op: BinOp, lhs: Box<Expr>, rhs: Box<Expr>, span: Span },
    Cmp { op: CmpOp, lhs: Box<Expr>, rhs: Box<Expr>, span: Span },
    Paren(Box<Expr>, Span),
}

impl Expr {
    pub fn span(&self) -> Span {
        match self {
            Expr::IntLit(_, s)
            | Expr::BoolLit(_, s)
            | Expr::Neg(_, s)
            | Expr::BinOp { span: s, .. }
            | Expr::Cmp { span: s, .. }
            | Expr::Paren(_, s) => *s,
            Expr::Name(n) => n.span,
        }
    }
}
