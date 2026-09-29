# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SkelNet is a research harness for skeleton-guided concurrent Rust synthesis. An LLM writes a `.skel` skeleton (a small Rust-flavoured DSL), `skelnet` lowers it to ConcIR, verifies it against a hidden contract by Petri-net exploration, and maps diagnostics and counterexamples back to skeleton lines for revision. A verified skeleton then guides Rust generation, and an arm-agnostic oracle scores the result.

## Commands

```bash
# Rust (toolchain pinned to nightly-2026-09-04 + miri via rust-toolchain.toml)
cargo build --workspace --offline          # first build ever needs network for crates.io
cargo test  --workspace --offline
cargo test -p skel --test adherence        # one integration test file
cargo test -p concir --test round5_regressions <name_filter>

# Python (use the repo venv; conftest.py puts python/ on sys.path)
.venv/bin/python -m pytest python/tests
.venv/bin/python -m pytest python/tests/test_bench_validate.py::<test_name>

# Python CLI: package is not installed; run from repo root with python/ on the path
# (relative defaults like --out experiments/run assume the repo root as cwd)
PYTHONPATH=python .venv/bin/python -m skelnet <run|eval|report|models|oracle|tools|bench> ...

# Benchmark integrity (exits 1 on any fail); prefix with PYTHONPATH=python as above
python -m skelnet bench validate --tasks all
python -m skelnet bench validate --tasks 'lock-order/abba_2lock' --checks V4 --json
python -m skelnet bench validate --tasks all --run --oracle --strict   # builds + runs fixed.rs, full oracle
python -m skelnet bench tiers [--write]

# skelnet front-end (binaries land in target/debug/)
./target/debug/skelnet check  <f.skel> [--reqs requirements.json] [--json]
./target/debug/skelnet verify <f.skel> <contract.json> [--json]
./target/debug/skelnet lower  <f.skel> -o out.cir.json --map out.map.json
./target/debug/concir-backend explore <prog.cir.json> [contract.json]
```

Python locates `skelnet` / `concir-backend` in `target/debug`, then `target/release`, then `$PATH` (you can override with `SKELNET_BIN` / `CONCIR_BACKEND`). **Run `cargo build` before the Python tests**, or tests that need binaries skip or fail. Tests that need cargo, clippy, lockbud, Shuttle, or miri skip when the tool is absent. `scripts/setup_oracle_tools.sh` prefetches Shuttle and sets up the miri sysroot. `scripts/setup_lockbud.sh` builds the pinned lockbud into `tools/lockbud/`.

`skelnet` exit codes: 0 pass, 1 diagnostics error or verification not PASS, 2 usage/IO. `concir-backend` exit codes: 0 PASS, 1 FAIL, 2 usage, 3 UNKNOWN, 4 INVALID, 5 UNSUPPORTED.

## Architecture

Cargo workspace: `crates/concir`, `crates/skel`, `runtime/concir_sync`. `tools/` is excluded from the workspace: it holds the Shuttle shim and the lockbud checkout.

- **`crates/concir`** is vendored and trimmed ConcIR, and it is **the only semantics**. It covers validation (`E###`), the interpreter, the Petri-net explorer, codegen, the instrumenter, and the monitor. Its bins are `concir-backend`, `concir-instrument`, and `bind-check`. The DSL adds no meaning of its own. Do not re-implement ConcIR checks in the front-end; ConcIR diagnostics are remapped instead.
- **`crates/skel`** is the DSL front-end. The pipeline is `lexer.rs` → `parser.rs` (hand-written recursive descent; no parser generators) → `check.rs` (`S###` codes) → `lower.rs` (ConcIR JSON plus a `SourceMap`) → `feedback.rs` (ConcIR locations/paths → DSL spans). Lowering is total and does not optimise. `compute "…"` holes lower to `nop` on purpose (see `docs/lowering.md`). `adhere.rs` is a human-review tool only, and no arm or metric uses it.
- **`runtime/concir_sync`** is a std-only semaphore that generated Rust depends on by path.
- **`python/skelnet`** runs the experiments:
  - `pipeline.py` defines the arms `G0` (direct Rust), `SKEL`, and `CIR` (the LLM writes ConcIR JSON).
  - `baselines.py` defines `REFINE`, `STATIC`, `DYNAMIC`, and `DYNAMIC_M`.
  - `prompts.py::PROMPT_ROUTES` maps each (arm, stage) pair to an ordered tuple of `prompts/*.md` assets. A missing route raises, and there is never a fallback to another arm's prompt. Prompts are content-addressed by sha256, so editing a prompt changes cache keys.
  - `oracle.py` plus `rusttools/` implement the four-layer oracle: O1 build/policy, O2 20 runs plus the terminal line, O3 Shuttle plus miri, O4 instrument plus monitor against the contract. `functional_ok` is the conjunction of all four. See `docs/oracle.md`.
  - The rest of the machinery lives in `transport.py`/`providers.py`/`models.py` (LLM clients), `cache.py`/`budget.py` (response cache and global spend ledger), `schema.py` (the `skelnet-cell-v1` result schema, validated before every write), and `bench.py` (`bench validate` checks V1–V9 and `bench tiers`).

## Benchmarks

