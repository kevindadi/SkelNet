# Per-cell result schema (`skelnet-cell-v1`)

Every `experiments/<run>/cells/<task>/<rep>/result.json` is validated against
this schema by `python/skelnet/schema.py::validate_cell` before it is written.
A validation failure is a program bug and aborts the run.

```json
{
  "schema_version": "skelnet-cell-v1",
  "arm": "SKEL", "model": "DeepSeek Flash", "model_id": "deepseek-flash",
  "task": "lock-order/abba_2lock", "tier": null, "hint": "h0",
  "rep": 0, "seed": 123456789,
  "status": "ok", "skip_reason": null, "error": null,
  "accepted": true, "parse_ok": true, "check_ok": true, "rounds_used": 2,
  "history": [], "ledger": {}, "evidence_sufficient": true, "rust_mode": "llm",
  "calls": [
    {"attempt": 1, "stage": "generate", "system_sha256": "...",
     "request_sha256": "...", "cache_hit": false, "transport_attempt": 1,
     "truncation_retry": false, "finish_reason": "stop",
     "finish_reasons": ["length", "stop"],
     "usage": {"input": 1200, "output": 800, "reasoning": 300, "cached": null},
     "wall_ms": 4210, "error": null}
  ],
  "budget_used": {"calls": 2, "tokens": 2000},
  "oracle": {
    "built": true, "ran": true, "run_ok": true,
    "functional_ok": true, "functional_ok_no_o4": true,
    "terminal_check": "pass", "oracle_complete": true,
    "layers": {
      "O1": {"status": "pass", "category": null, "detail": null, "wall_ms": 12},
      "O2": {"status": "pass", "category": null, "detail": null, "wall_ms": 8},
      "O3": {"status": "pass", "category": null, "detail": null, "wall_ms": 4},
      "O4": {"status": "unavailable", "category": "no-monitor", "detail": "x",
             "wall_ms": null}
    }
  }
}
```

- `status`: `ok` | `error` | `skipped`. `skip_reason` is
  `no_requirements_text` for boundary tasks.
- `calls`: one entry per **logical** call. `transport_attempt` counts bounded
  retries (A4); `truncation_retry` marks the larger-cap retry (A6). Transport and
  truncation retries do not consume the cell call budget. `finish_reasons` is the
  ordered per-attempt finish reason (required; length 1 without a truncation
  retry), while `finish_reason` is the final one. A call that fails with
  `transport_truncated` still records its per-attempt `usage` and
  `finish_reasons` (so its tokens count against `budget_used` and the global
  ledger).
- `budget_used`: logical calls and billable tokens (`input + output`). Chat
  `completion_tokens` and Responses `output_tokens` already include reasoning, so
  `reasoning` is counted only when `output` is absent; it is still recorded
  separately in `usage`.
- `oracle`: the shared format used by the independent oracle (round 3). The
  optional `functional_ok_no_o4`, `oracle_complete` and `layers` keys are
  accepted when present; `layers` status is one of
  `pass|fail|unsupported|unavailable|not_run`; each layer's `category`/`detail`
  are `str|null` and `wall_ms` is `int|null`.

### Oracle sub-tool fields (round 8)

`oracle.o3_tools` (`object|null`) exposes the two halves of O3, which
`_combine_o3` keeps in the O3 layer's `data` but does not otherwise write to
`result.json`:

```json
{"shuttle": {"status": "pass|fail|unsupported|unavailable|not_run|null",
             "category": "str|null"},
 "miri":    {"status": "…", "category": "…"},
 "no_concurrency": false}
```

When O3 did not run (O1 failed, O3 disabled, or an older run recorded before
round 8) the key is `null`; readers must fall back to parsing the O3 `detail`
text for `no concurrency to explore` and `shuttle_unsupported`.  The value is
taken verbatim from the O3 layer's `data` and changes no decision logic:
`functional_ok` and the layer statuses are unaffected.

### SKEL/CIR method fields (round 5)

Present on SKEL/CIR cells (G0 and the round-4 baselines may omit them):

- `skel_verified` (`bool|null`): the skeleton stage ended on `PASS ∧ complete`.
- `skel_status` (`str|null`): the last skeleton's outcome (`PASS`/`FAIL`/
  `UNKNOWN`/`INVALID`/`UNSUPPORTED`/`check_failed`/`no_candidate`).
- `rust_compiled` (`bool|null`): the final Rust version compiled.
- `rust_calls` (`int`), `rust_attempts` (`list` of
  `{call, stage, reply_kind, compiled, compile}`), `rust_skipped` (`str|null`,
  one of
  `no_candidate`/`skeleton_invalid`/`codegen_failed`/`unverified`/`no_program`).
- `feedback_mode`, `rust_when_unverified`, `property_ids` (`str|null`): the
  method knobs recorded in `run_params`.

`accepted` for SKEL/CIR means **the skeleton verified AND the final Rust
compiled** (`skel_verified ∧ rust_compiled`), independent of the oracle.
`rounds_used` counts skeleton-stage calls; total calls are `budget_used.calls`.
`status` only says whether the orchestration errored: an `ok` cell may still
carry an `error` (e.g. `cell_budget_exhausted`, `transport_truncated`,
`compile_unavailable`, `compile_timeout`).

Each `rust_attempts[]` entry's `compile` is `"ok"`/`"error"` for a compiled
reply, `"unavailable"`/`"timeout"` when the compiler could not run, and `null`
when the reply was not a program. When `compile` is `unavailable`/`timeout` the
Rust stage stops immediately (`rust_compiled=null`), the cell error is
`compile_unavailable`/`compile_timeout`, and the oracle still scores the latest
Rust version.

Codegen mode (`--rust-mode codegen`) reports only `run_ok` and the layer
statuses: both `functional_ok` and `functional_ok_no_o4` are `null`.

### Tool timing fields (round 9a)

Optional, checked only when present. Each value is an `int` or `null`, in
milliseconds. A string such as `"12"` is rejected. `bool` is not an int.

- SKEL/CIR `history[]` check and verify items: `wall_ms`.
- `rust_attempts[]`: `compile_wall_ms` (`null` when that attempt did not compile).
- G0 cells: top-level `compile_wall_ms`.
- Baseline `rounds[]`: `compile_wall_ms`.
- Baseline `rounds[].tools.clippy`, `rounds[].tools.lockbud`, and the DYNAMIC
  tool slices: `wall_ms`.
