# Error codes

## Skeleton front-end (`S###`)

| code | severity | meaning |
| --- | --- | --- |
| S001 | error | lexical error (bad character, unterminated string, bad escape, int overflow) |
| S002 | error | out-of-subset construct, with a hint |
| S003 | error | syntax error (expected token set) |
| S101 | error | undefined name / function / handle |
| S102 | error | duplicate definition (module/resource/function/parameter/local) |
| S103 | error | resource kind / operation mismatch |
| S104 | error | `cv.wait()` outside the `lock` of the mutex it is bound to |
| S105 | error | `break`/`continue` outside a loop |
| S106 | error | `scope` spawn target is not a `fn` |
| S107 | error | `.join()` on a non-spawn handle |
| S108 | error | literal/type mismatch, bounded `Int` initializer out of range, bad arity |
| S109 | error | invalid tag (not `R<n>`) |
| S201 | warning | requirement id has no `@R` annotation (only with `--reqs`) |
| S202 | warning | `@R<n>` references an unknown requirement id (only with `--reqs`) |

Rendering is rustc-style with a caret and an optional `= hint:` line; `--json`
emits `{code, severity, message, span, hint, origin, concir_code?}`.

## ConcIR (`E###`/`W###`)

The full ConcIR code table is in [`docs/concir/error_codes.md`](concir/error_codes.md).
SkelNet does not re-implement ConcIR checks; their diagnostics are remapped to
DSL positions and tagged `origin: "concir"`. Common ones seen through the
feedback channel include E309 (protected variable accessed without its lock),
E401 (spawned handle not joined, warning), E605 (non-terminating loop),
E114 (empty function body, warning).

## Exit codes (`skelnet`)

| code | meaning |
| --- | --- |
| 0 | pass |
| 1 | diagnostics error / verification failure (FAIL/UNKNOWN/INVALID/UNSUPPORTED) |
| 2 | usage or IO error |
