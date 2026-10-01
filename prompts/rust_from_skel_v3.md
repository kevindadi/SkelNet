# Rust from skeleton — prompt (v3)

Write one std-only single-file Rust program that implements the skeleton.

## Hard rules

- Use the skeleton's resource names and function names as Rust identifiers
  (same names). A mutex `m` becomes a `Mutex`/`Arc<Mutex<..>>`; a condvar `cv`
  becomes a `Condvar`; a semaphore `s` becomes `concir_sync::Semaphore`.
- `lock m { ... }` becomes a guard scope:
  `{ let _g = m.lock().unwrap(); ... }`.
- `permit s { ... }` becomes `let _p = s.acquire();` held for the block.
- `s.post()` / `s.take()` use `concir_sync` (`Semaphore::post` / `take`).
- `ch.send(e)` / `ch.recv()` use a std `mpsc`-style or a small channel with the
  declared capacity; `c.load()`/`store`/`cas` use `std::sync::atomic`.
- Fill each `compute "description"` hole with the sequential logic that
  description calls for.
- Preserve requirement comments: keep `// @Rn` on the statements they came from.
- `concir_sync` is already linked; do not declare a module for it.

## Policy rules (the same as every Rust generation prompt)

- Only the standard library and the already-linked `concir_sync` crate. No other
  crates, no `unsafe`, no `static mut`, no `#![feature]`, no `extern crate`.
- Do not use `sleep`, `yield_now`, `process::exit`, `process::abort`, timing, or
  environment-dependent behavior to dodge a concurrency problem. Coordination
  must come from synchronization primitives.
- Keep a busy-wait a busy-wait: translate `loop { if flag == true { break; } }`
  to `while !flag.load(Ordering::SeqCst) {}` (or the equivalent), and never add
  `sleep`/`yield_now`.

## Threads and `scope`

- Translate `scope { spawn f(); spawn g(); }` to: create each thread with
  `std::thread::spawn` (worker functions receive their shared `Arc` handles as
  arguments), then call `join` on every handle, in the order the `spawn`s
  appear, before the scope block ends.
- Do **not** use `std::thread::scope` (or `thread::Builder`): the schedule
  explorer does not support scoped threads, and the reference programs do not
  use them.

## Output format

Output **one** fenced ```` ```rust ```` code block and nothing else.
