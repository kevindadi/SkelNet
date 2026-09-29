# Baseline arms (B0–B3)

The baseline arms write Rust directly and are scored by the same oracle as
SKEL and CIR. In-group acceptance is separate from that oracle: the loop
never calls `RustOracle`, and the oracle scores only the final program, on
`<cell>/`. Compile probes live in `<cell>/compile/c<k>/`. Feedback probes
live in `<cell>/feedback/r<k>/`.

| Arm | Group | Feedback after a successful compile | In-group accept |
| --- | --- | --- | --- |
| `G0` | B0, one call | none | the program compiles |
| `REFINE` | B1 | the model reviews its own program (`NO_ISSUES`) | reply `NO_ISSUES` and the latest version compiles |
| `STATIC` | B2 | rustc diagnostics, concurrency clippy, lockbud | no blocking static finding |
| `DYNAMIC` | B3 | repeated runs, Shuttle (PCT + random), miri | every dynamic tool passes |
| `DYNAMIC_M` | B3-M | B3 plus `concir-backend monitor` | B3, and the monitor has no blocking result |

Each cell makes at most `call_budget` LLM calls (default 5) and stays inside
the cell token budget. A non-empty `CandidateResponse.error` ends the loop.
The final Rust is the latest version, even when it does not compile.

## Shared first call and compile repair (D4-1, D4-10)

Call 1 of every arm is `stage=generate` with the G0 system prompt
(`rust_generation_v2.md` + `rust_runtime_api_v1.md`) and
`requirements_only_user_prompt`. The cache key does not include the arm, and
`call_index` is 1, so one `--cache-dir` stores that reply once.

Official order: run `G0` first, then the four baseline arms with the same
`--cache-dir` and `--first-round require-cache`. `require-cache` raises
`first_round_miss` (no inner call, no oracle) when call 1 is absent.
`auto` (the default) uses a hit and otherwise calls the model.

`--replay-mode key` (default) requires the tool feedback to be byte-identical,
because the next request is part of the cache key. Offline reproduction of
DYNAMIC and DYNAMIC_M uses `--replay-mode sequence`: the reply is the one
stored for `(model_id, arm, task, rep, call_index)`, even when the request
text differs. A differing request sets `calls[].replay_mismatch` to true and
still returns the recorded reply. See `docs/experiments.md` (Reproducibility).

`--tasks` accepts `all` or a comma-separated union of fnmatch patterns, in
directory order. Any pattern that matches nothing prints
`unmatched task patterns: ...` on stderr and exits 2. The same syntax applies
to `tools fp-check`.

A version that does not compile is followed by `stage=rust_fix` for every
arm, including SKEL and CIR. The system prompt is `rust_compile_fix_v1.md`
plus the runtime appendix, and the user text is `render_compile_errors`
(errors only, 8192 bytes). Group-specific feedback starts only after a
version compiles.

A compiler that does not produce a verdict is not a compile failure (round
5b, M2). `compile_rust` reports `unavailable` when cargo cannot run or exits
non-zero with no compiler error, and `timed_out` when the build times out.
That round records `compiled: null` and `compile: "unavailable"` or
`"timeout"`. The loop stops with no further LLM call and no `rust_fix`,
`accepted` is false, and an empty cell `error` becomes
`compile_unavailable` or `compile_timeout`. The oracle still scores the
latest Rust. G0 uses the same error strings.

## Acceptance details

### REFINE (D4-6)

`NO_ISSUES` is recognized only for REFINE, only at stage `review`, and only
when the current version compiled (`allow_no_issues=True`). The classifier
drops every non-letter character and accepts the reply only when what remains
is exactly `NOISSUES`, so `NO_ISSUES` and `No issues.` match. That check runs
before code fences. A reply that contains a code block does not reduce to
`NOISSUES`; if the extracted block contains `fn main` it is a program. A
`NO_ISSUES` reply during `rust_fix`, or while the current version does not
compile, is `other`: the previous version is kept, `FORMAT_RETRY_NOTE` is
prepended, and the call counts.

### STATIC (D4-2, D4-3)

Blocking: a rustc error; rustc warning `let_underscore_lock` or
`unused_must_use`; any finding in `CONCURRENCY_LINTS`; any lockbud `bug_kind`
record. Other rustc warnings are shown and do not block. An unavailable tool
is not a finding.

Clippy is `cargo clippy -- -A clippy::all -W <lint>...` with, in order:

- `clippy::mutex_atomic`
- `clippy::mutex_integer`
- `clippy::significant_drop_in_scrutinee`
- `clippy::significant_drop_tightening`
- `clippy::arc_with_non_send_sync`
- `clippy::readonly_write_lock`

