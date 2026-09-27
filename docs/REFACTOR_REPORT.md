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

## P4 — benchmark migration + gold.skel + equivalence

### Changes

- Migrated all 27 tasks to `benchmarks/tasks/<family>/<task>/`, per §6.1:
  `contract.json`, `spec.md`, `ground_truth.json`, `requirements.json` +
  `REQUIREMENTS.md` (where a `generation_input/` exists), `gold.cir.json`
  (the `fixed.cir.json` or `correct.cir.json`), and `rust/fixed.rs` where
  present. Excluded: `buggy.cir.json`, `repair_input/`, `repair_task.json`,
  `rust/buggy.rs`.
- Wrote 25 new `gold.skel` files (24 generation tasks + boundary/unbounded_int;
  boundary rwlock/async intentionally have none).
- Generated `benchmarks/MANIFEST.json` (sha256 + source path per file) and
  `benchmarks/DEVIATIONS.json` (the same_cv and compute mapping deviations).
- Added `crates/skel/tests/equivalence.rs`.

### Tests

`cargo test -p skel --offline` (incl. `equivalence.rs`) → all green:

- `gold_skels_match_baseline`: for each of the 23 comparable tasks, lowering
  `gold.skel` and exploring against the task contract reproduces BASELINE
  `outcome`, `complete` and the exact per-property outcome list.
- `unbounded_int_is_unknown`: UNKNOWN, incomplete, `no-deadlock = UNKNOWN`.
- `rwlock_is_rejected_with_s002`, `async_and_select_are_rejected_with_s002`:
  the two boundary tasks without a gold skeleton are represented as DSL and
  rejected with `S002`.
- `same_cv_different_locks_direct_translation_is_s104`: the original structure
  (one condvar, two mutexes) is inexpressible and yields `S104`; the subset
  `gold.skel` (one condvar per waiter) explores to PASS, recorded as a
  `baseline_deviation`.
- `skelnet check --reqs` on golds is clean (warnings only; e.g. the empty extern
  helper body warns E114, mapped to its DSL line with `unmapped == 0`).

### Deviations / Open questions

- `condvar/same_cv_different_locks` (baseline UNSUPPORTED): a subset skeleton
  gives PASS; recorded in `benchmarks/DEVIATIONS.json` for human confirmation.
- `compute -> nop` (from P3) is re-confirmed as necessary by P4.
- `worker_with_payload`: the sequential helper is named `helper` instead of
  `compute` because `compute` is a DSL keyword; the contract does not name it.
- Tag distribution in gold.skel: `main` carries the union of the task's
  `clauses` ids and worker functions carry the `properties` ids, so `S201`/
  `S202` are clean under `--reqs` while the skeleton stays readable. (The plan
  notes Appendix tags are illustrative only.)

---

## P3 — lowering, source map, feedback remapping

### Changes

- `crates/skel/src/lower.rs` — total lowering of the checked AST to a
  `concir::ast::Program` plus a `SourceMap` (§5.1/§5.2/§5.4). Dense `s1..sn`
  sids per function, backpatched jump targets, `form:"closure"` for
  scope/spawn targets, `provides`/`requires` computed, source-map `stmts`,
  `functions`, `resources`, `json_paths`.
- §5.3 early exits: `return`/`break`/`continue` emit
  `implicit_release_on_exit` unlocks/releases inside-out before the jump, with
  `block_span` on the owning lock/permit block.
- `crates/skel/src/feedback.rs` — maps ConcIR validation diagnostics,
  `invalid`/`unsupported`, explore diagnostics, counterexamples (`StepLabel`
  origin, `cir_statements`, `doom_state`) back to DSL spans; counts `unmapped`;
  renders the §5.5 counterexample table; extracts property→req from a contract.
- `skelnet` CLI gains `lower` (`-o`, `--map`), `check` (front-end + lower +
  `concir::validate` + `concir::sem::program::lower` support, remapped), and
  `verify` (explore + remapped feedback, `--engine`, `--json`).

### Tests

`cargo test -p skel --offline` → 34 tests (31 front-end + 3 in
`tests/verify.rs`):

- `mapping_table_covers_each_row`: one skeleton exercises every §5.2 row and
  asserts the CIR resource fields (`count`, `capacity`, `base`, `init`,
  `protection`) and the full set of emitted op kinds.
- `early_exit_releases_inside_out_and_maps`: nested locks with an early
  `return` produce `mutex_unlock b`, `mutex_unlock a`, `return` with both
  releases marked `implicit_release_on_exit` and carrying a `block_span`.
