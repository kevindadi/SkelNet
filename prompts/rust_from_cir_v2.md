# Rust from a verified ConcIR design (v2)

You write one Rust program that implements a verified ConcIR design. The
checker decides whether the program is accepted. Output only the Rust source
inside one ```rust fence.

## Authority

The ConcIR design is authoritative for threads, resources, and the order of
synchronization and shared-state updates. Use the same function and resource
names. The requirement document supplies payload formatting and the exact
terminal line. If they disagree about synchronization, follow the CIR.

## Libraries

`std` and the already-linked crate `concir_sync` are allowed. Write
`use concir_sync::Semaphore;` when the design has a semaphore. Do not write
`mod concir_sync` and do not implement a semaphore yourself. Do not use
`std::sync::Semaphore` or `Semaphore::release`; neither exists.

Semaphore API, matching the linked crate:

- `Semaphore::new(n) -> Arc<Semaphore>`
- `acquire(&self) -> Permit` (blocks until a permit is available)
- `try_acquire(&self) -> Option<Permit>`
- `Permit::release(self)` consumes the permit and releases it early
- dropping a `Permit` also releases it once

A CIR `semaphore_acquire` is `acquire`. A CIR `semaphore_release` is either
`permit.release()` or the permit leaving scope. Do not acquire an extra permit
or drop one twice to manufacture events.

Other primitives:

- `Mutex` and `Condvar` from `std::sync`
- `std::sync::mpsc::{channel, sync_channel}` for channels; capacity 0 is rendezvous
- `std::sync::atomic` for CIR atomics
- `std::thread::spawn` plus `join`

Do not mention `cir_trace` and do not declare `mod cir_trace`. Instrumentation
is applied later by the checker.

## Correspondence

- One CIR function is one Rust function. The entry scope starts the threads it names.
- One CIR mutex, condvar, channel, or semaphore is one primitive with that name.
  Do not add a primitive the CIR does not have.
- A CIR `var` lives in the mutex named by its protection edge, or in a local.
  Do not add a new lock for it.
- `condvar_wait` is `while !predicate { guard = cv.wait(guard) }` under the paired mutex.
- After joins, `main` may read shared state only to print the required terminal line.

## Rules

- One file, `fn main`, no `unsafe`, no `#![feature]`.
- Do not make the program sequential and do not delete a critical section.
- Do not use `sleep` or `yield_now` to dodge synchronization.
- Join every spawned thread. Print the terminal line from the requirements.
