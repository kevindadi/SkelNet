# Skeleton DSL — generation prompt (v1)

You write a **Skeleton DSL** (`.skel`) file, not Rust. The skeleton is a small,
Rust-flavoured, block-structured description of a concurrent design. It is
mechanically lowered to ConcIR and verified against a hidden contract; you will
receive remapped feedback and may revise.

## Syntax (authoritative subset)

```
skeleton <name>;

mutex m;                          // lock
condvar cv for m;                 // condition variable bound to one mutex
semaphore s = 2;                  // counting semaphore (initial permits >= 0)
channel ch: Int cap 0;            // cap 0 = rendezvous, n >= 1 = bounded buffer
shared x: Bool = false guarded_by m;   // protected variable
atomic c: Int[0..=2] = 0;         // atomic with a value domain

fn main() { scope { spawn worker(); } }     // entry is always main::main

fn worker() {
    lock m {                      // lexical scope: leaving the block releases
        while ready == false { cv.wait(); }
    }
    permit s { compute "work"; }  // RAII semaphore
    s.take();                     // P (acquire, no return)
    s.post();                     // V (release)
    ch.send(1);                   // value ops are method calls
    let v = ch.recv();
    c.store(2);
    let old = c.cas(v, v + 1);
    cv.notify_one();
    cv.notify_all();
}
```

Rules:

- **Locks are lexically scoped.** There is no `unlock`: `lock m { ... }`
  releases `m` when the block ends, including on `return`/`break`/`continue`.
- A `condvar` is bound to exactly one mutex at declaration; `cv.wait()` is only
  legal inside `lock <that mutex> { ... }`.
- Expressions are a small subset: integers, `true`/`false`, names, `+ - * / %`,
  one comparison (`== != < <= > >=`). There is **no** `&&`, `||`, or `!`; use
  nested `if`.
- Only `Bool`, `Int`, and `Int[lo..=hi]` types exist. No structs, floats,
  strings, `Arc`, `async`, `select`, `rwlock`, or `unlock`.
- `compute "description";` marks a sequential hole to be filled in the Rust
  stage. It has no concurrent effect.
- Tag statements/items with `@Rn` to trace requirements.

## Output format

Output **one** fenced ```` ```skel ```` code block and nothing else.

## Examples (not from the benchmark)

### Example A — ordered locks, three resources

```
skeleton pipeline;

mutex in_lock;
mutex mid_lock;
mutex out_lock;

@R1
fn main() { scope { spawn producer(); spawn consumer(); } }

@R2
fn producer() {
    lock in_lock {
        lock mid_lock {
            compute "stage the record";
        }
    }
}

@R3
fn consumer() {
    lock mid_lock {
        lock out_lock {
            compute "emit the record";
        }
    }
}
```

### Example B — condvar predicate loop with a separate flag

```
skeleton gate;

mutex gate_lock;
condvar gate_cv for gate_lock;
shared open: Bool = false guarded_by gate_lock;

@R1
fn main() { scope { spawn waiter(); spawn opener(); } }

@R4
fn waiter() {
    lock gate_lock {
        while open == false { gate_cv.wait(); }
    }
}

@R3
fn opener() {
    lock gate_lock {
        open = true;
        gate_cv.notify_all();
    }
}
```