Each task lives in `benchmarks/tasks/<family>/<task>/`. It contains `spec.md`, `requirements.json` (terminal line, entities, tier), `REQUIREMENTS.md` (h0) / `REQUIREMENTS.h1.md` (h1), `contract.json` (hidden), `gold.skel`, `gold.cir.json`, `ground_truth.json`, and `rust/{fixed.rs,buggy*.rs,expect.json}`. `boundary/` tasks are negative examples and need only a subset of these files. `docs/benchmarks.md` defines every file and check.

Some edits need follow-up work elsewhere:
- **Any change to task files** means updating that file's sha256 in `benchmarks/MANIFEST.json` (check V9). No tool regenerates it, so edit the hash by hand.
- **Changing `rust/fixed.rs`** changes the `crates/skel/tests/adherence.rs` insta snapshots, which run over every task's `fixed.rs`. Regenerate them, for example with `INSTA_UPDATE=always cargo test -p skel --test adherence`, and review the diff. `cargo-insta` is not installed.
- `gold.skel` must verify to the same outcome as `BASELINE.json` / `BASELINE_EXT.json` (`crates/skel/tests/equivalence.rs`, check V4).
- `fixed.rs` must compute its terminal line rather than print it as a string literal (check V6).

## Hard rules

- **Never modify `benchmarks/BASELINE.json`, `BASELINE_EXT.json`, or `DEVIATIONS.json`** unless the round's task sheet explicitly allows it. Never edit an existing task's `contract.json`, `gold.skel`, `gold.cir.json`, `REQUIREMENTS.md`, `spec.md`, or `ground_truth.json`. h1 lives in a new file (`REQUIREMENTS.h1.md`); it does not replace h0. Never change expectations to get a green run. If a requirement can't be met, stop and report.
- **Reference Rust (`rust/fixed.rs`, `buggy*.rs`):**
  - Mutex/Condvar/Semaphore construction sites equal gold's counts (channels and atomics are exempt).
  - Name variables and functions after entities.
  - `thread::spawn` takes a closure that only calls the same-named function. No `thread::scope`, no nested grouped `use std::{…}` imports, and no spawning different roles inside a loop.
  - `Condvar::wait` goes inside a predicate loop.
  - The terminal line is computed; `println!("DONE x={}", 1)` is forbidden even though V6 can't see it.
  - `buggy.rs` differs from `fixed.rs` only in the defect.
- **Known oracle gaps (round 9b fixes them in the tooling, not the data):**
  - O3 checks only exit codes, not output. As a result, the lost-update and overflow defects in `structure/worker_with_payload`, `atomic-data/atomic_lost_update`, and `atomic-data/counter_overflow_safety` pass O3.
  - Shuttle PCT reports the correct busy-wait in `lock-order/partial_deadlock_bystander` as a panic. Do not change it to park/unpark.
  - Until 9b merges, a full `bench validate --run --oracle --strict` is not all green. Don't widen race windows or touch these tasks.
- `test_round04_fpcheck.py` relies on the substring `mtx_c` in `lock-order/cycle_3lock/rust/fixed.rs`.
- **Contract disclosure:** feedback shown to the LLM must never contain contract `goal` formulas, `holds_all(`, `completed(`, `function_completed`, or the contract file (`prompts.sanitize_detail`, `test_feedback_disclosure.py`). The CIR and SKEL arms must receive equivalent information (see `docs/feedback.md`, "CIR fairness").
- **No new dependencies.** Rust is limited to serde, serde_json, syn, proc-macro2, and insta, and must build `--offline`. Python is limited to `openai`, `cursor-sdk`, and the stdlib (plus pytest for dev).
- **No real LLM calls in tests.** Use `python/tests/_fake_sdk.py` or recorded fixtures. `run` spends real API budget, so use `--dry-run` to check prompts and budgets. `models probe --dry-run` makes no calls.
- **`.env` holds API keys.** Never print, commit, or snapshot its values. `.env.example` lists key names only.
- `UNKNOWN` or incomplete exploration is never reported as safe.

## Conventions

- Work happens in review rounds. A coordinator writes a task sheet per round, and Kevin (the owner) forwards it to the executor. The executor branches from the latest `origin/main` (`round<id>/<topic>`), opens a PR to `main`, and prefixes commit subjects with the round id (for example `R7a2a-fix: F1 …`). Review fixes go onto the same branch; don't open a new PR.
- Sync with `git merge origin/main`. Never rebase a pushed branch, force-push, or push to `main`. Touch only the files the task sheet allows. Follow the "adopted" column of its decisions table. Report tool defects (symptom, repro, workaround) instead of fixing them.
- Every change needs a test that fails when the change is reverted. The real CLI paths (`cmd_run`, `cli.main`) need tests that fake only the outermost client or subprocess.
- Never put absolute paths or API keys in logs, reports, feedback, or snapshots. Real LLM runs happen only on Kevin's machine.
- **Rebuild before testing.** Python tests use whatever binaries are in `target/debug`. Stale binaries give misleading failures, for example the MutexGuard O4 test.
- Experiment outputs go to `experiments/<run_id>/` (layout in `docs/experiments.md`). Raw cell artifacts are git-ignored.
- Reference docs: `docs/dsl.md` (authoritative EBNF), `docs/lowering.md` (mapping table and source map), `docs/error_codes.md`, `docs/result-schema.md`, and `docs/concir/` (ConcIR semantics and CLI). Keep them in sync with code changes. `docs/REFACTOR_PLAN.md` is the original (Chinese) spec for the migration.
