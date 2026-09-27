# SkelNet

Skeleton-guided concurrent program synthesis and verification.

SkelNet introduces a small, Rust-flavoured **Skeleton DSL** as a formal front-end
for the [ConcIR](../ConcIR) concurrent intermediate representation. An LLM writes
a `.skel` skeleton, SkelNet mechanically lowers it to ConcIR, verifies it against
a frozen contract, and maps diagnostics/counterexamples back to skeleton lines so
the LLM can revise the skeleton. A verified skeleton then guides Rust generation.

- DSL reference: [`docs/dsl.md`](docs/dsl.md)
- Lowering rules + source map: [`docs/lowering.md`](docs/lowering.md)
- Verification feedback / disclosure policy: [`docs/feedback.md`](docs/feedback.md)
- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Migration provenance: [`docs/MIGRATION.md`](docs/MIGRATION.md)
- Refactor log: [`docs/REFACTOR_REPORT.md`](docs/REFACTOR_REPORT.md)

## Layout

```
crates/concir/         ConcIR (trimmed) — library + concir-backend, concir-instrument, bind_check
crates/skel/           Skeleton DSL front-end — library + skelnet
runtime/concir_sync/   Runtime sync primitives used by generated Rust
python/skelnet/        Python orchestration (LLM arms, oracle, reporting)
prompts/               Prompt templates
benchmarks/            Tasks + BASELINE.json
experiments/           Run outputs
docs/                  Design + reference docs
```

## Build

```
cargo build --workspace --offline
cargo test  --workspace --offline
python -m pytest python/tests
```

## Secret hygiene

`.env` is ignored and never committed. Copy `.env.example` to `.env` and fill in
values locally.
