//! Hand-written recursive-descent parser with `;`/`}` error recovery.
//!
//! Reports at most [`MAX_ERRORS`] syntax errors (`S003`) plus any `S002` lexer
//! errors carried on the token stream.

use crate::ast::*;
use crate::error::SkError;
use crate::lexer::{TokKind, Token};
use crate::span::Span;

pub const MAX_ERRORS: usize = 20;

struct Parser<'a> {
    toks: &'a [Token],
    pos: usize,
    errors: Vec<SkError>,
}

impl<'a> Parser<'a> {
    fn cur(&self) -> &'a Token {
        &self.toks[self.pos.min(self.toks.len() - 1)]
    }

    fn peek(&self) -> &TokKind {
        &self.cur().kind
    }

    fn at_eof(&self) -> bool {
        matches!(self.peek(), TokKind::Eof)
    }

    fn advance(&mut self) -> &'a Token {
        let t = self.cur();
        if self.pos < self.toks.len() - 1 {
            self.pos += 1;
        }
        t
    }

    fn at(&self, k: &TokKind) -> bool {
        self.peek() == k
    }

    fn eat(&mut self, k: &TokKind) -> bool {
        if self.at(k) {
            self.advance();
            true
        } else {
            false
        }
    }

    fn error(&mut self, code: &str, span: Span, msg: impl Into<String>) {
        self.error_hint(code, span, msg, None);
    }

    fn error_hint(
        &mut self,
        code: &str,
        span: Span,
        msg: impl Into<String>,
        hint: Option<String>,
    ) {
        if self.errors.len() >= MAX_ERRORS {
            return;
        }
        self.errors
            .push(SkError::error_at(code, Some(span), msg, hint));
    }

    /// Expect `k`, recording `S003` (without consuming) when absent.
    fn expect(&mut self, k: TokKind, what: &str) -> bool {
        if self.at(&k) {
            self.advance();
            true
        } else {
            let span = self.cur().span;
            let found = self.cur().describe();
            self.error(
                "S003",
                span,
                format!("expected {what}, found {found}"),
            );
            false
        }
    }

    fn synchronize_stmt(&mut self) {
        // Skip to just after a `;`, or stop before a `}` / EOF.
        while !self.at_eof() {
            match self.peek() {
                TokKind::Semi => {
                    self.advance();
                    return;
                }
                TokKind::RBrace => return,
                _ => {
                    self.advance();
                }
            }
        }
    }

    fn skip_reserved(&mut self) -> bool {
        if let TokKind::Reserved(_) = self.peek() {
            self.advance();
            true
        } else {
            false
        }
    }
}

pub fn parse(name: String, tokens: &[Token]) -> (File, Vec<SkError>) {
    let mut p = Parser {
        toks: tokens,
        pos: 0,
        errors: Vec::new(),
    };
    let file = p.parse_file(name);
    (file, p.errors)
}

impl<'a> Parser<'a> {
    fn parse_file(&mut self, _name: String) -> File {
        let start = self.cur().span;
        self.expect(TokKind::Skeleton, "`skeleton`");
        let file_name = match self.peek().clone() {
            TokKind::Ident(n) => {
                self.advance();
                n
            }
            _ => {
                let span = self.cur().span;
                self.error("S003", span, "expected the skeleton name");
                "<error>".to_string()
            }
        };
        self.expect(TokKind::Semi, "`;` after the skeleton name");

        let mut modules: Vec<Module> = Vec::new();
        let implicit = !self.at(&TokKind::Module);
        if implicit {
            let items = self.parse_items_until(&[TokKind::Eof]);
            modules.push(Module {
                name: "main".to_string(),
                items,
                span: start.to(self.cur().span),
            });
        } else {
            while !self.at_eof() {
                if self.at(&TokKind::Module) {
                    modules.push(self.parse_module());
                } else {
                    // Mixed form: the grammar allows either items or modules.
                    let span = self.cur().span;
                    self.error(
                        "S003",
                        span,
                        "top-level items may not appear once `module` blocks are used",
                    );
                    let item = self.parse_item();
                    let m = modules.iter_mut().find(|m| m.name == "main");
                    match m {
                        Some(m) => m.items.push(item),
                        None => modules.push(Module {
                            name: "main".to_string(),
                            items: vec![item],
                            span,
                        }),
                    }
                }
            }
        }
        let end = self.cur().span;
        File {
            name: file_name,
            modules,
            implicit_main: implicit,
            span: start.to(end),
        }
    }

