# concir_sync

Standard-library-only counting semaphore used by the SkelNet generation
harness. Generated cargo projects depend on it by path so the model can write
`use concir_sync::Semaphore;` without declaring a module.

- `Semaphore::new(n)` / `new_named(name, n)` (returns `Arc<Self>`)
- `acquire()` -> `Permit` (drop releases), `try_acquire()`,
  `permit.release()` (consume to release early), `permit.forget()` (consume
  without releasing)
- `Semaphore::take()` -> blocking P: acquire one permit and never return it
- `Semaphore::post()` -> V: add one permit
- there is no `Semaphore::release`

`acquire`/`post`/`take` call a recorder installed via `set_recorder`; the
generated `cir_trace` runtime installs its `record` function, so semaphore
operations appear as `sem_acquire`/`sem_release` events. The crate contains no
tracing itself and builds standalone.
