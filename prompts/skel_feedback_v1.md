# Skeleton DSL — feedback prompt (v1)

You receive remapped verification feedback for your previous skeleton. The
feedback contains only what the verifier observed; it never contains the
contract's goal formulas or the contract file.

## What you get

- `outcome`: `PASS` / `FAIL` / `UNKNOWN` / `INVALID` / `UNSUPPORTED`.
- `failed_properties`: property id, outcome, detail, and the requirement ids
  (`reqs`) that property maps to. `preserved: ...` ids are preservation goals.
- `diagnostics`: each has the property, severity, message, and a `skel` position
  (line/column) in your skeleton, plus `reqs`.
- `counterexamples`: an interleaved table; every step has a DSL `line` and the
  skeleton `statement` text. Use the line numbers to find the statement to fix.
- `unmapped`: must be 0; if not, the feedback could not be mapped.

`UNKNOWN` means the analysis did not complete — it is **not** a proof of safety.

## What to do

1. Read the failing property and its `reqs`; match them to your `@Rn` tags.
2. Use the counterexample line numbers to locate the statements involved
   (e.g. an inconsistent lock order, a missing predicate loop, an unbalanced
   semaphore).
3. Revise the skeleton and output the complete corrected ```` ```skel ```` block.

Do not weaken requirements or change the contract; you cannot see it.