    fn parse_module(&mut self) -> Module {
        let start = self.cur().span;
        self.expect(TokKind::Module, "`module`");
        let name = match self.peek().clone() {
            TokKind::Ident(n) => {
                self.advance();
                n
            }
            _ => {
                let span = self.cur().span;
                self.error("S003", span, "expected a module name");
                "<error>".to_string()
            }
        };
        self.expect(TokKind::LBrace, "`{`");
        let items = self.parse_items_until(&[TokKind::RBrace, TokKind::Eof]);
        let end = self.cur().span;
        self.expect(TokKind::RBrace, "`}`");
        Module {
            name,
            items,
            span: start.to(end),
        }
    }

    fn parse_items_until(&mut self, stop: &[TokKind]) -> Vec<Item> {
        let mut items = Vec::new();
        loop {
            if self.at_eof() || stop.iter().any(|k| self.at(k)) {
                break;
            }
            if self.skip_reserved() {
                continue;
            }
            let before = self.pos;
            let item = self.parse_item();
            items.push(item);
            if self.pos == before {
                // No progress: force one token to avoid an infinite loop.
                self.advance();
            }
        }
        items
    }

    fn parse_tags(&mut self) -> Vec<Tag> {
        let mut tags = Vec::new();
        while let TokKind::At = self.peek() {
            let at = self.advance().span;
            match self.peek().clone() {
                TokKind::Ident(raw) => {
                    let span = self.advance().span;
                    let n = parse_tag_number(&raw);
                    tags.push(Tag {
                        raw,
                        n,
                        span: at.to(span),
                    });
                }
                _ => {
                    let span = self.cur().span;
                    self.error("S003", span, "expected a tag name after `@` (e.g. `@R3`)");
                    break;
                }
            }
        }
        tags
    }

    fn parse_item(&mut self) -> Item {
        let tags = self.parse_tags();
        let start = tags.first().map(|t| t.span).unwrap_or(self.cur().span);
        let kind = match self.peek() {
            TokKind::Mutex => ItemKind::Resource(self.parse_resource_impl(ResourceKeyword::Mutex)),
            TokKind::Condvar => {
                ItemKind::Resource(self.parse_resource_impl(ResourceKeyword::Condvar))
            }
            TokKind::Semaphore => {
                ItemKind::Resource(self.parse_resource_impl(ResourceKeyword::Semaphore))
            }
            TokKind::Channel => {
                ItemKind::Resource(self.parse_resource_impl(ResourceKeyword::Channel))
            }
            TokKind::Shared => ItemKind::Resource(self.parse_resource_impl(ResourceKeyword::Shared)),
            TokKind::Atomic => ItemKind::Resource(self.parse_resource_impl(ResourceKeyword::Atomic)),
            TokKind::Fn => ItemKind::Fn(self.parse_fn()),
            TokKind::Extern => ItemKind::ExternFn(self.parse_extern()),
            _ => {
                let span = self.cur().span;
                let found = self.cur().describe();
                self.error(
                    "S003",
                    span,
                    format!("expected an item (resource, `fn`, or `extern fn`), found {found}"),
                );
                self.synchronize_item();
                ItemKind::ExternFn(ExternFn {
                    name: "<error>".into(),
                    name_span: span,
                    span,
                })
            }
        };
        let end = self.prev_span();
        Item {
            tags,
            kind,
            span: start.to(end),
        }
    }

