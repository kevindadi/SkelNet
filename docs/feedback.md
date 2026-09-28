# Verification feedback and disclosure

`skelnet check` and `skelnet verify` run the ConcIR validator/explorer and map
everything back to Skeleton DSL positions through the source map. Feedback is
what an LLM sees while revising a skeleton; it is also the artifact recorded in
Python run cells.

## Mapping

- ConcIR `location` (`module::function.sid`) and `path`
  (`modules[i].functions[j].body[k]`) → the source-map statement, giving the DSL
  `line`/`col`, `construct` and `reqs`.
- `cir_statements`, `blocked`, `doom_state.threads[].at_sid` and
  `counterexample_names` are translated the same way.
- A `StepLabel` origin (`function`, `sid` index) is resolved through the lowered
  program to a DSL statement.
- Anything that cannot be mapped keeps its original text and is flagged
  `unmapped: true`. The gold suite and the P3/P5 tests require `unmapped == 0`.

## Disclosure policy

Feedback may contain: property id, outcome, detail, the property's `req` ids,
the counterexample, blocked/holds state, `complete`, boundary events and
diagnostics with mapped positions.

Feedback **never** contains the contract's `goal` formulas or the contract file.
Both feedback builders (`build_explore_feedback` for SKEL and
`build_cir_feedback` for CIR) share `prompts.sanitize_detail`:

- a property whose id starts with `preserved:` always gets the fixed detail
  `"preserved behaviour is not reachable in any explored schedule"`;
- any other `detail` containing `holds_all(`, `completed(`,
  `function_completed` or `goal` is replaced with a neutral text.

The property **id** is kept unchanged by default (`--property-ids keep`). With
`--property-ids opaque` every occurrence of a property id (in
`failed_properties[].id`, `preserved_unmet[].id`, `counterexamples[].property`
and SKEL `diagnostics[].property`/`message`) is replaced by a stable `P<n>`
within the cell. `test_feedback_disclosure.py` asserts the rendered feedback has
no `goal`, `function_completed`, `holds_all`, or `completed(` in every mode.

## Feedback modes

`--feedback-mode` trims the verification-stage feedback (the check stage is
never trimmed):

- `full` (default): unchanged.
- `outcome_only`: only `stage`, `outcome`, `complete` and the failed property
  ids (no details, counterexamples or diagnostics).
- `nocex`: drop `counterexamples`, keep the rest.
- `nomap`: drop the mapped DSL positions (`line`/`col`/`skel`/`statement`) and
  keep only the raw ConcIR location (`concir_loc`, e.g. `main::main::s1`). CIR
  feedback is already ConcIR-positioned, so `nomap` equals `full` there.

## CIR fairness

- `failed_properties[].reqs` is filled from the contract's `req` field (by
  property id, including the `preserved: <description>` form); no other contract
  field (`goal`, `kind`, `bounds`, …) ever enters the feedback.
- `repair_hints` are never provided to CIR (SKEL has no equivalent), so the two
  arms see the same information.
- CIR candidates are **not normalised**: the bytes written to
  `candidate_<k>.cir.json` are exactly the extracted reply.

## `--json` schema

`skelnet check --json`:

```json
{"valid": true, "unmapped": 0, "diagnostics": [], "support_error": null}
```

`skelnet verify --json` (see `python/skelnet/prompts.py` for the full shape):

```json
{
  "outcome": "FAIL", "complete": true,
  "properties": [{"id": "no-deadlock", "outcome": "FAIL", "detail": "...", "reqs": ["R4"]}],
  "counterexamples": [{
    "property": "no-deadlock", "reqs": ["R4"],
    "steps": [{"step": 1, "thread": 0, "function": "main::t1",
               "skel": {"loc": "main::t1::s1", "line": 10, "col": 14, "reqs": ["R2"]},
               "statement": "lock a { lock b { } }"}],
    "final_note": "T0 holds [main::a] waits mutex main::b; T1 holds [main::b] waits mutex main::a"
  }],
  "diagnostics": [], "unmapped": 0
}
```

## Counterexample rendering

```
counterexample (property no-deadlock, requirements R4 R5):
  step thread fn                 line  statement
  1    T0     main::t1           10    lock a { lock b { } }
  2    T1     main::t2           13    lock b { lock a { } }
final: T0 holds [main::a] waits mutex main::b; T1 holds [main::b] waits mutex main::a
```

Every step carries a DSL line number. The renderer does not print the contract
goal. (The plan's per-step "holds after" column is not recoverable from a
ConcIR `StepLabel`; the `final:` line summarises holds/waits from `doom_state`.)

## Worked example

For `benchmarks/tasks/lock-order/abba_2lock/gold.skel` with the two workers
locking in the same order, `skelnet verify` reports `PASS` with all properties
PASS and `unmapped == 0`. Swapping `t2` to `lock b { lock a { } }` makes
`no-deadlock` FAIL; the feedback lists a counterexample whose steps point at
lines 10 and 13 of the skeleton.
