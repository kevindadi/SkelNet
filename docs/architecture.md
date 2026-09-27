# Architecture

```
LLM ──writes──▶ .skel ──skelnet check/verify──▶ ConcIR ──▶ Petri ──▶ outcome
                    ▲                               │
                    └──────── remapped feedback ◀───┘
                    │
                    └── accepted skeleton ──▶ LLM ──▶ Rust ──▶ oracle.py
```

## Crates

- `crates/concir` — the trimmed ConcIR: AST, validation, interpreter, Petri-net
  exploration, codegen, conformance, monitoring. Bins `concir-backend`,
  `concir-instrument`, `bind-check`. It is the single source of semantics.
- `crates/skel` — the Skeleton DSL front-end:
  - `lexer.rs` + `parser.rs` → `ast.rs` (hand-written; no parser generator),
  - `check.rs` → `S###` diagnostics,
  - `lower.rs` → ConcIR JSON + `SourceMap`,
  - `feedback.rs` → ConcIR → DSL remapping,
  - `fmt.rs` (canonical printer), `codegen.rs` (annotated Rust skeleton),
    `adhere.rs` (human-review adherence report),
  - bin `skelnet`.
- `runtime/concir_sync` — std-only counting semaphore (`acquire`/`Permit`,
  `post`/`take`) used by generated Rust.

## Data flow

1. The LLM writes a `.skel` skeleton (`prompts/skel_generation_v1.md`).
2. `skelnet check` parses, runs front-end checks, lowers, and runs ConcIR
   `validate` + `support`. Diagnostics are remapped to DSL spans.
3. `skelnet verify` additionally explores the lowered program against the
   frozen contract and renders remapped counterexamples.
4. The revision loop feeds remapped feedback back to the LLM (contract hidden).
5. On PASS, the accepted skeleton + requirements produce Rust
   (`prompts/rust_from_skel_v1.md`), scored by `python/skelnet/oracle.py`.

## Python orchestration

`python/skelnet` has three arms (`pipeline.py`): `G0` (direct Rust), `SKEL`
(skeleton-guided), `CIR` (ConcIR ablation). All arms share one oracle. The
`run`/`eval`/`report` CLI writes one directory per run (`MANIFEST.json`,
`cells/`, `SUMMARY.json`, `REPORT.md`). `adhere` is a manual tool and is not
referenced by any arm or metric.

## Trust boundary

- ConcIR is the only semantics; the DSL adds no meaning.
- `.env` and keys never enter git; the Python audit log stores prompt/response
  hashes, not secrets.
- Verification is exhaustive over the bounded model; `UNKNOWN` is reported as
  such and never as safety.