    fn synchronize_item(&mut self) {
        while !self.at_eof() {
            match self.peek() {
                TokKind::RBrace | TokKind::Module | TokKind::Fn | TokKind::Mutex
                | TokKind::Condvar | TokKind::Semaphore | TokKind::Channel
                | TokKind::Shared | TokKind::Atomic | TokKind::Extern => return,
                TokKind::Semi => {
                    self.advance();
                    return;
                }
                _ => {
                    self.advance();
                }
            }
        }
    }

    fn prev_span(&self) -> Span {
        let i = self.pos.saturating_sub(1);
        self.toks[i.min(self.toks.len() - 1)].span
    }

    fn parse_resource_impl(&mut self, keyword: ResourceKeyword) -> ResourceDecl {
        let start = self.advance().span; // consume the resource keyword
        let (name, name_span) = match self.peek().clone() {
            TokKind::Ident(n) => {
                let s = self.advance().span;
                (n, s)
            }
            _ => {
                let s = self.cur().span;
                self.error("S003", s, "expected a resource name");
                ("<error>".to_string(), s)
            }
        };
        let kind = match keyword {
            ResourceKeyword::Mutex => {
                self.expect(TokKind::Semi, "`;`");
                ResourceKind::Mutex
            }
            ResourceKeyword::Condvar => {
                self.expect(TokKind::For, "`for`");
                let bound = self.parse_name();
                self.expect(TokKind::Semi, "`;`");
                ResourceKind::Condvar { bound }
            }
            ResourceKeyword::Semaphore => {
                self.expect(TokKind::Eq, "`=`");
                let count = self.parse_int("the initial permit count");
                self.expect(TokKind::Semi, "`;`");
                ResourceKind::Semaphore { count }
            }
            ResourceKeyword::Channel => {
                self.expect(TokKind::Colon, "`:`");
                let ty = self.parse_type();
                self.expect(TokKind::Cap, "`cap`");
                let cap = self.parse_int("the channel capacity");
                self.expect(TokKind::Semi, "`;`");
                ResourceKind::Channel { ty, cap }
            }
            ResourceKeyword::Shared => {
                self.expect(TokKind::Colon, "`:`");
                let ty = self.parse_type();
                self.expect(TokKind::Eq, "`=`");
                let init = self.parse_literal();
                let guarded_by = if self.eat(&TokKind::GuardedBy) {
                    Some(self.parse_name())
                } else {
                    None
                };
                self.expect(TokKind::Semi, "`;`");
                ResourceKind::Shared {
                    ty,
                    init,
                    guarded_by,
                }
            }
            ResourceKeyword::Atomic => {
                self.expect(TokKind::Colon, "`:`");
                let ty = self.parse_type();
                self.expect(TokKind::Eq, "`=`");
                let init = self.parse_literal();
                self.expect(TokKind::Semi, "`;`");
                ResourceKind::Atomic { ty, init }
            }
        };
        let end = self.prev_span();
        ResourceDecl {
            kind,
            name,
            span: start.to(end),
            name_span,
        }
    }

    fn parse_int(&mut self, what: &str) -> i64 {
        let neg = self.eat(&TokKind::Minus);
        match self.peek().clone() {
            TokKind::Int(n) => {
                self.advance();
                if neg {
                    -n
                } else {
                    n
                }
            }
            _ => {
                let span = self.cur().span;
                self.error("S003", span, format!("expected an integer for {what}"));
                0
            }
        }
    }

    fn parse_literal(&mut self) -> Literal {
        match self.peek().clone() {
            TokKind::True => {
                self.advance();
                Literal::Bool(true)
            }
            TokKind::False => {
                self.advance();
                Literal::Bool(false)
            }
            TokKind::Int(n) => {
                self.advance();
                Literal::Int(n)
            }
            TokKind::Minus => {
                self.advance();
                let n = self.parse_int("a literal");
                Literal::Int(n)
            }
            _ => {
                let span = self.cur().span;
                self.error("S003", span, "expected a literal (`true`, `false`, or an integer)");
                Literal::Int(0)
            }
        }
    }

