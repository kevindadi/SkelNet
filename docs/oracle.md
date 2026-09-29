# Independent oracle (v2)

Every arm's final Rust is scored by one arm-agnostic four-layer oracle. The
layers are independent: a program can pass the build and still fail schedule
exploration, and each layer's result is recorded separately.

## Layers

| Layer | What it checks | Failure categories |
| --- | --- | --- |
| **O1** build & policy | `cargo build` (std + `concir_sync` only); policy scan: no `unsafe`, `static mut`, `thread::sleep`/`yield_now`, `process::exit`/`abort`, `extern crate`, `#![feature]`, or crates other than `std`/`core`/`alloc`/`concir_sync`/`crate`/`self`/`super`/local `mod` | `no_build` / `policy_violation` |
| **O2** termination & output | run the built binary `R=20` times (10 s watchdog each); every exit code 0, and the **last non-empty line equals** the expected terminal line | `hang` / `crash` / `wrong_output` / `no_output` |
| **O3** schedule exploration | Shuttle PCT (step bound `ContinueAfter(10_000)`: an over-long PCT iteration is abandoned) then random (default `FailAfter(1_000_000)`) with the oracle's reserved seed; every explored Shuttle schedule must end with the terminal line; plus miri multi-seed | `deadlock` / `livelock` / `wrong_output` / `panic` / `thread_leak` / `ub`; `shuttle_unsupported` / `miri_unsupported` |
| **O4** structural fidelity | `concir-instrument --wrappers` + `concir-backend monitor` against the task contract: safety never violated, preserved observed at least once, and at least the reference number of worker threads | `monitor_fail` / `not_observed` / `unmapped` / `design_loss` |

Main metric `functional_ok = O1 ∧ O2 ∧ O3 ∧ O4`. Sensitivity metric
`functional_ok_no_o4 = O1 ∧ O2 ∧ O3`.

## Composition

- A layer participates in the conjunction when its status is `pass` or `fail`.
- An `unsupported` layer does **not** participate, but sets
  `oracle_complete = false`; its category is still recorded.
- Any layer that is `unavailable` (tool missing) makes `functional_ok = null`
  (an environment problem, not a program defect).
- A layer that fails records the dependent later layers as `not_run` (O1
  failing leaves O2–O4 `not_run`; O2 `hang`/`crash` leaves O4 `not_run`, since a
  non-terminating program cannot be instrumented meaningfully — O3 still runs).
  O2 `wrong_output`/`no_output` still lets O4 run.
- `terminal_check` comes from O2: `pass` only when all R runs match. A task
  with no terminal line is still `absent` and O2 fails. In codegen mode
  (`check_terminal=False`) it is `not_applicable` and `functional_ok = null`,
  while the other layers still run.
- `oracle_complete` is true only when every layer actually ran and decided.

The per-cell `oracle` object (shared with the cell schema) is:

```json
{"built": true, "ran": true, "run_ok": true,
 "functional_ok": true, "functional_ok_no_o4": true,
 "terminal_check": "pass", "oracle_complete": true,
 "layers": {"O1": {"status": "pass", "category": null, "detail": null, "wall_ms": 12}}}
```

## Seeds

`python/skelnet/rusttools/seeds.py` fixes the oracle's Shuttle seed and a miri
seed range, and reserves a disjoint range for the round-4 feedback baselines:

- oracle Shuttle seed `0x5EED0001`; oracle miri seeds
  `0x5EED1000..0x5EED1010` (16 seeds).
- feedback Shuttle seed `0xF00D0001`; feedback miri seeds
  `0xF00D1000..0xF00D1040` (64 seeds).

