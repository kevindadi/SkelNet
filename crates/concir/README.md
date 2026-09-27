# ConcIR (vendored)

Static validator and verification backend for **ConcIR** (Concurrency
Intermediate Representation) — a statement-level, verification-oriented
concurrency IR. Reads a ConcIR JSON file, runs the validation passes, and emits
a structured diagnostic report; the backend also explores the program as a
colored Petri net for deadlock/safety/preservation properties.

This copy is the trimmed version vendored into SkelNet. The repair experiment
line (`repair`, `replay`, `bench`, `repair-context`, `evaluate-patch`,
`src_mutate`) and the validate-only `cir` binary were removed in the migration;
see [`docs/MIGRATION.md`](../../docs/MIGRATION.md). ConcIR is language-neutral:
a program is a set of modules; names are ConcIR FQNs (`module::entity`).
Function bodies are a flattened CFG; non-control ops fall through to the next
statement, while `goto` / `branch` / `switch` / `return` / `select` transfer
control.

## Quick start

From the workspace root:

```bash
cargo build --workspace
./target/debug/concir-backend check   crates/concir/examples/producer_consumer.json
./target/debug/concir-backend support crates/concir/examples/complex_rwlock.json
./target/debug/concir-backend explore crates/concir/examples/producer_consumer.json
./target/debug/concir-backend explore crates/concir/examples/lockorder_bug.json crates/concir/examples/lockorder_contract.json
./target/debug/concir-backend codegen crates/concir/examples/producer_consumer.json --out /tmp/out
```

`check` prints a JSON `ValidationReport` (`{"valid": true, "diagnostics": []}`)
and exits non-zero when invalid. `explore` prints a `VerificationReport` with an
`outcome` of `PASS` / `FAIL` / `UNKNOWN` / `INVALID` / `UNSUPPORTED`.

## Bins

| bin | purpose |
| --- | --- |
| `concir-backend` | `check`, `explore`, `run`, `support`, `schema`, `codegen`, `conform`, `monitor` |
| `concir-instrument` | rewrite a std-only Rust program onto instrumented wrappers (`--wrappers`) |
| `bind-check` | structural binding check between instrumented resources and a CIR program |

Exit codes: `0` PASS, `1` FAIL, `2` usage, `3` UNKNOWN, `4` INVALID,
`5` UNSUPPORTED.

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/concir/backend-design.md`](../../docs/concir/backend-design.md) | Operational semantics, Petri nets, contracts, diagnostics |
| [`docs/concir/backend-usage.md`](../../docs/concir/backend-usage.md) | Commands, support matrix, model boundaries |
| [`docs/concir/ebnf.md`](../../docs/concir/ebnf.md) | ISO EBNF abstract syntax |
| [`docs/concir/error_codes.md`](../../docs/concir/error_codes.md) | Validation error reference (E0xx–E9xx) |
| [`docs/concir/syntax/`](../../docs/concir/syntax/README.md) | Prose grammar, split by top-level construct |

## Project structure

```
src/
  lib.rs               Module declarations
  ast.rs               IR types (Program, Module, Stmt, Op)
  env.rs               Per-function name environment
  expr.rs              Expression parser and type checker
  fqn.rs               Identifier and FQN rules
  typedef.rs           Module-level named types
  diagnostic.rs        Diagnostic types (Diagnostic, ValidationReport)
  validate/            Validation passes (E0xx–E9xx)
  sem/                 Semantic lowering + reference interpreter
  petri/               Colored Petri-net translation and executor
  explore/             Finite-state exploration + contract checking
  codegen.rs           Deterministic Rust project generation
  conform.rs           Runtime-trace conformance
  monitor.rs           Contract monitoring from traces
  export/dot.rs        Graphviz DOT export
  bin/                 concir-backend, instrument, bind_check
examples/              ConcIR example programs
tests/                 Validation, differential, regression, and snapshot tests
```

The authoritative ConcIR documentation lives under [`docs/concir/`](../../docs/concir/).
