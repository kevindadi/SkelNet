# Benchmarks

Tasks live in `benchmarks/tasks/<family>/<task>/`. `bench validate` checks that
a task is complete enough to run, and `bench tiers` computes a difficulty
tier from the gold ConcIR program. Neither command edits the tree unless
`bench tiers --write` is passed.

## Layout

| File | Role |
| --- | --- |
| `spec.md` | Human-readable description of the task |
| `requirements.json` | Machine-readable requirements, `terminal`, optional `terminal_v2`, `entities`, `hint_variants`, and (when strict) `tier` |
| `REQUIREMENTS.md` | h0 prompt text. May mark unverifiable sentences with `[U]` |
| `REQUIREMENTS.h1.md` | h1 prompt text: same `R<n>.` numbers and Entities section as h0, no `[U]`, no contract leakage, terminal line in backticks |
| `contract.json` | Hidden verification contract |
| `gold.skel` | Reference skeleton |
| `gold.cir.json` | Reference ConcIR program |
| `ground_truth.json` | Expected defect family and monitor resources |
| `direct.skel` | Boundary-only skeleton that must be rejected by `skelnet check` |
| `rust/fixed.rs` | Reference program. The terminal line is computed, not a string literal |
| `rust/buggy*.rs` | Defect programs that must fail the oracle |
| `rust/expect.json` | Expected oracle layer and category (see below) |

A task whose path starts with `boundary/` is a boundary task. It only needs
`contract.json`, `ground_truth.json`, and `spec.md`. Every other task is a
main task (L1/L2/L3) and needs the full set, including at least one
`rust/buggy*.rs`.

## Hints and the terminal line

`cli.read_terminal` is the only reader. With hint `h0` it returns
`requirements.json`'s `terminal`. Otherwise it prefers `terminal_v2` when that
field is a non-empty string, and falls back to `terminal`. The default hint
for the reader is `h1`.

`hint_variants`, when present, lists the hint ids the task claims to support.
`h0` requires `REQUIREMENTS.md` and `h1` requires `REQUIREMENTS.h1.md`.

A `terminal` of exactly `DONE done=1` is a placeholder. The task must also
set `terminal_v2` to a different line. Programs that intentionally print a
constant line are named in `benchmarks/terminal_allowlist.json`
(`{"<family>/<task>": "<reason>"}`). A missing allowlist is empty. Those
tasks skip the literal-terminal check.

## `rust/expect.json`

```json
{"schema_version": "skelnet-rust-expect-v1",
 "fixed.rs": {"functional": true},
 "buggy.rs": {"functional": false, "layer": "O3", "category": "deadlock"}}
```

Keys are file names under `rust/`. `layer` is `O1`–`O4`. Categories match the
oracle: O1 `no_build` / `policy_violation`; O2 `hang` / `crash` /
`wrong_output` / `no_output`; O3 `deadlock` / `panic` / `thread_leak` / `ub`;
O4 `monitor_fail` / `not_observed` / `unmapped` / `design_loss`.

## Checks (`bench validate`)

| Id | What it checks |
| --- | --- |
| V1 | Required files exist (main vs boundary, above) |
| V2 | `terminal` is a non-empty string; `entities.roles` and `entities.resources` are lists (they may be empty); placeholder terminal has a distinct `terminal_v2`; `hint_variants` files exist. `--strict` also requires `tier` ∈ {L1, L2, L3}. Boundary tasks skip |
| V3 | h1 and h0 share R-numbers and the Entities section; h1 has no `[U]`, quotes the terminal from `read_terminal`, and does not contain `clauses`, `contract.json`, or the task path. Boundary tasks skip |
| V4 | Main tasks: `skelnet verify gold.skel contract.json --json` matches `BASELINE.json` or `BASELINE_EXT.json` (`outcome`, `complete`, per-property outcomes). A `baseline_deviation` with no `moved_to` is skipped. Boundary tasks: `concir-backend explore` on `gold.cir.json` matches the same entry; `direct.skel` must make `skelnet check` exit 1, and the error codes are reported |
| V5 | Tasks listed in `BASELINE_EXT.json`: `skelnet lower gold.skel` equals `gold.cir.json` after key-sorted JSON |
| V6 | `rust/fixed.rs` does not contain the terminal line as a whole string literal, and some `println!` / `print!` has a `{}` or `{name}` argument. Allowlisted tasks and boundary tasks skip |
| V7 | With `--run`: build `rust/fixed.rs` outside the repository (empty `[workspace]`, dependency `runtime/concir_sync`) and run it once (10 s). Exit 0 and the last non-empty stdout line equals the terminal line. Without `--run`, skip |
| V8 | With `--oracle`: `fixed.rs` has `functional_ok` true and every `buggy*.rs` has `functional_ok` false, using `default_oracle_factory`. When the result has `layers` and `expect.json` names a layer, that layer must be `fail` with the expected category. Without layers the category check is skipped. Without `--oracle`, skip |
| V9 | Every `benchmarks/MANIFEST.json` record for the task hashes to the file bytes, and every `rust/` file and `REQUIREMENTS.h1.md` has a record |

Lookup of a BASELINE row is by the task's directory path, then by
`DEVIATIONS.json` `task` / `moved_to`. Task names are not hard-coded.

Any `fail` makes the process exit 1. `skip` does not.

```bash
python -m skelnet bench validate --tasks all
python -m skelnet bench validate --tasks 'lock-order/abba_2lock' --checks V4 --json
python -m skelnet bench validate --tasks all --run --oracle --strict
```

`--root` points at a repository root (the default is this checkout). `--json`
prints the machine-readable report.

## Tiers (`bench tiers`)

Threads are the distinct functions named by `spawn` or `scope` in
`gold.cir.json` (not `entities.roles`). Sync resources are ConcIR resources
whose type is Mutex, Condvar, Semaphore, Channel, or Atomic; a plain `Var`
does not count. Mechanism count is the number of those types in use. A
resource is parameterized when a Semaphore `count` is not 1 or a channel-like
resource carries `capacity` or `bound`.

The state count is `states_explored` from `concir-backend explore` on
`skelnet lower gold.skel` (`petri`). `skelnet verify --json` does not report
it. If lowering or exploration fails, the count falls back to the BASELINE
row's `states_explored_reference` and the row says so.

| Tier | All of |
| --- | --- |
| L1 | ≤3 threads, ≤2 sync resources, 1 mechanism, ≤300 states |
| L2 | 3–4 threads, 2 mechanisms, 300–5000 states |
| L3 | 4–6 threads, ≥3 mechanisms or a parameterized protocol, 5000–100000 states |

`computed_tier` is the lowest matching tier. Otherwise it is `unclassified`
and the failed conditions are listed.

The declared tier of a task already in the frozen baseline is `L1`
(`tier_source: legacy`). A task that exists only in `BASELINE_EXT.json` is
declared as `computed_tier` (`tier_source: computed`). The report lists every
task whose computed tier differs from the declared one.

```bash
python -m skelnet bench tiers
python -m skelnet bench tiers --json
python -m skelnet bench tiers --write   # benchmarks/TIERS.md and requirements.json
```

`--write` appends `tier`, `tier_source`, and `tier_metrics` to each main
task's `requirements.json` (existing keys stay in order; indent 2; trailing
newline) and writes `benchmarks/TIERS.md`. Boundary tasks are omitted.
