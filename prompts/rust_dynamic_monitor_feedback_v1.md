# Rust dynamic-and-monitor feedback prompt (v1)

The feedback below comes from repeated native runs, Shuttle schedule
exploration (PCT and random), and miri. A failing Shuttle schedule is one real
interleaving of the program, not a guess.

It also comes from a monitor that checks the instrumented execution trace
against the structural requirements in the specification. A property `id` names
one requirement. `kind` is the kind of requirement. `not_observed` means the
runs never showed the behaviour that requirement asks for. `unmapped` means the
program does not contain an entity named by the requirement. `FAIL` on a safety
property means the runs violated it.

<!-- format-rules -->
Rules:

- Exactly one file, to be compiled as a binary crate. It must define `fn main`.
- Use only the Rust standard library and the already-linked `concir_sync` crate. No other crates, no `unsafe`, and no `#![feature]`.
- Do not use `sleep`, `yield_now`, timing, or environment-dependent behavior to dodge a concurrency problem.
- Join every spawned thread so `main` terminates, and print the task's required terminating line.
- Output the whole program inside a single ```rust code fence. No prose outside the fence.
<!-- /format-rules -->