Shuttle is made reproducible through `SHUTTLE_RANDOM_SEED` (honoured by both the
PCT and random schedulers). The generated `main` runs PCT as
`shuttle::Runner::new(shuttle::scheduler::PctScheduler::new(3, 2000), cfg)`
with `cfg.max_steps = MaxSteps::ContinueAfter(10_000)`, then
`shuttle::check_random(…, 2000)` with Shuttle's default `Config`
(`FailAfter(1_000_000)`). Iterations, depth and seeds are unchanged from round
3, and for a program that never reaches 10 000 steps the PCT schedules are the
ones `check_pct` explored.

PCT is deliberately unfair: a thread with the highest priority keeps being
picked, so a correct busy-wait (`while !flag.load(SeqCst) {}`) can spin until
the step bound. An iteration that exceeds 10 000 steps is therefore stopped
and discarded without a verdict. Random picks a runnable task uniformly at
every step, so exceeding its 1 000 000-step bound means the program would not
finish under a fair scheduler either (for example two workers wait on each
other forever while a third thread spins). That is `livelock`, not `deadlock`
(it is not a global deadlock; `partial_deadlock_bystander` pre-registers
`deadlock_free: PASS`) and not `panic`. The detail is Shuttle's
`exceeded max_steps bound …` line and `data["schedule"]` is parsed as usual.
The cost: a correct program whose executions exceed 10 000 steps loses PCT
coverage (random still explores it fully). The Shuttle half records
`pct_completed`, `random_completed` and `pct_abandoned` (= iterations −
completed PCT schedules; `null` when PCT did not finish or under
`no_concurrency`). They do not affect the verdict or `oracle_complete`;
calibration lists them per program as `o3_shuttle`.

O3 classifies from the **tool's** exit code and diagnostics. The one exception
is the terminal check: when the oracle checks the terminal line (not in
codegen mode, and only for tasks that have one), each schedule prints a marker
line after the program body (`__SKELNET_SHUTTLE_END_PCT__` /
`__SKELNET_SHUTTLE_END_RANDOM__`, preceded by a newline so a trailing `print!`
is still split off). The text before a marker is one completed schedule (a
residue after the last marker is dropped), and its last non-empty line must
equal the terminal line exactly (not stripped), as in O2. The first schedule
that differs makes the Shuttle half `fail` / `wrong_output`, with detail
`schedule <k>/<n> (<pct|random>): <line>` and `data["first_wrong"]`,
`schedules_checked`, `schedules_wrong`, `output_check` (`pass` / `fail` /
`no_schedules` / `not_run`). Output is never searched for keywords: a program
that prints `deadlock`/`panic` still passes.

A non-zero exit keeps its tool-derived category, in this order: Shuttle
`deadlock! blocked tasks` → `deadlock`, a timeout → `deadlock`,
`exceeded max_steps bound` → `livelock`, other panic → `panic`. Wrong schedules
seen before that failure are counted in `schedules_wrong` but do not change the
category. miri: `error: Undefined Behavior` → `ub`, `error: deadlock` →
`deadlock`, `the main thread terminated without waiting for all remaining
threads` → `thread_leak`, `panicked at` → `panic`. A program with no
concurrency makes Shuttle PCT assert `did not exercise any concurrency` after
one complete execution: that single schedule is still checked against the
terminal line (so O3 agrees with O2 on a sequential program), and when it
matches O3 is `pass` with `data["no_concurrency"] = true` (O4's thread count
decides). Exit code 0 without any marker (only fake runners do this) is
`pass` with `output_check: "no_schedules"`.

miri does not check output: `-Zmiri-many-seeds` runs the seeds in parallel and
interleaves their stdout, so a line cannot be attributed to a seed, and the
default preemption rate (0.01) did not expose the three lost-update defects in
16 seeds. When a half is `unsupported` (`shuttle_unsupported`/
`miri_unsupported`) the other half decides, with `oracle_complete = false`;
when both are unsupported O3 is `unsupported`.