    fn parse_type(&mut self) -> Type {
        match self.peek().clone() {
            TokKind::TypeBool => {
                self.advance();
                Type::Bool
            }
            TokKind::TypeInt => {
                self.advance();
                if self.eat(&TokKind::LBracket) {
                    let lo = self.parse_int("the lower bound");
                    self.expect(TokKind::DotDotEq, "`..=`");
                    let hi = self.parse_int("the upper bound");
                    self.expect(TokKind::RBracket, "`]`");
                    Type::BoundedInt { lo, hi }
                } else {
                    Type::Int
                }
            }
            _ => {
                let span = self.cur().span;
                let found = self.cur().describe();
                self.error(
                    "S003",
                    span,
                    format!("expected a type (`Bool`, `Int`, or `Int[lo..=hi]`), found {found}"),
                );
                Type::Int
            }
        }
    }

    fn parse_name(&mut self) -> Name {
        let (module, ident, span) = self.parse_name_parts();
        Name {
            module,
            ident,
            span,
        }
    }

    fn parse_name_parts(&mut self) -> (Option<String>, String, Span) {
        let first_span = self.cur().span;
        let first = match self.peek().clone() {
            TokKind::Ident(n) => {
                self.advance();
                n
            }
            _ => {
                let span = self.cur().span;
                let found = self.cur().describe();
                self.error("S003", span, format!("expected a name, found {found}"));
                return (None, "<error>".to_string(), span);
            }
        };
        if self.eat(&TokKind::ColonColon) {
            match self.peek().clone() {
                TokKind::Ident(second) => {
                    let end = self.advance().span;
                    (Some(first), second, first_span.to(end))
                }
                _ => {
                    let span = self.cur().span;
                    self.error("S003", span, "expected a name after `::`");
                    (None, first, first_span)
                }
            }
        } else {
            (None, first, first_span)
        }
    }

    fn parse_fn(&mut self) -> FnDecl {
        let start = self.advance().span; // `fn`
        let (name, name_span) = match self.peek().clone() {
            TokKind::Ident(n) => {
                let s = self.advance().span;
                (n, s)
            }
            _ => {
                let s = self.cur().span;
                self.error("S003", s, "expected a function name");
                ("<error>".to_string(), s)
            }
        };
        self.expect(TokKind::LParen, "`(`");
        let mut params = Vec::new();
        if !self.at(&TokKind::RParen) {
            loop {
                let pstart = self.cur().span;
                let (pname, _) = match self.peek().clone() {
                    TokKind::Ident(n) => {
                        let s = self.advance().span;
                        (n, s)
                    }
                    _ => {
                        let s = self.cur().span;
                        self.error("S003", s, "expected a parameter name");
                        ("<error>".to_string(), s)
                    }
                };
                self.expect(TokKind::Colon, "`:`");
                let ty = self.parse_type();
                let pend = self.prev_span();
                params.push(Param {
                    name: pname,
                    ty,
                    span: pstart.to(pend),
                });
                if !self.eat(&TokKind::Comma) {
                    break;
                }
                if self.at(&TokKind::RParen) {
                    break;
                }
            }
        }
        self.expect(TokKind::RParen, "`)`");
        let ret = if self.eat(&TokKind::Arrow) {
            Some(self.parse_type())
        } else {
            None
        };
        let body = self.parse_block();
        let end = self.prev_span();
        FnDecl {
            name,
            name_span,
            params,
            ret,
            body,
            span: start.to(end),
        }
    }

