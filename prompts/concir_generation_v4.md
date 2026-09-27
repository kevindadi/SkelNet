# ConcIR generation prompt (v4)

You propose one ConcIR program as a single JSON object. A separate checker
decides whether it is accepted. You may revise after feedback. You do not
verify, translate, or accept the program yourself. Output only the JSON object.

`sid` is per function and matches `^s[0-9]+$`. Every expression field (`expr`,
`cond`, `value`, `expected`, `desired`, each `args` element) is a JSON **string**,
never an object. Statements in a body run in order; a control-flow statement
jumps to the `sid` it names.

## What belongs in CIR

Model the concurrency structure, the shared state, the data conditions that
guard synchronization, and the behaviors named by the requirements: threads,
locks, condition variables, channels, semaphores, and the shared variables they
protect. Exact output text and formatting that the requirements mark as not
formally checked are implemented later in Rust; do not encode them as CIR calls.
There is no builtin `println`, `print`, or `io::println`; calling an undefined
function is a static error.

## Modules, params, locals

- A module has `name`, `provides`/`requires` (each `{"resources":[],"functions":[]}`),
  `resources`, `protection`, and `functions`. Resource and function FQNs are
  `module::name`.
- A parameter is `{"name","type","modeled"}`; a local is
  `{"name","type","modeled","init"}`. `type` is `Int` or `Bool`. `modeled: true`
  means the checker tracks the value. Parameters and locals have no `base`.
- `base` and `init` appear only on `Var`, `Atomic`, and `Channel` resources.

## Resources

| type | fields |
| --- | --- |
| Mutex | `name`, `kind`=`sync`, `type`=`Mutex`, `mode`=`Sync` |
| Condvar | `name`, `kind`=`sync`, `type`=`Condvar`, `mode`=`Sync` |
| Semaphore | those, plus optional `count` (initial permits) |
| Channel | those, plus `base` and `capacity` |
| Var / Atomic | `name`, `kind`=`var`, `type`, `base`, `init` |

A `Var` written under a lock needs `protection`: `{"var": "<var>", "lock": "<lock>"}`.

## Statements (complete list)

| kind | required fields | notes |
| --- | --- | --- |
| `mutex_lock` / `mutex_unlock` | `resource` | Mutex FQN |
| `condvar_wait` | `condvar`, `lock` | releases `lock` while waiting, reacquires it on wake |
| `condvar_notify` / `condvar_notify_all` | `condvar` | wake one / all waiters |
| `semaphore_acquire` | `resource`, optional `count` (default 1) | blocks while fewer than `count` permits are free |
| `semaphore_release` | `resource` | returns one permit |
| `channel_send` | `channel`, `value` | `value` is an expression string |
| `channel_recv` | `channel`, `dst` | `dst` is a local or `"_"` |
| `read_shared` | `resource` | read a `Var`/`Atomic` |
| `write_shared` | `resource`, `expr` | write a `Var`/`Atomic` |
| `atomic_load` | `resource`, `dst` | |
| `atomic_store` | `resource`, `value` | |
| `atomic_cas` | `resource`, `expected`, `desired`, `dst` | `dst` receives the observed value |
| `assign_local` | `target`, `expr` | write a declared local |
| `call` | `func`, optional `args`, optional `dst` | `args` is an array of strings |
| `spawn` | `func`, `handle`, optional `args` | start a thread |
| `join` | `handle` | wait for the spawned thread |
| `scope` | `funcs` (array of function FQNs) | structured spawn+join of all listed functions |
| `branch` | `cond`, `then`, `else` | `then`/`else` are `sid`s in the same function |
| `goto` | `target` | a `sid` in the same function |
| `return` | optional `value` | ends the function |

Do **not** emit `rwlock_*`, `select`, `async_call`, `await`, `abstract_step`, or
`seq_hole`: the Rust target and runtime do not implement them faithfully.

## Semantics you must respect

- **Lock order.** Acquire locks in one consistent order across all threads.
- **Wait loop.** `condvar_wait` must sit inside a loop guarded by a predicate on
  the shared state, and the notify must happen under the lock that the waiter
  reacquires; otherwise the wakeup can be lost. Model the loop with `branch` and
  `goto`.
- **Control flow.** `branch`/`goto` targets are `sid`s of statements in the same
  function; make sure every loop has a reachable exit so the function returns.
- **Semaphore / Permit.** `semaphore_acquire` takes `count` permits (default 1);
  `semaphore_release` returns one. A permit released twice, or acquired without a
  matching release, changes the modeled count.
- **Channels.** `channel_send` and `channel_recv` name the same channel FQN; the
  runtime maps the sender and receiver endpoints of one constructed channel to
  that resource. A rendezvous is a `Channel` with `capacity` 0.
- **Resources.** Use the exact entity names from the requirements. A `Var`
  written by more than one thread under a lock must be listed in `protection`.

## Example 1: bounded loop with an explicit exit (branch + goto)

