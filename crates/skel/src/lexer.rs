//! Hand-written lexer for the Skeleton DSL (no parser-generator dependencies).

use crate::error::SkError;
use crate::span::{SourceFile, Span};

#[derive(Debug, Clone, PartialEq)]
pub enum TokKind {
    Ident(String),
    Int(i64),
    Str(String),
    /// A reserved word outside the supported subset. Emitted together with an
    /// `S002` error so the parser can recover.
    Reserved(String),

    At,
    Semi,
    LBrace,
    RBrace,
    LParen,
    RParen,
    LBracket,
    RBracket,
    Comma,
    Colon,
    ColonColon,
    Dot,
    DotDotEq,
    Arrow,

    Eq,
    EqEq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    Plus,
    Minus,
    Star,
    Slash,
    Percent,

    Skeleton,
    Module,
    Mutex,
    Condvar,
    For,
    Semaphore,
    Channel,
    Cap,
    Shared,
    GuardedBy,
    Atomic,
    Fn,
    Extern,
    Let,
    Lock,
    Permit,
    Scope,
    Spawn,
    If,
    Else,
    While,
    Loop,
    Break,
    Continue,
    Return,
    Compute,
    Reads,
    Writes,
    True,
    False,
    TypeBool,
    TypeInt,

    Eof,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Token {
    pub kind: TokKind,
    pub span: Span,
}

impl Token {
    pub fn describe(&self) -> String {
        match &self.kind {
            TokKind::Ident(s) => format!("identifier `{s}`"),
            TokKind::Int(n) => format!("integer `{n}`"),
            TokKind::Str(_) => "string literal".to_string(),
            TokKind::Reserved(s) => format!("reserved word `{s}`"),
            TokKind::Eof => "end of file".to_string(),
            other => format!("`{}`", punct_str(other)),
        }
    }
}

fn punct_str(k: &TokKind) -> &'static str {
    match k {
        TokKind::At => "@",
        TokKind::Semi => ";",
        TokKind::LBrace => "{",
        TokKind::RBrace => "}",
        TokKind::LParen => "(",
        TokKind::RParen => ")",
        TokKind::LBracket => "[",
        TokKind::RBracket => "]",
        TokKind::Comma => ",",
        TokKind::Colon => ":",
        TokKind::ColonColon => "::",
        TokKind::Dot => ".",
        TokKind::DotDotEq => "..=",
        TokKind::Arrow => "->",
        TokKind::Eq => "=",
        TokKind::EqEq => "==",
        TokKind::Ne => "!=",
        TokKind::Lt => "<",
        TokKind::Le => "<=",
        TokKind::Gt => ">",
        TokKind::Ge => ">=",
        TokKind::Plus => "+",
        TokKind::Minus => "-",
        TokKind::Star => "*",
        TokKind::Slash => "/",
        TokKind::Percent => "%",
        TokKind::Skeleton => "skeleton",
        TokKind::Module => "module",
        TokKind::Mutex => "mutex",
        TokKind::Condvar => "condvar",
        TokKind::For => "for",
        TokKind::Semaphore => "semaphore",
        TokKind::Channel => "channel",
        TokKind::Cap => "cap",
        TokKind::Shared => "shared",
        TokKind::GuardedBy => "guarded_by",
        TokKind::Atomic => "atomic",
        TokKind::Fn => "fn",
        TokKind::Extern => "extern",
        TokKind::Let => "let",
        TokKind::Lock => "lock",
        TokKind::Permit => "permit",
        TokKind::Scope => "scope",
        TokKind::Spawn => "spawn",
        TokKind::If => "if",
        TokKind::Else => "else",
        TokKind::While => "while",
        TokKind::Loop => "loop",
        TokKind::Break => "break",
        TokKind::Continue => "continue",
        TokKind::Return => "return",
        TokKind::Compute => "compute",
        TokKind::Reads => "reads",
        TokKind::Writes => "writes",
        TokKind::True => "true",
        TokKind::False => "false",
        TokKind::TypeBool => "Bool",
        TokKind::TypeInt => "Int",
        TokKind::Eof => "<eof>",
        _ => "<token>",
    }
}

