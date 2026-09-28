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
  retry), while `finish_reason` is the final one.
- `budget_used`: logical calls and billable tokens (`input + output`). Chat
  `completion_tokens` and Responses `output_tokens` already include reasoning, so
  `reasoning` is counted only when `output` is absent; it is still recorded
  separately in `usage`.
- `oracle`: the shared format used by the independent oracle (round 3). The
  optional `functional_ok_no_o4`, `oracle_complete` and `layers` keys are
  accepted when present; `layers` status is one of
  `pass|fail|unsupported|unavailable|not_run`.
