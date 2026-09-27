//! Skeleton DSL front-end: source -> tokens -> AST -> canonical form -> checks.

pub mod ast;
pub mod check;
pub mod error;
pub mod feedback;
pub mod fmt;
pub mod lexer;
pub mod lower;
pub mod parser;
pub mod span;

use error::SkError;
use span::SourceFile;

/// Parse a source file into an AST plus all lexer/parser diagnostics.
pub fn parse_source(name: &str, text: &str) -> (ast::File, Vec<SkError>) {
    let file = SourceFile::new(name, text);
    let (tokens, mut errors) = lexer::lex(&file);
    let (ast, parse_errors) = parser::parse(file.name.clone(), &tokens);
    errors.extend(parse_errors);
    (ast, errors)
}