    fn parse_extern(&mut self) -> ExternFn {
        let start = self.advance().span; // `extern`
        self.expect(TokKind::Fn, "`fn`");
        let (name, name_span) = match self.peek().clone() {
            TokKind::Ident(n) => {
                let s = self.advance().span;
                (n, s)
            }
            _ => {
                let s = self.cur().span;
                self.error("S003", s, "expected a function name");
                ("<error>".to_string(), s)
            }
        };
        self.expect(TokKind::LParen, "`(`");
        self.expect(TokKind::RParen, "`)`");
        self.expect(TokKind::Semi, "`;`");
        let end = self.prev_span();
        ExternFn {
            name,
            name_span,
            span: start.to(end),
        }
    }

    fn parse_block(&mut self) -> Block {
        let open = self.cur().span;
        self.expect(TokKind::LBrace, "`{`");
        let mut stmts = Vec::new();
        loop {
            if self.at(&TokKind::RBrace) || self.at_eof() {
                break;
            }
            if self.skip_reserved() {
                continue;
            }
            let before = self.pos;
            let stmt = self.parse_stmt();
            stmts.push(stmt);
            if self.pos == before {
                self.advance();
            }
        }
        let close = self.cur().span;
        self.expect(TokKind::RBrace, "`}`");
        Block {
            stmts,
            span: open.to(close),
            close_span: close,
        }
    }

    fn parse_stmt(&mut self) -> Stmt {
        let tags = self.parse_tags();
        let start = tags.first().map(|t| t.span).unwrap_or(self.cur().span);
        let core = self.parse_stmt_core();
        let end = self.prev_span();
        Stmt {
            tags,
            core,
            span: start.to(end),
        }
    }

