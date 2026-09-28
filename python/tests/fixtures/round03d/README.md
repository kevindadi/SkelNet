# Round 3d instrumentation fixtures

The `contract.json`, `gold.cir.json` and `requirements.json` files are byte-for-byte
copies from commit `9dfaefec459f494a8c7e57938df606c8f5873466`:

- `abba_2lock`: `benchmarks/tasks/lock-order/abba_2lock/` (also the round03 fixture contract).
- `nested_scope_lock_order`: `benchmarks/tasks/structure/nested_scope_lock_order/`.

The Rust programs are new coverage fixtures. Their terminal lines match
`cli.read_terminal` for their respective task directories. `loop3.rs` deliberately
uses `worker` instead of the required `t1`/`t2`, so O4 reports `not_observed` while
recording all three workers. All other fixtures are expected to pass O4.
The tests also derive expression, import, loop and scope variants in `tmp_path`.