On toolchain `nightly-2026-09-04` all six exist. None were dropped.

Lockbud is commit `cc78cb7` on `nightly-2026-02-07`. The wrapper is invoked
with `LOCKBUD_LOG=warn` because the JSON report is a `log::warn!` and is
otherwise silent. Only JSON `"bug_kind"` records count. A summary line that
merely contains the word `conflictlock` is not a finding. Each record's raw
text is the full JSON object (`JSONDecoder.raw_decode`), so a nested
`ConflictLock` `diagnosis` keeps every edge. False positives are fed back as
usual and are also reported by `tools fp-check`.

A non-zero lockbud exit that produced no `bug_kind` record is not a clean
result. `tools.lockbud` is `{"status": "unavailable", "category":
"lockbud_failed"}` and the feedback says `lockbud could not analyze this
program: …` (the first stderr line that starts with `error`, otherwise the
last non-empty stderr line, after path rewriting). That does not block
acceptance, same as `shuttle_unsupported` / `miri_unsupported`. A non-zero
exit that still emitted `bug_kind` records keeps those records and blocks.
Exit 0 with no records stays `pass` and the feedback says `no bug_kind
records`.

What the same invocation reports depends on how the locks are written:

| Shape | `bug_kind` |
| --- | --- |
| two spawn closures locking a→b and b→a | `ConflictLock` |
| same function locks one `Mutex` twice | `DoubleLock` |
| `&Arc<Mutex<_>>` parameters, struct fields, `thread::scope` + `&Mutex`, `static` locks, reverse order inside one function | `ConflictLock` |
| two named functions that take `Arc<Mutex<_>>` by value | none (known miss) |

The miss is alias analysis: lockbud does not follow an `Arc` moved by value
into different callees. `-k all`, `LOCKBUD_LOG=info`, and `-b` do not change
it. `abba_2lock`'s `REQUIREMENTS.md` calls t1/t2 "threads/functions", so a
model often writes that missed form. The replay fixture's STATIC arm
therefore accepts the ABBA program on call 1. Silence after a successful
run is not a finding.

### DYNAMIC (D4-4, D4-8)

Accept when every repeated run exits 0, none times out, and the last
non-empty line equals the terminal line; Shuttle passes (including
`no_concurrency`); and miri passes. Shuttle passing includes the round-9b
rules of the oracle's O3 (`docs/oracle.md`), under the feedback seed: every
explored schedule's last non-empty line must equal the terminal line
(`wrong_output` otherwise), PCT abandons iterations above 10 000 steps, and
random above 1 000 000 steps is `livelock`. Both block acceptance like any
other Shuttle failure. The `wrong_output` feedback is `category:
wrong_output`, the `schedule <k>/<n> (<scheduler>): <line>` detail and the
`failure.txt` text (expected and observed last lines and the first 40 lines
of that schedule). The `livelock` feedback is only `category: livelock` and
Shuttle's `exceeded max_steps bound …` line: the failing schedule of a
million-step run is hundreds of kilobytes of hex. Schedule marker lines never
appear in feedback. `shuttle_unsupported` and
`miri_unsupported` do not block, and the feedback says the tool could not
run. `miri_unavailable` and a build failure do block.

Defaults, every round: 20 runs × 10 s (no seed); Shuttle PCT 2000 (depth 3)
then random 2000 at `FEEDBACK_SHUTTLE_SEED`; miri uses the first
`--feedback-miri-seeds` seeds of the feedback window (default 16, at most 64)
starting at `FEEDBACK_MIRI_SEED_START`.

Shuttle's panic header contains the OS thread id. That id is removed before
the failure text is placed in the feedback, so a repeated run of the same
program and seed produces the same feedback bytes. The schedule string is
left intact.

Every feedback section (clippy rendered text, lockbud records and the
lockbud failure line, stress, Shuttle, miri, monitor property `detail`, and
the monitor-run detail) goes through `clippy.relativize`, in order:

1. `compile._relativize` rewrites the probe workdir, the repository root, and
   the rustc sysroot source prefix (`<rust>/`), and rewrites remaining
   `-->` / `:::` positions to `<abs>/<filename>`.
2. `CARGO_HOME` (or `~/.cargo` when it is unset) `registry/src/<index>/`
   becomes `<cargo>/registry/`.
3. Any other absolute path with at least two components, including
   `panicked at /…:line:col`, becomes `<abs>/<filename>`. The line and column
   stay.

### DYNAMIC_M (D4-5)

Blocking monitor results: a safety property `FAIL` (also `never_holds_all` /
`unreachable`); a preserved/reachable property `not_observed`; a property
`unmapped`; an instrumented run that times out or crashes. Not blocking:
`instrument_unsupported` (feedback says `monitor 无法插桩这种写法`),
`deferred`, `unsupported`, and anything derived from the reference design
(`design_loss`, thread counts, `extra_sync`).