```json
{
  "program": "bounded_loop",
  "version": "3.5.0",
  "entry": "main::main",
  "modules": [
    {"name": "main",
     "provides": {"resources": ["m"], "functions": ["main", "w"]},
     "requires": {"resources": [], "functions": []},
     "resources": [{"name": "m", "kind": "sync", "type": "Mutex", "mode": "Sync"}],
     "protection": [],
     "functions": [
       {"name": "w", "kind": "normal", "form": "closure",
        "locals": [{"name": "i", "type": "Int", "modeled": true, "init": 0}],
        "body": [
          {"sid": "s1", "kind": "mutex_lock", "resource": "main::m"},
          {"sid": "s2", "kind": "branch", "cond": "i < 3", "then": "s3", "else": "s5"},
          {"sid": "s3", "kind": "assign_local", "target": "i", "expr": "i + 1"},
          {"sid": "s4", "kind": "goto", "target": "s2"},
          {"sid": "s5", "kind": "mutex_unlock", "resource": "main::m"},
          {"sid": "s6", "kind": "return"}
        ]},
       {"name": "main", "kind": "normal",
        "body": [
          {"sid": "s1", "kind": "scope", "funcs": ["main::w"]},
          {"sid": "s2", "kind": "return"}
        ]}
     ]}
  ]
}
```

## Example 2: predicate-guarded condition-variable wait

```json
{
  "program": "condvar_wait",
  "version": "3.5.0",
  "entry": "main::main",
  "modules": [
    {"name": "main",
     "provides": {"resources": ["m", "cv", "ready"], "functions": ["main", "waiter", "notifier"]},
     "requires": {"resources": [], "functions": []},
     "resources": [
       {"name": "m", "kind": "sync", "type": "Mutex", "mode": "Sync"},
       {"name": "cv", "kind": "sync", "type": "Condvar", "mode": "Sync"},
       {"name": "ready", "kind": "var", "type": "Var", "base": "Bool", "init": false}
     ],
     "protection": [{"var": "ready", "lock": "m"}],
     "functions": [
       {"name": "waiter", "kind": "normal", "form": "closure",
        "body": [
          {"sid": "s1", "kind": "mutex_lock", "resource": "main::m"},
          {"sid": "s2", "kind": "branch", "cond": "ready == true", "then": "s5", "else": "s3"},
          {"sid": "s3", "kind": "condvar_wait", "condvar": "main::cv", "lock": "main::m"},
          {"sid": "s4", "kind": "goto", "target": "s2"},
          {"sid": "s5", "kind": "mutex_unlock", "resource": "main::m"},
          {"sid": "s6", "kind": "return"}
        ]},
       {"name": "notifier", "kind": "normal", "form": "closure",
        "body": [
          {"sid": "s1", "kind": "mutex_lock", "resource": "main::m"},
          {"sid": "s2", "kind": "write_shared", "resource": "main::ready", "expr": "true"},
          {"sid": "s3", "kind": "condvar_notify", "condvar": "main::cv"},
          {"sid": "s4", "kind": "mutex_unlock", "resource": "main::m"},
          {"sid": "s5", "kind": "return"}
        ]},
       {"name": "main", "kind": "normal",
        "body": [
          {"sid": "s1", "kind": "scope", "funcs": ["main::waiter", "main::notifier"]},
          {"sid": "s2", "kind": "return"}
        ]}
     ]}
  ]
}
```

## Example 3: a call with parameters and a local

```json
{
  "program": "call_with_args",
  "version": "3.5.0",
  "entry": "main::main",
  "modules": [
    {"name": "main",
     "provides": {"resources": [], "functions": ["main", "step"]},
     "requires": {"resources": [], "functions": []},
     "resources": [], "protection": [],
     "functions": [
       {"name": "step", "kind": "normal",
        "params": [{"name": "n", "type": "Int", "modeled": true}],
        "locals": [{"name": "tmp", "type": "Int", "modeled": true, "init": 0}],
        "body": [
          {"sid": "s1", "kind": "assign_local", "target": "tmp", "expr": "n + 1"},
          {"sid": "s2", "kind": "return", "value": "tmp"}
        ]},
       {"name": "main", "kind": "normal",
        "body": [
          {"sid": "s1", "kind": "call", "func": "main::step", "args": ["1"]},
          {"sid": "s2", "kind": "return"}
        ]}
     ]}
  ]
}
```

## Example 4: a channel with a sender and a receiver

```json
{
  "program": "channel_one_value",
  "version": "3.5.0",
  "entry": "main::main",
  "modules": [
    {"name": "main",
     "provides": {"resources": ["ch"], "functions": ["main", "sender", "receiver"]},
     "requires": {"resources": [], "functions": []},
     "resources": [{"name": "ch", "kind": "sync", "type": "Channel", "mode": "Sync",
                    "base": "Int", "capacity": 0}],
     "protection": [],
     "functions": [
       {"name": "sender", "kind": "normal", "form": "closure",
        "body": [
          {"sid": "s1", "kind": "channel_send", "channel": "main::ch", "value": "1"},
          {"sid": "s2", "kind": "return"}
        ]},
       {"name": "receiver", "kind": "normal", "form": "closure",
        "body": [
          {"sid": "s1", "kind": "channel_recv", "channel": "main::ch", "dst": "_"},
          {"sid": "s2", "kind": "return"}
        ]},
       {"name": "main", "kind": "normal",
        "body": [
          {"sid": "s1", "kind": "scope", "funcs": ["main::sender", "main::receiver"]},
          {"sid": "s2", "kind": "return"}
        ]}
     ]}
  ]
}
```

Use the entity names from the requirements. Resend the whole program after
feedback.
