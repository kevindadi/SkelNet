# ConcIR feedback prompt (v1)

The previous candidate failed. Revise the ConcIR program for the **same**
requirements; the original requirements are authoritative. The verification
feedback below is context for the repair, not a new specification. Never weaken
the requirements, remove preserved behaviour, or rename properties to make the
failure disappear.

Output only the revised JSON object. No prose, no markdown fences.

## Feedback fields

- `stage`: `check` or `explore`.
- `outcome`/`status`: the backend's actual value. `UNKNOWN`, `UNSUPPORTED`,
  process errors and timeouts are **not** "no defect".
- `failed_properties`: the property id, outcome, detail and the requirement ids
  it maps to. `preserved: ...` ids are preservation goals.
- `diagnostics`: static errors with codes and mapped positions when `stage` is
  `check`.
- `counterexamples`: an interleaved table; use the concrete statement ids and
  resource names to locate the concurrent defect.

Fix the concurrent defect (for example a lock-order inversion) rather than
deleting the synchronization or the preserved behaviour.