On a Shuttle deadlock, livelock or panic the tool output (stderr, then stdout
without marker lines) is written to `<workdir>/shuttle/failure.txt` (kept
through cleanup) and the serialized `failing schedule` is recorded in
`data["schedule"]` for the round-4 dynamic baseline. On `wrong_output`,
`failure.txt` holds `output mismatch in schedule <k>/<n> (<scheduler>)`, the
expected and observed last lines (`repr`), and the first 40 lines of that
schedule's output; `data["schedule"]` is `null` (an output mismatch has no
Shuttle failing schedule). Marker lines are printed by the main task after the
body returns, so output from a thread still running after `main` would fall
into the next schedule; O1 requires every spawned thread to be joined.

## O4 resource mapping

The instrumented runtime's `sync` module aliases `MutexGuard` to its `Guard`,
and rewrites `use std::sync::MutexGuard` the same way as `Mutex` and `Condvar`,
so a signature that names `MutexGuard` still type-checks after instrumentation.

`concir-instrument` renames each concurrency object to a runtime-unique
`<binding>_<kind><n>#<site>` (e.g. `a_mutex0#86`, `t1#200`). The oracle derives
the alignment mapping automatically: strip the `#<site>` suffix and the
`_<kind><n>` counter to recover the binding, then match `main::<binding>` (or a
`::`-suffix match) in the contract's resources/functions. Unmatched names are
left out of the mapping, so the monitor reports them `unmapped`.

`design_loss` fires when:

- the number of worker threads actually started (the max over the traces of
  distinct non-`t0` tags vs `spawn` events) is **less than** the reference
  thread count computed from `gold.cir.json` (`scope` targets + `spawn` nodes),
  reported as `threads: <actual> < reference <ref>`; or
- the program builds **more** `Mutex`, `Condvar` or `Semaphore` sites than the
  reference design declares of the same type, reported as
  `extra_sync: <Kind> <have> > <want> (<sites>)`. Channel, `ChannelWrapper`,
  `RwLock`, `Barrier` and `Once` are not counted, because channels name their
  endpoints differently (`tx`/`rx`) and cannot be matched by name.

The count-based `extra_sync` rule is deliberately strict: it catches a mutant
that wraps all logic in one global lock, and it also fires when a program hand-
writes a semaphore out of a `Mutex`+`Condvar` while the reference declares a
`Semaphore`. Whether to relax it is the owner's call; the calibration report
lists every time it fires on a reference program.

A name-mapping miss is **not** a `design_loss`: it is reported by the monitor as
`unmapped`, and the unmapped program resources are recorded in the O4 result's
`data["unmapped_program_resources"]`.

The wrapper instrumenter recognizes `thread::spawn` / `std::thread::spawn`
in expression positions (including push arguments, returns, if/match branches,
iterator closures, other function bodies, and macro arguments that `syn` can
parse). Bare `spawn` calls require a visible `use std::thread::spawn` import
(including grouped imports and `std::thread::*`); local functions, bindings and
explicit imports can shadow a glob. A user function with that name is not a thread.
It also forwards `thread::scope` / `std::thread::scope` and imported `scope`,
and rewrites `.spawn` only on the lexical scope parameter. Nested scopes,
closures capturing that parameter, borrowed captures and joined return values
are supported. Each loop or iterator closure site has one Spawn resource with
optional `in_loop: true`; each execution records a fresh spawn event and thread
tag, while retaining the site's resource name. In an unparseable macro body,
recognized bare imported `spawn(...)` / `scope(...)` tokens are qualified as
`std::thread::spawn` / `std::thread::scope` and reported as limitations, so the
existing residual check yields `instrument_unsupported` instead of a false failure.