- `feedback_remap_has_no_unmapped_and_no_goal_leak`: an ABBA-bug skeleton
  verifies FAIL; `unmapped == 0`, every counterexample step has a DSL line, and
  the rendered text contains no contract goal.

Manual checks: `skelnet verify` on the Appendix B (ABBA) and Appendix C
(condvar) skeletons against the real ConcPlanVerify contracts gives PASS with
all per-property outcomes equal to BASELINE and `unmapped == 0`.

### Deviations / Open questions

- **`compute` lowers to ConcIR `nop`, not `seq_hole`.** §5.2 says
  `compute` → `seq_hole`, but ConcIR `a35dc86` classifies `seq_hole` as
  UNSUPPORTED in the precise backend ("sequential fill sites have no defined
  semantics yet"), so *any* skeleton containing a compute hole would be
  UNSUPPORTED and could never match a PASS baseline (e.g. Appendix B ABBA).
  `nop` is ConcIR's supported, semantics-neutral construct; the source-map
  entry still uses `construct: "seq_hole"` so codegen/adhere can identify the
  hole. This is the one deliberate mapping-table deviation and is called out
  for reviewer confirmation.
- The source map's `span` serialises `line/col/end_line/end_col` (matching the
  §5.4 example); byte offsets are omitted there.
- `requires` is computed by scanning emitted ops for cross-module resource and
  callee FQNs. Cross-module resources referenced only inside an expression
  string (not as an op target) are not collected; no gold needs this.
- Per-step "holds after" in the §5.5 table is not available from a ConcIR
  `StepLabel`; the renderer prints step/thread/function/line/statement and a
  `final:` line built from `doom_state` (holds + waits). Every step still has a
  DSL line number, and no contract goal is disclosed.

---

## P2 — `crates/skel`: lexer, parser, AST, fmt, front-end checks

### Changes

New crate `crates/skel` (lib + bin `skelnet`):

- `span.rs` — `Span { start, end, line, col, end_line, end_col }` + `SourceFile`.
- `lexer.rs` — hand-written lexer: identifiers, ints, strings (`\" \\ \n`),
  `//` comments, all punctuation/operators, keywords, and the out-of-subset
  reserved words which emit `S002` + hint.
- `ast.rs` — full DSL AST; every node carries a `Span`; serializable for
  `skelnet parse --json`.
- `parser.rs` — hand-written recursive descent implementing §4.3 EBNF exactly;
  `;`/`}` error recovery; `S003`; at most 20 syntax errors.
- `fmt.rs` — canonical pretty-printer (idempotent, round-trip stable).
- `check.rs` — `S101`–`S109` and `S201`/`S202`; builds the module/resource/function
  tables that lowering will reuse.
- `error.rs` — `S###` diagnostics, rustc-style rendering with caret + hint, and
  the `--json` schema `{code,severity,message,span,hint,origin,concir_code?}`.
- `main.rs` — `skelnet parse|fmt|check` (lower/verify/codegen/adhere land in
  P3/P6). Exit codes 0/1/2.

### Tests

`cargo test -p skel --offline` → 31 tests pass in `tests/frontend.rs`:

- one negative (and one positive) test per `S` code: S001, S002, S003, S101,
  S102, S103, S104, S105, S106, S107, S108, S109, S201, S202. `S104` and `S002`
  also assert the hint text.
- `fmt` round-trip on the Appendix B/C examples plus a mixed atomic/semaphore/
  channel example: reparse is error-free, `fmt` is idempotent, and the AST
  serialization with all span fields zeroed compares equal.
- CLI smoke test: `skelnet check --json` emits `S101` and exits 1; a valid
  program exits 0.

`cargo build --workspace --offline` and `cargo test --workspace --offline` green.

### Deviations / Open questions

- `Span` does not carry the file name; the source file is passed at render time.
  The §4.4 prose lists `file` in the span, but the `--json` schema in the same
  section does not, and omitting it keeps `Span` `Copy`. Recorded here.
- `S106` fires when a `scope` spawn target resolves to a resource rather than a
  function; an undefined target is `S101`. The grammar forbids arguments inside
  `scope`, so "spawn with arguments" in a `scope` is an `S003` syntax error.
- `S101` vs `S103` for "name exists but is the wrong kind": `S103` is used when
  the name resolves and the kind is wrong (e.g. `lock s` on a semaphore,
  `c.load()` on a non-atomic); `S101` when it does not resolve.
- `S201`/`S202` warnings compare tags against the `R<n>` ids that appear in
  `requirements.json` `clauses` (recursive string scan). `unverifiable` numbers
  are integers, so they are not treated as requirements to annotate.

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
