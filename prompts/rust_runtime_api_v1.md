# Rust runtime API (v1)

Generated Rust may use **only** the standard library and the already-linked
`concir_sync` crate. Do not declare `mod concir_sync` and do not implement a
semaphore yourself. The program must print the task's required terminating line
and then exit.

```rust
use concir_sync::Semaphore;
```

## `Semaphore`

- `Semaphore::new(n: i64) -> Arc<Semaphore>` — `n` initial permits.
- `Semaphore::new_named(name: &'static str, n: i64) -> Arc<Semaphore>` — same,
  with a name used by instrumentation.
- `Semaphore::acquire(&self) -> Permit<'_>` — blocks until a permit is
  available, then takes one. Dropping the returned `Permit` releases it.
- `Semaphore::try_acquire(&self) -> Option<Permit<'_>>` — non-blocking.
- `Semaphore::take(&self)` — the P operation: blocks until a permit is
  available and consumes it permanently (it is not returned on drop).
- `Semaphore::post(&self)` — the V operation: adds one permit.

There is no `Semaphore::release`.

## `Permit`

- `Permit::release(self)` — releases the permit early (consumes it).
- `Permit::forget(self)` — consumes the permit **without** releasing it.

Releasing by simply dropping the `Permit` is equally valid. Never release the
same permit twice.
