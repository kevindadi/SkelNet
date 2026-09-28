# Independent oracle (v2)

Every arm's final Rust is scored by one arm-agnostic four-layer oracle. The
layers are independent: a program can pass the build and still fail schedule
exploration, and each layer's result is recorded separately.

## Layers

| Layer | What it checks | Failure categories |
| --- | --- | --- |
| **O1** build & policy | `cargo build` (std + `concir_sync` only); policy scan: no `unsafe`, `static mut`, `thread::sleep`/`yield_now`, `process::exit`/`abort`, `extern crate`, `#![feature]`, or crates other than `std`/`core`/`alloc`/`concir_sync`/`crate`/`self`/`super`/local `mod` | `no_build` / `policy_violation` |
| **O2** termination & output | run the built binary `R=20` times (10 s watchdog each); every exit code 0, and the **last non-empty line equals** the expected terminal line | `hang` / `crash` / `wrong_output` / `no_output` |
| **O3** schedule exploration | Shuttle (`check_pct` + `check_random`) with the oracle's reserved seed, plus miri multi-seed | `deadlock` / `panic` / `thread_leak` / `ub`; `shuttle_unsupported` / `miri_unsupported` |
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
PCT and random schedulers). `check_pct` runs `iterations=2000`, `depth=3`;
`check_random` runs `iterations=2000`.

O3 classifies from the **tool's** exit code and diagnostics, never from the
program's own output: a program that prints `deadlock`/`panic` still passes.
Only a non-zero exit is classified (Shuttle `deadlock! blocked tasks` →
`deadlock`, other panic → `panic`; miri `error: Undefined Behavior` → `ub`,
`error: deadlock` → `deadlock`, `the main thread terminated without waiting for
all remaining threads` → `thread_leak`, `panicked at` → `panic`). A program with
no concurrency makes Shuttle PCT assert `did not exercise any concurrency`: this
is recorded as O3 `pass` with `data["no_concurrency"] = true` (there is nothing
to explore; O4's thread count decides). When a half is `unsupported`
(`shuttle_unsupported`/`miri_unsupported`) the other half decides, with
`oracle_complete = false`; when both are unsupported O3 is `unsupported`.

On a Shuttle failure the full output is written to
`<workdir>/shuttle/failure.txt` (kept through cleanup) and the serialized
`failing schedule` is recorded in `data["schedule"]` for the round-4 dynamic
baseline.

## O4 resource mapping

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

When the annotated program still contains a spawn form the instrumenter does not
rewrite (`thread::spawn(`, a `.spawn(` method call, or `thread::scope`), the
instrumentation has not covered every thread. In that case `monitor_fail` and
the count-based `extra_sync` still fail, but a thread shortage, `not_observed`
and `unmapped` are reported as O4 `unsupported` / `instrument_unsupported` (the
residual forms are listed in `detail`, and `oracle_complete` is false).

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