fn keyword(word: &str) -> Option<TokKind> {
    Some(match word {
        "skeleton" => TokKind::Skeleton,
        "module" => TokKind::Module,
        "mutex" => TokKind::Mutex,
        "condvar" => TokKind::Condvar,
        "for" => TokKind::For,
        "semaphore" => TokKind::Semaphore,
        "channel" => TokKind::Channel,
        "cap" => TokKind::Cap,
        "shared" => TokKind::Shared,
        "guarded_by" => TokKind::GuardedBy,
        "atomic" => TokKind::Atomic,
        "fn" => TokKind::Fn,
        "extern" => TokKind::Extern,
        "let" => TokKind::Let,
        "lock" => TokKind::Lock,
        "permit" => TokKind::Permit,
        "scope" => TokKind::Scope,
        "spawn" => TokKind::Spawn,
        "if" => TokKind::If,
        "else" => TokKind::Else,
        "while" => TokKind::While,
        "loop" => TokKind::Loop,
        "break" => TokKind::Break,
        "continue" => TokKind::Continue,
        "return" => TokKind::Return,
        "compute" => TokKind::Compute,
        "reads" => TokKind::Reads,
        "writes" => TokKind::Writes,
        "true" => TokKind::True,
        "false" => TokKind::False,
        "Bool" => TokKind::TypeBool,
        "Int" => TokKind::TypeInt,
        _ => return None,
    })
}

/// Out-of-subset reserved words and the hint shown with `S002`.
pub fn reserved_hint(word: &str) -> Option<&'static str> {
    Some(match word {
        "rwlock" | "RwLock" | "read_lock" | "write_lock" => {
            "rwlock is not in the subset; use `mutex`"
        }
        "unlock" | "release" | "acquire" | "drop" => {
            "there is no unlock/acquire/drop: leaving a `lock`/`permit` block releases; for a counting semaphore use `s.post()` (V) / `s.take()` (P)"
        }
        "async" | "await" | "select" => "async/await/select are not in the subset",
        "Arc" => "Arc is unnecessary: resources are shared by name",
        "Float" | "String" => "only `Bool` and `Int` (and `Int[lo..=hi]`) are in the subset",
        "struct" | "enum" => "struct/enum are not in the subset; declare resources instead",
        "match" => "match is not in the subset; use nested `if`",
        "thread" => "thread is not in the subset; use `scope { spawn f(); }`",
        "unsafe" => "unsafe is not in the subset",
        _ => return None,
    })
}

struct Lexer<'a> {
    file: &'a SourceFile,
    bytes: &'a [u8],
    pos: usize,
    line: u32,
    col: u32,
    errors: Vec<SkError>,
}

pub fn lex(file: &SourceFile) -> (Vec<Token>, Vec<SkError>) {
    let mut lx = Lexer {
        file,
        bytes: file.text.as_bytes(),
        pos: 0,
        line: 1,
        col: 1,
        errors: Vec::new(),
    };
    let mut tokens = Vec::new();
    loop {
        lx.skip_trivia();
        if lx.pos >= lx.bytes.len() {
            tokens.push(lx.token(TokKind::Eof, lx.pos, lx.line, lx.col));
            break;
        }
        if let Some(t) = lx.next_token() {
            tokens.push(t);
        }
    }
    (tokens, lx.errors)
}