The model sees property id (via `present_property_id`), `kind`, `source`,
`req`, `status`, `sanitize_detail(detail)`, and unmapped program resource
names. It does not see the contract goal, `gold.cir.json`, or `gold.skel`.
`concir-backend monitor` does not emit an event sequence; this round does
not add one.

B3-M is implemented here and is run officially at Stage 2.

## Feedback length (D4-9)

Each tool-feedback message is at most 8192 UTF-8 bytes. Sections stay in a
fixed order, share the budget equally, and unused bytes roll forward. A
section that does not fit keeps its prefix and ends with `[truncated]`.

## Seeds (T0, T1)

| | Shuttle | miri start | miri count |
| --- | --- | --- | --- |
| Oracle (held out) | `0x5EED_0001` | `0x5EED_1000` | 16 |
| Feedback | `0xF00D_0001` | `0xF00D_1000` | 64 reserved, 16 used |

The ranges are disjoint.

Shuttle 0.8.1 reads `SHUTTLE_RANDOM_SEED` inside `check_random` /
`RandomScheduler::new` and `check_pct` / `PctScheduler::new` (both call
`new_from_seed` and override the constructor seed when the variable is a
valid `u64`). The same failing program and the same seed reproduce the same
failing schedule. Round 9b builds PCT through
`shuttle::Runner::new(PctScheduler::new(depth, iterations), cfg)` instead of
`check_pct` (only `cfg.max_steps` differs), so the seed still applies. The
seed still travels in the environment, not in the generated source.

## Installing tools

```bash
bash scripts/setup_oracle_tools.sh   # cargo fetch Shuttle, miri
bash scripts/setup_lockbud.sh        # clone lockbud @ cc78cb7, nightly-2026-02-07
```

`tools/lockbud/` is gitignored. `concir_sync` has no crates.io dependencies.
Whether that crate builds under lockbud's nightly is recorded by the gated
lockbud test and by `tools fp-check`.

## `tools fp-check`

```bash
python -m skelnet tools fp-check --tasks all --out /tmp/fp
python -m skelnet tools fp-check --tasks 'lock-order/*,condvar/*' --out /tmp/fp
```

For every selected task, clippy (`CONCURRENCY_LINTS`) and lockbud run on
`rust/fixed.rs` and `rust/buggy*.rs`. The command writes `FP_CHECK.json` and
`FP_CHECK.md`: per-program findings, the false-positive rate on `fixed.rs`,
and the detection rate on `buggy*.rs`. A missing tool is `unavailable` and
the exit code stays 0. Tasks that have no `buggy*.rs` yet contribute no
detection rate.

## `baseline` object

`result.extra["baseline"]` is written at the top level of the cell:

| Field | Meaning |
| --- | --- |
| `rounds` | one record per LLM call: `call`, `stage`, `reply_kind`, `version`, `compiled` (`null` when the compiler did not run), `compile` (`ok` / `error` / `unavailable` / `timeout`), `compile_wall_ms` (milliseconds, or null when nothing was compiled), per-tool `status`/`category` and `wall_ms`, `seeds`, `feedback_sha256`, `feedback_bytes`, `truncated` |
| `accepted_at_call` | the call that met the in-group rule, or null |
| `accept_reason` | `no_issues`, `static_clean`, `dynamic_pass`, `dynamic_monitor_pass`, `budget_exhausted`, `model_error`, `compile_unavailable`, or `compile_timeout` |
| `final_version` | index of the latest program (0 if none) |
| `first_round_cache_hit` | cache hit of call 1, when the provider records one |
| `tools_missing` | names reported by preflight |

`accepted` follows the in-group rule. `parse_ok` is whether call 1 was a
program. `check_ok` is whether any version compiled. `rounds_used` is the
number of `propose` calls.

## MANIFEST `baseline_tools`

Recorded for resume checks: clippy version and `probe_lints` (STATIC only),
lockbud commit and toolchain when the checkout is readable, Shuttle `0.8.1`
when the registry has it, the feedback seed window, the repeated-run
parameters, `first_round`, and `missing`. A resume whose snapshot differs
exits. Dry-run does not require the tools. A baseline arm with
`--rust-mode codegen` exits. `--allow-missing-tools` records the gap instead
of exiting; the tools still run when they are installed.

## Decisions D4-1 through D4-10

Executed as specified in the round-4 task. D4-3 dropped no lints. D4-6 uses
round 5's classifier rather than an exact token match. D4-7 keeps the latest
version when the budget is spent.