    fn parse_stmt_core(&mut self) -> StmtCore {
        match self.peek().clone() {
            TokKind::Lock => {
                self.advance();
                let name = self.parse_name();
                let body = self.parse_block();
                StmtCore::Lock { name, body }
            }
            TokKind::Permit => {
                self.advance();
                let name = self.parse_name();
                let body = self.parse_block();
                StmtCore::Permit { name, body }
            }
            TokKind::Scope => {
                self.advance();
                let mut spawns = Vec::new();
                if !self.expect(TokKind::LBrace, "`{`") {
                    self.synchronize_stmt();
                    return StmtCore::Scope { spawns };
                }
                while !self.at(&TokKind::RBrace) && !self.at_eof() {
                    if self.skip_reserved() {
                        continue;
                    }
                    let sstart = self.cur().span;
                    if self.at(&TokKind::Spawn) {
                        self.advance();
                        let name = self.parse_name();
                        self.expect(TokKind::LParen, "`(`");
                        self.expect(TokKind::RParen, "`)`");
                        let send = self.prev_span();
                        self.expect(TokKind::Semi, "`;`");
                        spawns.push(SpawnStmt {
                            name,
                            span: sstart.to(send),
                        });
                    } else {
                        let span = self.cur().span;
                        let found = self.cur().describe();
                        self.error(
                            "S003",
                            span,
                            format!("expected `spawn f();` in a `scope` block, found {found}"),
                        );
                        self.synchronize_stmt();
                        if self.at(&TokKind::RBrace) {
                            break;
                        }
                    }
                }
                self.expect(TokKind::RBrace, "`}`");
                StmtCore::Scope { spawns }
            }
            TokKind::If => {
                self.advance();
                let cond = self.parse_expr();
                let then = self.parse_block();
                let els = if self.eat(&TokKind::Else) {
                    if self.at(&TokKind::If) {
                        Some(Else::If(Box::new(self.parse_stmt())))
                    } else {
                        Some(Else::Block(self.parse_block()))
                    }
                } else {
                    None
                };
                StmtCore::If { cond, then, els }
            }
            TokKind::While => {
                self.advance();
                let cond = self.parse_expr();
                let body = self.parse_block();
                StmtCore::While { cond, body }
            }
            TokKind::Loop => {
                self.advance();
                let body = self.parse_block();
                StmtCore::Loop { body }
            }
            TokKind::Break => {
                self.advance();
                self.expect(TokKind::Semi, "`;`");
                StmtCore::Break
            }
            TokKind::Continue => {
                self.advance();
                self.expect(TokKind::Semi, "`;`");
                StmtCore::Continue
            }
            TokKind::Return => {
                self.advance();
                let value = if self.at(&TokKind::Semi) {
                    None
                } else {
                    Some(self.parse_expr())
                };
                self.expect(TokKind::Semi, "`;`");
                StmtCore::Return(value)
            }
            TokKind::Compute => {
                self.advance();
                let (desc, desc_span) = match self.peek().clone() {
                    TokKind::Str(s) => {
                        let sp = self.advance().span;
                        (s, sp)
                    }
                    _ => {
                        let sp = self.cur().span;
                        self.error("S003", sp, "expected a string description after `compute`");
                        (String::new(), sp)
                    }
                };
                let reads = if self.eat(&TokKind::Reads) {
                    self.expect(TokKind::LParen, "`(`");
                    let names = self.parse_name_list();
                    self.expect(TokKind::RParen, "`)`");
                    names
                } else {
                    Vec::new()
                };
                let writes = if self.eat(&TokKind::Writes) {
                    self.expect(TokKind::LParen, "`(`");
                    let names = self.parse_name_list();
                    self.expect(TokKind::RParen, "`)`");
                    names
                } else {
                    Vec::new()
                };
                self.expect(TokKind::Semi, "`;`");
                StmtCore::Compute {
                    desc,
                    desc_span,
                    reads,
                    writes,
                }
            }
            TokKind::Let => {
                self.advance();
                let (name, name_span) = match self.peek().clone() {
                    TokKind::Ident(n) => {
                        let s = self.advance().span;
                        (n, s)
                    }
                    _ => {
                        let s = self.cur().span;
                        self.error("S003", s, "expected a local name after `let`");
                        ("<error>".to_string(), s)
                    }
                };
                let ty = if self.eat(&TokKind::Colon) {
                    Some(self.parse_type())
                } else {
                    None
                };
                self.expect(TokKind::Eq, "`=`");
                let rhs = self.parse_rhs();
                self.expect(TokKind::Semi, "`;`");
                let discard = name == "_";
                StmtCore::Let {
                    name,
                    name_span,
                    ty,
                    rhs,
                    discard,
                }
            }
            TokKind::Ident(_) | TokKind::Reserved(_) => {
                let name = self.parse_name();
                match self.peek() {
                    TokKind::Eq => {
                        self.advance();
                        let expr = self.parse_expr();
                        self.expect(TokKind::Semi, "`;`");
                        StmtCore::Assign { name, expr }
                    }
                    TokKind::Dot => {
                        self.advance();
                        let call = self.parse_method_call();
                        self.expect(TokKind::Semi, "`;`");
                        StmtCore::Method { recv: name, call }
                    }
                    TokKind::LParen => {
                        let call = self.parse_call_after_name(name);
                        self.expect(TokKind::Semi, "`;`");
                        StmtCore::Call { call }
                    }
                    _ => {
                        let span = self.cur().span;
                        let found = self.cur().describe();
                        self.error(
                            "S003",
                            span,
                            format!("expected `=`, `.`, or `(`, found {found}"),
                        );
                        self.synchronize_stmt();
                        StmtCore::Call {
                            call: Call {
                                name,
                                args: Vec::new(),
                                span,
                            },
                        }
                    }
                }
            }
            _ => {
                let span = self.cur().span;
                let found = self.cur().describe();
                self.error("S003", span, format!("expected a statement, found {found}"));
                self.synchronize_stmt();
                StmtCore::Return(None)
            }
        }
    }

    fn parse_name_list(&mut self) -> Vec<Name> {
        let mut names = Vec::new();
        if self.at(&TokKind::RParen) {
            return names;
        }
        loop {
            names.push(self.parse_name());
            if !self.eat(&TokKind::Comma) {
                break;
            }
        }
        names
    }

