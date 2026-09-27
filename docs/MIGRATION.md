# Migration record

This repository is a curated extraction from two read-only source repositories.
History (experiments, notes, paper drafts, repair tooling) stays in the originals;
this file records exactly what was brought over, what was deleted, and why.

## Source repositories

| Source | Path | Commit SHA |
| --- | --- | --- |
| ConcPlanVerify | `/Users/kevin/local-repos/ConcPlanVerify` | `8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f` |
| ConcIR | `/Users/kevin/local-repos/ConcIR` | `a35dc867d6327c772d48bd7c0473a6606fcc467a` |

Both sources are read-only for this migration: they are never modified, committed
to, or tagged.

## P0: workspace skeleton

Created:

- `.gitignore` (ignores `.env`, `.env.*`, except `!.env.example`)
- `.env` copied from `ConcPlanVerify/.env` (ignored, never tracked, never printed)
- `.env.example` (key names only, no values)
- `rust-toolchain.toml` (nightly-2026-09-04 + miri + rust-src, from ConcIR)

Details of subsequent phases are appended below as they are completed.

## P1: ConcIR + runtime

### Brought in

`crates/concir` (from ConcIR `a35dc86`, tracked files only via `git archive`):

- `src/ast.rs, expr.rs, env.rs, fqn.rs, hash.rs, schema.rs, typedef.rs,
  diagnostic.rs, codegen.rs, conform.rs, instrument.rs, monitor.rs`
- `src/validate/*`, `src/sem/*`, `src/interp/*`, `src/petri/*`, `src/explore/*`,
  `src/export/dot`
- `src/bin/concir-backend.rs`, `src/bin/instrument.rs`, `src/bin/bind_check.rs`
- `tests/` (all semantic tests, see trims below), `examples/*.json`, `build.rs`
- ConcIR `doc/` moved to `docs/concir/` (backend-design, backend-usage, ebnf,
  error_codes, syntax/*)

`runtime/concir_sync` (from ConcPlanVerify `8bf9fa49b`): `Semaphore`/`Permit`
RAII API, plus new `Semaphore::post` (V) and `Semaphore::take` (P), with a unit
test. `take` is `acquire().forget()`; `forget` was added to `Permit`. The old
`Semaphore::release` is **not** restored.

### Deleted (non-core repair experiment line)

- `crates/concir/src/repair/` — `mod.rs, benchmark.rs, candidates.rs,
  external.rs, patch.rs, search.rs`.
- `crates/concir/src/src_mutate.rs`
- `crates/concir/src/main.rs` — validate-only duplicate binary; `concir-backend
  check` covers it. Cargo.toml now sets `autobins = false` and declares
  `concir-backend`, `concir-instrument`, `bind_check` explicitly.
- `crates/concir/examples/pilot_tool.rs` — depended on `concir::repair`.
- CLI subcommands `repair`, `replay`, `repair-context`, `evaluate-patch`, `bench`
  (and the `--src-mutate` mode of `concir-instrument`).
- Tests removed whole: `tests/repair_e2e.rs`, `tests/repair_search.rs`,
  `tests/src_mutate.rs`, `tests/benchmark.rs`, `tests/cli.rs` (only covered the
  removed repair subcommands / artifact replay).
- Nested `crates/concir/.gitignore` and `crates/concir/rust-toolchain.toml`
  dropped: the workspace root `.gitignore` and `rust-toolchain.toml` apply.
- `Cargo.lock` regenerated for the workspace (same dependency set).

### Mixed tests trimmed (semantic cases kept)

- `tests/round2_regressions.rs`: removed the file-candidate repair provider
  imports, the `repair_with` helper, and 5 repair-permission/rebinding tests;
  13 semantic tests remain.
- `tests/round3_regressions.rs`: removed repair imports; split
  `b1_repair_must_reject_deleting_the_last_write` into the semantic half
  (`b1_query_only_after_deletion_fails_in_both_engines`); removed the two
  `b7_*` patch-scope tests. 13 semantic tests remain.
- `tests/diagnostics_hint.rs` kept: it uses only `Diagnostic.repair_hints`
  (a heuristic string field on the explore diagnostic), not the repair module.

### Note

- `bind_check` keeps its underscore name (not `bind-check`) so
  `CARGO_BIN_EXE_bind_check` and the documented bin name stay as specified;
  Cargo emits a cosmetic kebab-case warning.
- Inert test fixtures under `tests/repro_*` that were only used by the deleted
  repair tests are retained as data (they do not compile into the test binary).
  They can be pruned later; none are referenced by any remaining test.
- `benchmarks/BASELINE.json` regenerated in P1 by running the trimmed
  `concir-backend explore <gold> contract.json petri` over all 27 Appendix A
  tasks; outcome / complete / per-property outcomes match Appendix A exactly.

## P2: `crates/skel` (new crate)

New code, not migrated: `crates/skel/` with `span.rs`, `lexer.rs`, `ast.rs`,
`parser.rs`, `fmt.rs`, `check.rs`, `error.rs`, `lib.rs`, `main.rs` (bin
`skelnet`) and `tests/frontend.rs`. The parser is hand-written (lexer +
recursive descent); no parser-generator dependency was added.

## P3: lowering + feedback (new code)

Added `crates/skel/src/lower.rs` and `crates/skel/src/feedback.rs`; extended the
`skelnet` CLI (`lower`, `check`, `verify`). Not migrated.

## P4: benchmarks (migrated + new)

Brought in from `ConcPlanVerify/benchmarks/families` (commit `8bf9fa49b`) into
`benchmarks/tasks/<family>/<task>/`: `contract.json`, `spec.md`,
`ground_truth.json`, `requirements.json` + `REQUIREMENTS.md`,
`gold.cir.json` (from `fixed.cir.json`/`correct.cir.json`), and
`rust/fixed.rs`. Not brought in: `buggy.cir.json`, `repair_input/`,
`repair_task.json`, `rust/buggy.rs`.

New: 25 `gold.skel` files, `benchmarks/MANIFEST.json` (sha256 + source path),
`benchmarks/DEVIATIONS.json`.

## P5: Python orchestration + prompts

Brought in from `ConcPlanVerify/python/cir_workflow` (commit `8bf9fa49b`),
verbatim with import fixes: `env.py`, `models.py`, `json_utils.py`, `llm.py`,
`transport.py`, `providers.py`, `direct.py`, `opencode_go.py`.

Reimplemented compactly (dependencies on removed/network modules): `audit.py`,
`channels.py`, `backend.py`, `prompts.py`, `pipeline.py`, `oracle.py`,
`evidence.py`, `cli.py`, `__main__.py`.

Not migrated: `arms.py`, `experiments_v2.py`, `results.py`, `gen_results.py`,
`flash_smoke.py`, `normalize.py`, `extract.py`, `patch_repair.py`,
`offline_workflow.py`, `mutation_protocol.py`, `detection.py`, `structural.py`,
`contract_strength.py`, `scale.py`, `live.py`, `cursor_harness.py`, all
`scripts/`, and the ConcIR repair-client paths in `concir_client.py`.

Prompts: new `skel_generation_v1.md`, `skel_feedback_v1.md`,
`rust_from_skel_v1.md`; migrated `concir_generation_v4.md`,
`rust_from_cir_v2.md`, `rust_generation_v1.md`, `examples/*`.

## P6: codegen + adhere (new code)

Added `crates/skel/src/codegen.rs` and `crates/skel/src/adhere.rs`, plus the
`skelnet codegen` / `skelnet adhere` CLI commands and insta snapshots under
`crates/skel/tests/snapshots/`. Not migrated.

## P7 (pending)
