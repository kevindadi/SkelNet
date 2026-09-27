//! Front-end diagnostics: stable `S###` codes, rustc-style rendering, `--json`.

use serde::Serialize;

use crate::span::{SourceFile, Span};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Error,
    Warning,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Origin {
    Skel,
    Concir,
}

#[derive(Debug, Clone, Serialize)]
pub struct SkError {
    pub code: String,
    pub severity: Severity,
    pub message: String,
    /// Rendered as a nested object in JSON; `null` when there is no span.
    pub span: Option<SpanJson>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
    pub origin: Origin,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub concir_code: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct SpanJson {
    pub start: u32,
    pub end: u32,
    pub line: u32,
    pub col: u32,
    pub end_line: u32,
    pub end_col: u32,
}

impl From<Span> for SpanJson {
    fn from(s: Span) -> Self {
        SpanJson {
            start: s.start,
            end: s.end,
            line: s.line,
            col: s.col,
            end_line: s.end_line,
            end_col: s.end_col,
        }
    }
}

impl SkError {
    pub fn error(code: &str, span: Span, message: impl Into<String>) -> Self {
        SkError {
            code: code.to_string(),
            severity: Severity::Error,
            message: message.into(),
            span: Some(span.into()),
            hint: None,
            origin: Origin::Skel,
            concir_code: None,
        }
    }

    pub fn error_at(
        code: &str,
        span: Option<Span>,
        message: impl Into<String>,
        hint: Option<String>,
    ) -> Self {
        SkError {
            code: code.to_string(),
            severity: Severity::Error,
            message: message.into(),
            span: span.map(Into::into),
            hint,
            origin: Origin::Skel,
            concir_code: None,
        }
    }

    pub fn warning(
        code: &str,
        span: Option<Span>,
        message: impl Into<String>,
        hint: Option<String>,
    ) -> Self {
        SkError {
            code: code.to_string(),
            severity: Severity::Warning,
            message: message.into(),
            span: span.map(Into::into),
            hint,
            origin: Origin::Skel,
            concir_code: None,
        }
    }

    pub fn with_hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }

    pub fn is_error(&self) -> bool {
        self.severity == Severity::Error
    }
}

/// Render one diagnostic in rustc style:
///
/// ```text
/// error[S104]: `cv.wait()` must be inside `lock m { ... }` (cv is bound to m)
///   --> task.skel:14:9
///    |
/// 14 |         cv.wait();
///    |         ^^^^^^^^^
///    = hint: wrap the wait loop in `lock m { while ready == false { cv.wait(); } }`
/// ```
pub fn render(file: &SourceFile, err: &SkError) -> String {
    let sev = match err.severity {
        Severity::Error => "error",
        Severity::Warning => "warning",
    };
    let mut out = format!("{sev}[{}]: {}\n", err.code, err.message);
    let Some(span) = err.span else {
        if let Some(hint) = &err.hint {
            out.push_str(&format!("  = hint: {hint}\n"));
        }
        return out;
    };
    out.push_str(&format!(
        "  --> {}:{}:{}\n",
        file.name, span.line, span.col
    ));
    let line = file.line(span.line);
    let gutter = span.line.to_string();
    let pad = " ".repeat(gutter.len());
    out.push_str(&format!("{pad} |\n"));
    out.push_str(&format!("{gutter} | {line}\n"));
    let caret_len = if span.end_line == span.line {
        (span.end_col.max(span.col + 1) - span.col) as usize
    } else {
        (line.len().saturating_sub(span.col.saturating_sub(1) as usize)).max(1)
    };
    out.push_str(&format!(
        "{pad} | {}{}\n",
        " ".repeat(span.col.saturating_sub(1) as usize),
        "^".repeat(caret_len)
    ));
    if let Some(hint) = &err.hint {
        out.push_str(&format!("{pad} = hint: {hint}\n"));
    }
    out
}

/// Render all diagnostics (errors first in input order, then warnings).
pub fn render_all(file: &SourceFile, errors: &[SkError]) -> String {
    let mut out = String::new();
    for e in errors.iter().filter(|e| e.is_error()) {
        out.push_str(&render(file, e));
    }
    for w in errors.iter().filter(|e| !e.is_error()) {
        out.push_str(&render(file, w));
    }
    out
}
