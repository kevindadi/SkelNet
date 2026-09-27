# SkelNet

Skeleton-guided concurrent program synthesis and verification.

SkelNet introduces a small, Rust-flavoured **Skeleton DSL** as a formal front-end
for the ConcIR concurrent intermediate representation (vendored under
`crates/concir`). An LLM writes a `.skel` skeleton, SkelNet mechanically lowers
it to ConcIR, verifies it against a frozen contract, and maps
diagnostics/counterexamples back to skeleton lines so the LLM can revise the
skeleton. A verified skeleton then guides Rust generation.

- DSL reference: [`docs/dsl.md`](docs/dsl.md)
- Lowering rules + source map: [`docs/lowering.md`](docs/lowering.md)
- Verification feedback / disclosure policy: [`docs/feedback.md`](docs/feedback.md)
- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Experiments / run layout: [`docs/experiments.md`](docs/experiments.md)
- Error codes: [`docs/error_codes.md`](docs/error_codes.md)
- Migration provenance: [`docs/MIGRATION.md`](docs/MIGRATION.md)
- Refactor log: [`docs/REFACTOR_REPORT.md`](docs/REFACTOR_REPORT.md)

## Skeleton DSL

```skel
skeleton abba_2lock;
mutex a;
mutex b;
@R1
fn main() { scope { spawn t1(); spawn t2(); } }
@R2 @R4
fn t1() { lock a { lock b { compute "update both records"; } } }
@R3 @R4
fn t2() { lock a { lock b { compute "update both records"; } } }
```

`skelnet check` / `verify` map ConcIR diagnostics and counterexamples back to
DSL lines; `skelnet lower` emits ConcIR + a source map; `skelnet codegen`
emits an annotated Rust skeleton; `skelnet adhere` reports skeleton adherence
for human review.

## Layout

```
crates/concir/         ConcIR (trimmed) — library + concir-backend, concir-instrument, bind-check
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
# First build downloads crates.io dependencies and therefore needs network.
cargo build --workspace

# Once the registry cache is populated, builds and tests run offline:
cargo build --workspace --offline
cargo test  --workspace --offline

python -m pytest python/tests
```

## Secret hygiene

`.env` is ignored and never committed. Copy `.env.example` to `.env` and fill in
values locally.