    fn parse_rhs(&mut self) -> Rhs {
        if self.at(&TokKind::Spawn) {
            self.advance();
            let call = self.parse_call();
            return Rhs::Spawn { call };
        }
        let save = self.pos;
        if matches!(self.peek(), TokKind::Ident(_)) {
            let name = self.parse_name();
            if self.eat(&TokKind::Dot) {
                if let TokKind::Ident(m) = self.peek().clone() {
                    match m.as_str() {
                        "recv" => {
                            self.advance();
                            self.expect(TokKind::LParen, "`(`");
                            self.expect(TokKind::RParen, "`)`");
                            return Rhs::Recv { recv: name };
                        }
                        "load" => {
                            self.advance();
                            self.expect(TokKind::LParen, "`(`");
                            self.expect(TokKind::RParen, "`)`");
                            return Rhs::Load { recv: name };
                        }
                        "cas" => {
                            self.advance();
                            self.expect(TokKind::LParen, "`(`");
                            let expected = self.parse_expr();
                            self.expect(TokKind::Comma, "`,`");
                            let desired = self.parse_expr();
                            self.expect(TokKind::RParen, "`)`");
                            return Rhs::Cas {
                                recv: name,
                                expected,
                                desired,
                            };
                        }
                        _ => {}
                    }
                }
            }
            if self.at(&TokKind::LParen) {
                let call = self.parse_call_after_name(name);
                return Rhs::Call { call };
            }
            self.pos = save;
        }
        Rhs::Expr(self.parse_expr())
    }

    fn parse_method_call(&mut self) -> MethodCall {
        let m = match self.peek().clone() {
            TokKind::Ident(m) => {
                self.advance();
                m
            }
            _ => {
                let span = self.cur().span;
                self.error("S003", span, "expected a method name after `.`");
                return MethodCall::Recv;
            }
        };
        match m.as_str() {
            "send" => {
                self.expect(TokKind::LParen, "`(`");
                let e = self.parse_expr();
                self.expect(TokKind::RParen, "`)`");
                MethodCall::Send(e)
            }
            "store" => {
                self.expect(TokKind::LParen, "`(`");
                let e = self.parse_expr();
                self.expect(TokKind::RParen, "`)`");
                MethodCall::Store(e)
            }
            "recv" => {
                self.expect(TokKind::LParen, "`(`");
                self.expect(TokKind::RParen, "`)`");
                MethodCall::Recv
            }
            "notify_one" => {
                self.expect(TokKind::LParen, "`(`");
                self.expect(TokKind::RParen, "`)`");
                MethodCall::NotifyOne
            }
            "notify_all" => {
                self.expect(TokKind::LParen, "`(`");
                self.expect(TokKind::RParen, "`)`");
                MethodCall::NotifyAll
            }
            "wait" => {
                self.expect(TokKind::LParen, "`(`");
                self.expect(TokKind::RParen, "`)`");
                MethodCall::Wait
            }
            "post" => {
                self.expect(TokKind::LParen, "`(`");
                self.expect(TokKind::RParen, "`)`");
                MethodCall::Post
            }
            "take" => {
                self.expect(TokKind::LParen, "`(`");
                self.expect(TokKind::RParen, "`)`");
                MethodCall::Take
            }
            "join" => {
                self.expect(TokKind::LParen, "`(`");
                self.expect(TokKind::RParen, "`)`");
                MethodCall::Join
            }
            other => {
                let span = self.cur().span;
                self.error(
                    "S003",
                    span,
                    format!(
                        "unknown method `{other}`; expected send/recv/store/notify_one/notify_all/wait/post/take/join"
                    ),
                );
                MethodCall::Recv
            }
        }
    }

    fn parse_call(&mut self) -> Call {
        let name = self.parse_name();
        self.parse_call_after_name(name)
    }

