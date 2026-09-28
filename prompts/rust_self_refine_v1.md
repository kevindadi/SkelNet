# Rust self-review prompt (v1)

You are reviewing a Rust program you wrote for a concurrency specification.
Look for concurrency defects: deadlock, lost wakeup, permanent blocking, and
lock-order cycles. If you find one, output a complete corrected program. If
you are sure the program has none, reply with exactly `NO_ISSUES` and nothing
else.

Do not remove synchronization, and do not serialize the program, to hide a
defect.

<!-- format-rules -->
Rules:

- Exactly one file, to be compiled as a binary crate. It must define `fn main`.
- Use only the Rust standard library and the already-linked `concir_sync` crate. No other crates, no `unsafe`, and no `#![feature]`.
- Do not use `sleep`, `yield_now`, timing, or environment-dependent behavior to dodge a concurrency problem.
- Join every spawned thread so `main` terminates, and print the task's required terminating line.
- Output the whole program inside a single ```rust code fence. No prose outside the fence.
<!-- /format-rules -->
