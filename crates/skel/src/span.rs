//! Byte + line/column spans for every token and AST node.

use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, serde::Serialize)]
pub struct Span {
    pub start: u32,
    pub end: u32,
    pub line: u32,
    pub col: u32,
    pub end_line: u32,
    pub end_col: u32,
}

impl Span {
    pub fn new(
        start: u32,
        end: u32,
        line: u32,
        col: u32,
        end_line: u32,
        end_col: u32,
    ) -> Self {
        Span {
            start,
            end,
            line,
            col,
            end_line,
            end_col,
        }
    }

    /// The zero-width span at the start of `self` (used for anchors).
    pub fn point(&self) -> Span {
        Span {
            start: self.start,
            end: self.start,
            line: self.line,
            col: self.col,
            end_line: self.line,
            end_col: self.col,
        }
    }

    /// Smallest span covering both.
    pub fn to(self, other: Span) -> Span {
        Span {
            start: self.start.min(other.start),
            end: self.end.max(other.end),
            line: if self.start <= other.start {
                self.line
            } else {
                other.line
            },
            col: if self.start <= other.start {
                self.col
            } else {
                other.col
            },
            end_line: if self.end >= other.end {
                self.end_line
            } else {
                other.end_line
            },
            end_col: if self.end >= other.end {
                self.end_col
            } else {
                other.end_col
            },
        }
    }
}

impl fmt::Display for Span {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}:{}", self.line, self.col)
    }
}

/// A parsed source file: its display name and full text (for error rendering).
#[derive(Debug, Clone)]
pub struct SourceFile {
    pub name: String,
    pub text: String,
}

impl SourceFile {
    pub fn new(name: impl Into<String>, text: impl Into<String>) -> Self {
        SourceFile {
            name: name.into(),
            text: text.into(),
        }
    }

    /// 1-based line contents (without the trailing newline).
    pub fn line(&self, n: u32) -> &str {
        self.text.lines().nth(n.saturating_sub(1) as usize).unwrap_or("")
    }
}
