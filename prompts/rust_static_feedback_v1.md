# Rust static-feedback prompt (v1)

The feedback below comes from rustc diagnostics, a fixed set of concurrency
clippy lints, and lockbud. These tools can report false positives. Do not
remove synchronization, and do not serialize the program, just to silence a
diagnostic.

<!-- format-rules -->
Rules:

- Exactly one file, to be compiled as a binary crate. It must define `fn main`.
- Use only the Rust standard library and the already-linked `concir_sync` crate. No other crates, no `unsafe`, and no `#![feature]`.
- Do not use `sleep`, `yield_now`, timing, or environment-dependent behavior to dodge a concurrency problem.
- Join every spawned thread so `main` terminates, and print the task's required terminating line.
- Output the whole program inside a single ```rust code fence. No prose outside the fence.
<!-- /format-rules -->