Spawn `display` names prefer the function path passed as the entry (using its
last segment), or the sole non-builtin function call in the closure,
then a direct `let` handle binding (including type annotations), then the first non-builtin function call,
then `spawn<k>` in file order starting at zero. Constructor/conversion/utility
calls such as `Arc::clone`, `new`, `default`, `from`, `into`, `with_capacity`,
`take`, `replace`, `swap`, `unwrap` and `expect` are not worker entries.
`name` remains `<display>#<site>`; optional `name_source` records `callee`,
`binding`, `first_call` or `index`, and optional `binding` retains the handle
name even when a unique callee wins. A binding to a method-chain result such as
`spawn(...).join()` is not a handle binding. Python mapping still uses the resource
name; it does not treat `binding` as an alias. Builder names are not supported
in this version (`Builder::spawn` and `Builder::spawn_scoped` are not rewritten).
Unknown/custom spawn methods and unparseable macro bodies remain limitations.
Nested std sync import groups are rewritten structurally. Wrapper types also
support Mutex/Condvar Debug, Mutex Default, try_lock, into_inner, get_mut,
is_poisoned, and Condvar wait_timeout/wait_timeout_while; successful try_lock
records a lock, failed try_lock records nothing, and each timed wait records
one condvar_wait with the existing event vocabulary.

When the annotated program still contains a spawn form the instrumenter does not
rewrite (`thread::spawn(`, a `.spawn(` method call, or `thread::scope`), the
instrumentation has not covered every thread. In that case `monitor_fail` and
the count-based `extra_sync` still fail, but a thread shortage, `not_observed`
and `unmapped` are reported as O4 `unsupported` / `instrument_unsupported` (the
residual forms are listed in `detail`, and `oracle_complete` is false). With a
residual spawn, O4 can be at best `unsupported` / `instrument_unsupported`, even
when every property passes.

Category priority when several fire: `monitor_fail` > `design_loss` >
`instrument_unsupported` > `unmapped` > `not_observed`; every triggered category
is also recorded in `data["categories"]`.

`concir-backend monitor` counts a `spawn` event as completion, so
`function_completed`-style properties are effectively guaranteed by O2 (the
process exits and joins); O4 only adds the observed-structure check.

Tasks without `contract.json` or `gold.cir.json` get O4 `not_run`.

## Tool installation

```bash
bash scripts/setup_oracle_tools.sh   # cargo fetch (Shuttle) + cargo miri setup
```

Shuttle `=0.8.1` lives in `tools/concir_sync_shuttle/` (outside the workspace;
the root `Cargo.toml` only adds `exclude = ["tools"]`, so `Cargo.lock` is
unchanged). The Shuttle project depends on
`concir_sync = { package = "concir_sync_shuttle", path = ... }`, so the generated
source keeps `use concir_sync::...`. `loom`, `lockbud` and `clippy` are out of
scope for this round.

## Calibration

```bash
python -m skelnet oracle calibrate --fixtures python/tests/fixtures/round03 \
    --out /tmp/cal --mutants
python -m skelnet oracle calibrate --tasks all --out /tmp/cal-all --report-only
```

`--tasks` is `all` or a comma-separated union of fnmatch patterns (the same
rule as `run` and `bench`). A pattern that matches nothing prints
`unmatched task patterns: ...` on stderr and exits 2 before the output
directory is created. `--fixtures` does not use `--tasks`.

For each task the reference `rust/fixed.rs` must pass and every `rust/buggy*.rs`
must fail (an optional `rust/expect.json` pins the expected layer/category).
With `--mutants`, three artificial mutants of `fixed.rs` (`print_only`,
`serialized`, `global_lock`) must also fail. The command writes
`CALIBRATION.json`/`CALIBRATION.md` and exits 1 on a mismatch unless
`--report-only`. Each program also records `first_fail_layer` (the first layer,
in O1–O4 order, whose status is `fail`), and the report lists
`shuttle_unsupported`, `instrument_unsupported`, `no_concurrency` and
`design_loss`.

`matched` means the expected layer failed with the expected category; it does
**not** require that layer to be the first to fail (a program may hang in O2 and
also deadlock in O3).

## Disk cleanup

After each cell the oracle deletes `<workdir>/target`, `<workdir>/shuttle/target`
and `<workdir>/o4/project/target`. Set `SKELNET_KEEP_TARGET=1` to keep them for
debugging.
