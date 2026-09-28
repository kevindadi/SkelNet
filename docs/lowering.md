# Lowering to ConcIR and the source map

`skelnet lower <f.skel> -o <f.cir.json> --map <f.map.json>` lowers a checked
skeleton to a ConcIR program (`version` `"3.5.0"`) and a source map. The
lowering is a **total function**: any skeleton that passes the front-end checks
produces JSON and never panics. The lowerer does no optimisation.

## General rules

- Each function body gets dense sids `s1..sn` in emission order; jump targets
  are backpatched.
- No dead statements: an implicit `return` is appended only when the fallthrough
  point is reachable (e.g. `loop {}` with no `break` gets none).
- Resource references in ops use FQNs (`main::m`). In expression strings,
  same-module resources and locals are bare; cross-module resources are FQNs.
- `provides` = the module's resources and functions; `requires` = referenced
  cross-module resources/functions (sorted, deduped).
- All resources have `mode: "Sync"` except `var`/`atomic` resources (no mode).
- Functions targeted by `scope`/`spawn` get `form: "closure"`.

## Mapping table

| DSL | ConcIR |
| --- | --- |
| `mutex m;` | `{"name":"m","kind":"sync","type":"Mutex","mode":"Sync"}` |
| `condvar cv for m;` | `{"kind":"sync","type":"Condvar","mode":"Sync"}` (binding kept in source map + front-end) |
| `semaphore s = 2;` | `{"type":"Semaphore","count":2,...}` |
| `channel ch: Int cap 0;` | `{"type":"Channel","base":"Int","capacity":0,...}` |
| `shared x: Bool = false guarded_by m;` | var `{"kind":"var","type":"Var","base":"Bool","init":false}` + `protection [{"var":"x","lock":"m"}]` |
| `atomic c: Int[0..=2] = 0;` | `{"kind":"var","type":"Atomic","base":{"Int":[0,2]},"init":0}` |
| `lock m { B }` | `mutex_lock m`; B; `mutex_unlock m` |
| `permit s { B }` | `semaphore_acquire s`; B; `semaphore_release s` |
| `s.take();` / `s.post();` | `semaphore_acquire s` / `semaphore_release s` |
| `cv.wait();` | `condvar_wait {condvar, lock: bound mutex}` |
| `cv.notify_one();` / `cv.notify_all();` | `condvar_notify` / `condvar_notify_all` |
| `ch.send(e);` | `channel_send {value: e}` |
| `let v = ch.recv();` / `ch.recv();` | `channel_recv {dst:"v"}` / `{dst:"_"}` |
| `let v = c.load();` | `atomic_load {dst: v}` |
| `c.store(e);` | `atomic_store {value: e}` |
| `let r = c.cas(e1, e2);` | `atomic_cas {expected, desired, dst: r}` (dst = old value) |
| `x = e;` (shared) | `write_shared {resource: x, expr: e}` |
| `x = e;` / `let x = e;` (local) | `assign_local` |
| `let v = x;` (shared) | `read_shared {dst: v}` |
| `f(a);` / `let r = f(a);` | `call {func, args, dst?}` |
| `let h = spawn f(a);` / `h.join();` | `spawn {func, args, handle: h}` / `join {handle: h}` |
| `scope { spawn f(); spawn g(); }` | `scope {funcs: [f, g]}` |
| `if c {A} else {B}` | `branch c then→A首 else→B首`; A末 `goto` join |
| `while c {B}` | head `branch c then→B首 else→exit`; B; `goto` head |
| `loop {B}` | B; `goto` B首 |
| `break;` / `continue;` | `goto` exit / `goto` head |
| `return e;` | `return {value: e}` |
| `extern fn f();` | function `f`, empty body |
| `compute "d" reads(..) writes(..);` | `nop`, source-map construct `compute` (see below) |

Local variables: each `let` produces a `locals` entry with `modeled: true`;
the type is the explicit annotation or inferred from the rvalue (`load`/`cas`
use the atomic base, `recv` the channel base, bounded `Int` widens to `Int`).
`let _ = ...` produces no local.

### `compute` → `nop` (deliberate deviation)

A `compute "d"` hole is the sequential computation the Rust stage fills in; it
has no concurrent effect, so it lowers to ConcIR's supported, semantics-neutral
`nop` (the plan's `seq_hole` is UNSUPPORTED in ConcIR `a35dc86`, so emitting it
would make every skeleton containing a hole unverifiable). The DSL front-end
rejects any `compute` footprint that names a shared resource (`S110`), so a
hole's `reads`/`writes` can only mention locals. `nop` is therefore a sound
abstraction for synchronization semantics; the cost is that a hole's effect on
local data is invisible in the model.

The source-map entry keeps the hole visible as `construct: "compute"`; the
description and footprint themselves are not carried into the map. See
`benchmarks/DEVIATIONS.json`.

## Early exits (§5.3)

`return`/`break`/`continue` that cross `lock`/`permit` blocks emit the matching
`mutex_unlock`/`semaphore_release` **before** the jump, inside-out, each marked
`construct: "implicit_release_on_exit"` with `span` = the triggering statement
and `block_span` = the owning block.

## Source map (`*.map.json`)

```json
{
  "skel_sha256": "...", "cir_sha256": "...", "file": "task.skel",
  "stmts": [
    {"loc": "main::waiter::s3", "construct": "condvar_wait",
     "span": {"line":12,"col":9,"end_line":12,"end_col":19},
     "block_span": null, "reqs": ["R4","R6"]},
    {"loc": "main::waiter::s5", "construct": "lock_exit",
     "span": {"line":14,"col":5,"end_line":14,"end_col":6},
     "block_span": {"line":12,"col":5,"end_line":14,"end_col":6}, "reqs": ["R4"]}
  ],
  "functions": {"main::waiter": {"span": {...}, "reqs": []}},
  "resources": {"main::m": {"span": {...}}, "main::cv": {"span": {...}, "bound_mutex": "main::m"}},
  "json_paths": {"modules[0].functions[1].body[2]": "main::waiter::s3", "modules[0].resources[0]": "main::m"}
}
```

`construct` values: `lock_enter, lock_exit, permit_enter, permit_exit,
implicit_release_on_exit, branch_if, branch_while, loop_back, break, continue,
implicit_return, return, compute`, the operation names from the mapping table,
`function`, and `resource`. `reqs` = the statement's own tags ∪ all enclosing
block tags ∪ the function tags.
