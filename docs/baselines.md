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

`NO_ISSUES` is recognized only by `classify_rust_reply(..., allow_no_issues=True)`,
and only when the latest version compiled and the stage is `review`. The
classifier drops non-letters and compares with `NOISSUES`, so `NO_ISSUES`
matches. A `NO_ISSUES` reply during `rust_fix` is `other`: the previous
version is kept, `FORMAT_RETRY_NOTE` is prepended, and the call counts.

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
merely contains the word `conflictlock` is not a finding. False positives
are fed back as usual and are also reported by `tools fp-check`.

On this checkout the detector does run (`Detecting deadlock` in the debug
log) and `concir_sync` builds with that nightly, but it emits no `bug_kind`
records for `abba_2lock`'s `buggy.rs` or `fixed.rs`, nor for a same-thread
`Mutex` double lock. Silence is not treated as a finding.

### DYNAMIC (D4-4, D4-8)

Accept when every repeated run exits 0, none times out, and the last
non-empty line equals the terminal line; Shuttle passes (including
`no_concurrency`); and miri passes. `shuttle_unsupported` and
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
failing schedule, so `shuttle.py` is unchanged. The seed still travels in
the environment, not in the generated source.

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
| `rounds` | one record per LLM call: `call`, `stage`, `reply_kind`, `version`, `compiled` (`null` when the compiler did not run), `compile` (`ok` / `error` / `unavailable` / `timeout`), per-tool `status`/`category`, `seeds`, `feedback_sha256`, `feedback_bytes`, `truncated` |
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