    fn parse_call_after_name(&mut self, name: Name) -> Call {
        let start = name.span;
        self.expect(TokKind::LParen, "`(`");
        let mut args = Vec::new();
        if !self.at(&TokKind::RParen) {
            loop {
                args.push(self.parse_expr());
                if !self.eat(&TokKind::Comma) {
                    break;
                }
            }
        }
        let end = self.cur().span;
        self.expect(TokKind::RParen, "`)`");
        Call {
            name,
            args,
            span: start.to(end),
        }
    }

    fn parse_expr(&mut self) -> Expr {
        let lhs = self.parse_add();
        let op = match self.peek() {
            TokKind::EqEq => Some(CmpOp::Eq),
            TokKind::Ne => Some(CmpOp::Ne),
            TokKind::Lt => Some(CmpOp::Lt),
            TokKind::Le => Some(CmpOp::Le),
            TokKind::Gt => Some(CmpOp::Gt),
            TokKind::Ge => Some(CmpOp::Ge),
            _ => None,
        };
        if let Some(op) = op {
            self.advance();
            let rhs = self.parse_add();
            let span = lhs.span().to(rhs.span());
            Expr::Cmp {
                op,
                lhs: Box::new(lhs),
                rhs: Box::new(rhs),
                span,
            }
        } else {
            lhs
        }
    }

    fn parse_add(&mut self) -> Expr {
        let mut lhs = self.parse_mul();
        loop {
            let op = match self.peek() {
                TokKind::Plus => BinOp::Add,
                TokKind::Minus => BinOp::Sub,
                _ => break,
            };
            self.advance();
            let rhs = self.parse_mul();
            let span = lhs.span().to(rhs.span());
            lhs = Expr::BinOp {
                op,
                lhs: Box::new(lhs),
                rhs: Box::new(rhs),
                span,
            };
        }
        lhs
    }

    fn parse_mul(&mut self) -> Expr {
        let mut lhs = self.parse_unary();
        loop {
            let op = match self.peek() {
                TokKind::Star => BinOp::Mul,
                TokKind::Slash => BinOp::Div,
                TokKind::Percent => BinOp::Mod,
                _ => break,
            };
            self.advance();
            let rhs = self.parse_unary();
            let span = lhs.span().to(rhs.span());
            lhs = Expr::BinOp {
                op,
                lhs: Box::new(lhs),
                rhs: Box::new(rhs),
                span,
            };
        }
        lhs
    }

    fn parse_unary(&mut self) -> Expr {
        if self.at(&TokKind::Minus) {
            let start = self.advance().span;
            let inner = self.parse_unary();
            let span = start.to(inner.span());
            Expr::Neg(Box::new(inner), span)
        } else {
            self.parse_atom()
        }
    }

    fn parse_atom(&mut self) -> Expr {
        match self.peek().clone() {
            TokKind::Int(n) => {
                let s = self.advance().span;
                Expr::IntLit(n, s)
            }
            TokKind::True => {
                let s = self.advance().span;
                Expr::BoolLit(true, s)
            }
            TokKind::False => {
                let s = self.advance().span;
                Expr::BoolLit(false, s)
            }
            TokKind::Ident(_) => Expr::Name(self.parse_name()),
            TokKind::LParen => {
                let open = self.advance().span;
                let inner = self.parse_expr();
                let close = self.cur().span;
                self.expect(TokKind::RParen, "`)`");
                Expr::Paren(Box::new(inner), open.to(close))
            }
            _ => {
                let span = self.cur().span;
                let found = self.cur().describe();
                self.error("S003", span, format!("expected an expression, found {found}"));
                Expr::IntLit(0, span)
            }
        }
    }
}

/// Distinguishes resource kinds at the dispatch site (the parser consumes the
/// keyword before calling `parse_resource_impl`).
#[derive(Debug, Clone, Copy)]
enum ResourceKeyword {
    Mutex,
    Condvar,
    Semaphore,
    Channel,
    Shared,
    Atomic,
}

fn parse_tag_number(raw: &str) -> Option<u64> {
    let rest = raw.strip_prefix('R')?;
    if rest.is_empty() || !rest.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    rest.parse::<u64>().ok()
}
