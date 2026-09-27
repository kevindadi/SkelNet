# Refactor report

Running log for the SkelNet refactor. One section per phase (P0–P7). Each section
records: what changed, the test command(s) and result summary, and deviations /
open questions.

---

## P0 — workspace skeleton, secrets hygiene

### Changes

- Added `.gitignore` ignoring `.env`, `.env.*` (negating `!.env.example`), plus
  Python caches, Rust `target/`, insta pending snapshots, experiment raw layer,
  transient logs, and OS/editor files.
- Copied `ConcPlanVerify/.env` → `SkelNet/.env` (never printed, never tracked).
- Added `.env.example` containing only key names:
  `DEEPSEEK_API_KEY`, `OPENCODE_API_KEY`, `CURSOR_API_KEY`, `DASHSCOPE_API_KEY`.
- Added `rust-toolchain.toml` (`nightly-2026-09-04`, `miri`, `rust-src`), matching ConcIR.
- Added `docs/MIGRATION.md` initial draft with source commit SHAs.
- Added `README.md` skeleton.

### §1.2 checks (outputs)

Command: `git check-ignore -v .env`

```
.gitignore:2:.env	.env
```

Command: `git ls-files | grep -E '(^|/)\.env$'`

```
(no output)
```

Command: `git diff --cached | grep -nE '(sk-|key-)[A-Za-z0-9_-]{16,}'`

```
(no output)
```

### Deviations / Open questions

- None at this phase.

---

## P1 — ConcIR migration + trim, runtime `concir_sync`

### Changes

- Extracted ConcIR `a35dc86` tracked files into `crates/concir`; moved ConcIR
  `doc/` → `docs/concir/`.
- Removed the repair experiment line: `src/repair/`, `src/src_mutate.rs`,
  `src/main.rs`, `examples/pilot_tool.rs`; CLI subcommands `repair, replay,
  repair-context, evaluate-patch, bench`; `concir-instrument --src-mutate`.
- Trimmed mixed regression tests (kept semantic cases); deleted repair-only
  test files. See `docs/MIGRATION.md` P1 for the full list.
- Added workspace `Cargo.toml`, explicit bins, regenerated `Cargo.lock`.
- `runtime/concir_sync`: added `Semaphore::post` (V) and `Semaphore::take` (P,
  = `acquire().forget()`), plus `Permit::forget`; kept `Semaphore`/`Permit`
  RAII and `permit.release()`. Did **not** restore `Semaphore::release`.
- Regenerated `benchmarks/BASELINE.json` over all 27 Appendix A tasks.

### Tests

- `cargo build --workspace --offline` → ok (warnings only: one pre-existing
  `unused_mut` in `conform.rs`, one dead field in `concir-instrument`, and the
  intentional `bind_check` kebab-case bin-name warning).
- `cargo test --workspace --offline` → all green. `concir`: 5 lib unit tests +
  all integration suites pass (ast_roundtrip, backend_errors, bind_check,
  conformance, diagnostics_hint, differential, dot_export, engine_agreement,
  instrument, interp_petri_diff, interp_smoke, module_syntax, monitor,
  round2/3/4/5 regressions, schema, semantics_regression, validate_*,
  validator_risks). `concir_sync`: 1 test for `post`/`take` event order.
- Baseline: `concir-backend explore <gold> contract.json petri` over the 27
  Appendix A tasks reproduces outcomes exactly (PASS/UNSUPPORTED/UNKNOWN and
  `complete` match; per-task property outcomes match). Raw table:
  `benchmarks/BASELINE.json`.

### Deviations / Open questions

- `benchmarks/BASELINE.json` uses the raw property ids emitted by the explorer
  (e.g. `preserved: main::w1 completes`, `both-increments`), per the instruction
  to use original strings. `states_explored_reference` is recorded for
  reference only and is **not** compared by the P4 equivalence test.
- Repair-only test fixtures under `tests/repro_*` that no remaining test
  references were retained as inert data rather than deleted (identifying
  "repair-only" fixtures is fuzzy; deleting live semantic fixtures would be
  riskier). Documented in MIGRATION.md; can be pruned later.
- `concir-instrument` wrapper mapping needed no code change: semaphore events
  are produced by the `concir_sync` recorder, so adding `post`/`take` there
  automatically surfaces them as `sem_acquire`/`sem_release` (the runtime event
  strings; ConcIR op kinds remain `semaphore_acquire`/`semaphore_release`).

---
