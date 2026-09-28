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
| V2 | `terminal` is a non-empty string; `entities.roles` and `entities.resources` are lists (they may be empty); placeholder terminal has a distinct `terminal_v2`; `hint_variants` is a list or object and each hint has its file; `protocol_params`, when present, maps names to integers ≥ 2. `--strict` also requires `tier` ∈ {L1, L2, L3}. Boundary tasks skip |
| V3 | h1 and h0 share R-numbers and the Entities section; h1 has no `[U]`, quotes the terminal from `read_terminal`, and does not contain `clauses`, `contract.json`, or the task path. Boundary tasks skip |
| V4 | Main tasks: `skelnet verify gold.skel contract.json --json` matches `BASELINE.json` or `BASELINE_EXT.json` (`outcome`, `complete`, per-property outcomes). A `baseline_deviation` with no `moved_to` is skipped. Boundary tasks: `concir-backend explore` on `gold.cir.json` matches the same entry; `direct.skel` must make `skelnet check` exit 1, and the error codes are reported |
| V5 | Tasks listed in `BASELINE_EXT.json`: `skelnet lower gold.skel` equals `gold.cir.json` after key-sorted JSON |
| V6 | Static check of `rust/fixed.rs`. A decoded string literal whose line equals the terminal line fails (escapes such as `\n` are decoded; raw strings and comments are handled; a character literal is not a string). A `println!`, `print!`, `writeln!`, or `write!` counts only outside comments. The format string is the first string literal. At least one such call must contain a Rust format hole (`{}`, `{0}`, `{name}`, `{name:?}`, `{name:>1}`, …) whose pattern matches the whole terminal line. `println!("{}", line)` and `println!("{line}")` pass. Splitting the line across two prints does not. This check cannot see constant arguments such as `println!("DONE t1={} t2={}", 1, 1)`; V8 and review cover that. Allowlisted tasks and boundary tasks skip |
| V7 | With `--run`: build `rust/fixed.rs` outside the repository (empty `[workspace]`, dependency `runtime/concir_sync`) and run it once (10 s). The comparison uses `last_nonempty_line` (the line is not stripped). A trailing space, a non-zero exit, or `panicked` on stderr is a fail, matching oracle O2. Without `--run`, skip |
| V8 | With `--oracle`, `expect.json` is checked first: `schema_version` is `skelnet-rust-expect-v1`; every `fixed.rs` / `buggy*.rs` has an entry and there are no extras; `fixed.rs` has `functional: true`; each buggy file has `functional: false`, `layer` ∈ O1–O4, and a `category` from that layer's set above. Then `default_oracle_factory` (unless a test supplies one) must report `functional_ok` the same way, and the named layer must be `fail` with that category. A result with no `layers` fails. Without `--oracle`, skip |
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
prints the machine-readable report. `--tasks` is either `all` or a
comma-separated list of patterns, each passed to `cli._select_tasks`, and the
hits are unioned in directory order. If the selection is empty, or any one
pattern matches nothing, both commands print the unmatched patterns on stderr
and exit 2 without writing a report. `tiers --write` writes nothing in that
case.

## Tiers (`bench tiers`)

Threads are spawn sites, not distinct functions and not `entities.roles`.
Every `spawn` node counts as one thread, and every entry of a `scope`'s
`funcs` list counts as one, repeats included. `main` is not counted. A spawn
written inside a loop is still a single ConcIR node, so that loop contributes
1: the model does not unroll it. `tier_metrics.thread_funcs` lists the
distinct callee names.

Only sync resources that an operation actually names are counted. The name is
matched as `module::name` and, for older files, as the bare name. Declared
but unused resources are listed in `tier_metrics.unused_resources` and do not
affect the tier. A plain `Var` is not a sync resource. Mutex and Condvar each
count as one sync resource.

Mechanisms are coarser than resource types. A Condvar and the Mutex named by
its `condvar_wait.lock` are one mechanism, `Condvar`, because a condition
variable cannot be waited on without that mutex. `Mutex` is counted only when
some used mutex is not the lock of any wait. Semaphore, Channel, and Atomic
each add their own mechanism. This stops every condvar task from looking like
a two-mechanism protocol.

`parameterized` is not guessed from CIR fields. Channel `capacity` (including
0) and a semaphore `count` of 0 are ordinary resource data, not a parameter.
The flag is true only when `requirements.json` has `protocol_params`, an
object whose values are integers ≥ 2, for example `{"accounts": 4}`. V2
rejects any other shape. Real parameterized protocols such as an N-account
transfer are then visible even if they only use mutexes.

The state count is `states_explored` from `concir-backend explore` on
`skelnet lower gold.skel` (`petri`), and only when that report has
`complete: true`. An incomplete exploration sets
`tier_metrics.states_complete` to false, notes `incomplete (<count>)`, and
fails the state condition. `skelnet verify --json` does not report a state
count. If lowering or exploration cannot run, the count falls back to the
BASELINE row's `states_explored_reference` and the row names that source.

| Tier | Threads (not including main) | Structure | Complete states |
| --- | --- | --- | --- |
| L1 | 0–3 | ≤2 sync resources and ≤1 mechanism | ≤300 |
| L2 | 3–4 | ≥2 mechanisms, or ≥3 sync resources | 300–5000 |
| L3 | 4–6 | ≥3 mechanisms, or `protocol_params` | 5000–100000 |

Both ends of each range are included. `computed_tier` is the lowest tier
whose three conditions all hold. `nearest_tier` is the tier with the fewest
violations; a tie takes the lower tier. `tier_metrics.violations` lists what
`nearest_tier` missed.

Declaration:

- A task in `BASELINE.json`, or one whose `requirements.json` already has
  `tier_source: legacy` and `tier` in L1–L3, keeps that declaration.
  `condvar/two_cv_two_locks` is declared L1 that way by round 7a-2; the tool
  does not special-case the name. `--write` does not change `tier` or
  `tier_source` for these tasks; it only refreshes `tier_metrics`. The report
  lists legacy declarations that are not in `BASELINE.json`.
- Otherwise, when `computed_tier` is set, that is the declaration
  (`tier_source: computed`).
- When no tier matches and `nearest_tier` misses exactly one condition, and
  that condition is threads or structure rather than states, the declaration
  is `nearest_tier` (`tier_source: nearest`). A state miss, or two or more
  misses, is declared `unclassified`. `--strict` then fails V2, because
  `unclassified` is not L1, L2, or L3.

`TIERS.md` has `nearest` and `violations` columns, a declared-versus-computed
list, and the `nearest` tasks. The summary counts tasks both by declaration
and by `computed_tier`.

```bash
python -m skelnet bench tiers
python -m skelnet bench tiers --json
python -m skelnet bench tiers --write   # benchmarks/TIERS.md and requirements.json
```

`--write` keeps existing `requirements.json` key order (indent 2, trailing
newline). Boundary tasks are omitted.