impl<'a> Lexer<'a> {
    fn peek_byte(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn peek2(&self) -> Option<u8> {
        self.bytes.get(self.pos + 1).copied()
    }

    fn token(&self, kind: TokKind, start: usize, line: u32, col: u32) -> Token {
        Token {
            kind,
            span: Span::new(start as u32, self.pos as u32, line, col, self.line, self.col),
        }
    }

    /// Advance one byte, updating line/col. Only call on ASCII bytes or
    /// multi-byte UTF-8 continuation bytes (which do not change the column
    /// count meaningfully for our ASCII DSL; we count bytes).
    fn bump(&mut self) {
        if let Some(b) = self.peek_byte() {
            self.pos += 1;
            if b == b'\n' {
                self.line += 1;
                self.col = 1;
            } else {
                self.col += 1;
            }
        }
    }

    fn skip_trivia(&mut self) {
        loop {
            match self.peek_byte() {
                Some(b' ') | Some(b'\t') | Some(b'\r') | Some(b'\n') => self.bump(),
                Some(b'/') if self.peek2() == Some(b'/') => {
                    while let Some(b) = self.peek_byte() {
                        if b == b'\n' {
                            break;
                        }
                        self.bump();
                    }
                }
                _ => break,
            }
        }
    }

    fn next_token(&mut self) -> Option<Token> {
        let start = self.pos;
        let line = self.line;
        let col = self.col;
        let b = self.peek_byte()?;
        match b {
            b'@' => {
                self.bump();
                Some(self.token(TokKind::At, start, line, col))
            }
            b';' => {
                self.bump();
                Some(self.token(TokKind::Semi, start, line, col))
            }
            b'{' => {
                self.bump();
                Some(self.token(TokKind::LBrace, start, line, col))
            }
            b'}' => {
                self.bump();
                Some(self.token(TokKind::RBrace, start, line, col))
            }
            b'(' => {
                self.bump();
                Some(self.token(TokKind::LParen, start, line, col))
            }
            b')' => {
                self.bump();
                Some(self.token(TokKind::RParen, start, line, col))
            }
            b'[' => {
                self.bump();
                Some(self.token(TokKind::LBracket, start, line, col))
            }
            b']' => {
                self.bump();
                Some(self.token(TokKind::RBracket, start, line, col))
            }
            b',' => {
                self.bump();
                Some(self.token(TokKind::Comma, start, line, col))
            }
            b':' => {
                self.bump();
                if self.peek_byte() == Some(b':') {
                    self.bump();
                    Some(self.token(TokKind::ColonColon, start, line, col))
                } else {
                    Some(self.token(TokKind::Colon, start, line, col))
                }
            }
            b'.' => {
                self.bump();
                if self.peek_byte() == Some(b'.')
                    && self.bytes.get(self.pos + 1) == Some(&b'=')
                {
                    self.bump();
                    self.bump();
                    Some(self.token(TokKind::DotDotEq, start, line, col))
                } else {
                    Some(self.token(TokKind::Dot, start, line, col))
                }
            }
            b'-' => {
                self.bump();
                if self.peek_byte() == Some(b'>') {
                    self.bump();
                    Some(self.token(TokKind::Arrow, start, line, col))
                } else {
                    Some(self.token(TokKind::Minus, start, line, col))
                }
            }
            b'=' => {
                self.bump();
                if self.peek_byte() == Some(b'=') {
                    self.bump();
                    Some(self.token(TokKind::EqEq, start, line, col))
                } else {
                    Some(self.token(TokKind::Eq, start, line, col))
                }
            }
            b'!' => {
                self.bump();
                if self.peek_byte() == Some(b'=') {
                    self.bump();
                    Some(self.token(TokKind::Ne, start, line, col))
                } else {
                    self.errors.push(SkError::error(
                        "S001",
                        Span::new(start as u32, self.pos as u32, line, col, self.line, self.col),
                        "unexpected character `!`",
                    ).with_hint("the DSL has no `!`; use a single comparison such as `x == false`"));
                    None
                }
            }
            b'<' => {
                self.bump();
                if self.peek_byte() == Some(b'=') {
                    self.bump();
                    Some(self.token(TokKind::Le, start, line, col))
                } else {
                    Some(self.token(TokKind::Lt, start, line, col))
                }
            }
            b'>' => {
                self.bump();
                if self.peek_byte() == Some(b'=') {
                    self.bump();
                    Some(self.token(TokKind::Ge, start, line, col))
                } else {
                    Some(self.token(TokKind::Gt, start, line, col))
                }
            }
            b'+' => {
                self.bump();
                Some(self.token(TokKind::Plus, start, line, col))
            }
            b'*' => {
                self.bump();
                Some(self.token(TokKind::Star, start, line, col))
            }
            b'/' => {
                self.bump();
                Some(self.token(TokKind::Slash, start, line, col))
            }
            b'%' => {
                self.bump();
                Some(self.token(TokKind::Percent, start, line, col))
            }
            b'"' => self.lex_string(start, line, col),
            b'0'..=b'9' => self.lex_int(start, line, col),
            b'A'..=b'Z' | b'a'..=b'z' | b'_' => self.lex_ident(start, line, col),
            other => {
                self.bump();
                self.errors.push(SkError::error(
                    "S001",
                    Span::new(start as u32, self.pos as u32, line, col, self.line, self.col),
                    format!("unexpected character `{}`", other as char),
                ));
                None
            }
        }
    }

    fn lex_string(&mut self, start: usize, line: u32, col: u32) -> Option<Token> {
        self.bump(); // opening quote
        let mut value = String::new();
        loop {
            match self.peek_byte() {
                None | Some(b'\n') => {
                    self.errors.push(SkError::error(
                        "S001",
                        Span::new(start as u32, self.pos as u32, line, col, self.line, self.col),
                        "unterminated string literal",
                    ));
                    return None;
                }
                Some(b'"') => {
                    self.bump();
                    return Some(self.token(TokKind::Str(value), start, line, col));
                }
                Some(b'\\') => {
                    self.bump();
                    match self.peek_byte() {
                        Some(b'"') => {
                            value.push('"');
                            self.bump();
                        }
                        Some(b'\\') => {
                            value.push('\\');
                            self.bump();
                        }
                        Some(b'n') => {
                            value.push('\n');
                            self.bump();
                        }
                        other => {
                            self.bump();
                            self.errors.push(SkError::error(
                                "S001",
                                Span::new(
                                    start as u32,
                                    self.pos as u32,
                                    line,
                                    col,
                                    self.line,
                                    self.col,
                                ),
                                format!(
                                    "unknown string escape `\\{}`",
                                    other.map(|b| b as char).unwrap_or('?')
                                ),
                            ).with_hint("supported escapes: \\\" \\\\ \\n"));
                            return None;
                        }
                    }
                }
                Some(_) => {
                    let ch_start = self.pos;
                    // Consume one UTF-8 scalar (bytes).
                    let len = utf8_len(self.bytes[self.pos]);
                    let mut n = 0;
                    while n < len && self.peek_byte().is_some() {
                        self.bump();
                        n += 1;
                    }
                    if let Some(s) = self.file.text.get(ch_start..self.pos) {
                        value.push_str(s);
                    }
                }
            }
        }
    }

    fn lex_int(&mut self, start: usize, line: u32, col: u32) -> Option<Token> {
        while matches!(self.peek_byte(), Some(b'0'..=b'9')) {
            self.bump();
        }
        let text = &self.file.text[start..self.pos];
        match text.parse::<i64>() {
            Ok(n) => Some(self.token(TokKind::Int(n), start, line, col)),
            Err(_) => {
                self.errors.push(SkError::error(
                    "S001",
                    Span::new(start as u32, self.pos as u32, line, col, self.line, self.col),
                    format!("integer literal `{text}` does not fit in i64"),
                ));
                None
            }
        }
    }

    fn lex_ident(&mut self, start: usize, line: u32, col: u32) -> Option<Token> {
        while matches!(
            self.peek_byte(),
            Some(b'A'..=b'Z') | Some(b'a'..=b'z') | Some(b'0'..=b'9') | Some(b'_')
        ) {
            self.bump();
        }
        let word = self.file.text[start..self.pos].to_string();
        if let Some(kind) = keyword(&word) {
            return Some(self.token(kind, start, line, col));
        }
        if let Some(hint) = reserved_hint(&word) {
            let span = Span::new(start as u32, self.pos as u32, line, col, self.line, self.col);
            self.errors.push(
                SkError::error(
                    "S002",
                    span,
                    format!("`{word}` is outside the Skeleton DSL subset"),
                )
                .with_hint(hint),
            );
            return Some(self.token(TokKind::Reserved(word), start, line, col));
        }
        Some(self.token(TokKind::Ident(word), start, line, col))
    }
}

fn utf8_len(first: u8) -> usize {
    if first < 0x80 {
        1
    } else if first >> 5 == 0b110 {
        2
    } else if first >> 4 == 0b1110 {
        3
    } else if first >> 3 == 0b11110 {
        4
    } else {
        1
    }
}
