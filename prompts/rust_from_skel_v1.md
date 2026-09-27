# Rust from skeleton — prompt (v1)

Write one std-only single-file Rust program that implements the verified
skeleton.

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
- No other crates; no `async`, `select`, `rwlock`, or `unsafe`.

## Output format

Output **one** fenced ```` ```rust ```` code block and nothing else.
