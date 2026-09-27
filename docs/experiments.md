# Experiments

## Arms

| arm | pipeline |
| --- | --- |
| `G0` | requirements → LLM writes Rust directly (baseline). |
| `SKEL` | requirements → LLM writes `.skel` → `skelnet check/verify` (contract hidden) → remapped feedback → revise (≤ N rounds) → accepted skeleton + requirements → LLM writes Rust. |
| `CIR` | as `SKEL`, but the LLM writes ConcIR JSON directly. |

All arms' final Rust is scored by the same `python/skelnet/oracle.py`. The
skeleton/CIR verification evidence is recorded separately (`evidence.py`) and
never mixed into the code score. `G1`/`G2` are not migrated; they can be
restored later if needed.

## Prompts (arm × stage)

Each `(arm, stage)` maps to an **ordered tuple** of system-prompt assets
(`prompts.py::PROMPT_ROUTES`); the tuple is joined with the fixed separator
`"\n\n---\n\n"`. The feedback stage carries the generation template first (the
model still needs the DSL grammar / ConcIR schema) and the feedback-reading
template second:

| arm | generate | feedback | rust |
| --- | --- | --- | --- |
| `SKEL` | `skel_generation_v1.md` | `skel_generation_v1.md` + `skel_feedback_v1.md` | `rust_from_skel_v1.md` |
| `CIR` | `concir_generation_v4.md` | `concir_generation_v4.md` + `concir_feedback_v1.md` | `rust_from_cir_v2.md` |
| `G0` | `rust_generation_v1.md` | — | — |

A missing route raises; the workflow never falls back to another arm's prompt.
`--dry-run` prints, per stage, the ordered asset list, each asset's sha256, and
the concatenated `system_sha256`.

## Terminal line

The required terminating stdout line is read from
`benchmarks/tasks/<task>/requirements.json["terminal"]` (e.g.
`"DONE t1=1 t2=1"`). Tasks without a `requirements.json` (the boundary tasks)
have no terminal line. The oracle records `terminal_check` as `"pass"`,
`"fail"`, or `"absent"`; `"absent"` is **never** counted as a pass.

## Run layout

```
experiments/<run_id>/
  MANIFEST.json          # git sha + dirty, binary sha, prompt sha, model, arm,
                         # rounds, reps, seed, temperature, start/end time
  audit.jsonl            # one record per real model call (real cell/task/rep)
  raw/                   # raw prompt/response text (optional)
  cells/<task>/<rep>/
    candidate_<n>.skel   # per-round artifacts
    candidate.rs         # final Rust
    cir_trace.rs         # deterministic-codegen runtime, when --rust-mode codegen
    result.json          # CellResult (history, ledger, oracle, metrics)
  SUMMARY.json
  REPORT.md
```

`--rust-mode codegen` skips the Rust LLM call after a PASS and uses
`skelnet codegen` (SKEL) or `concir-backend codegen` (CIR) instead.

## Commands

```
python -m skelnet run  --arm SKEL --model <name> --tasks all|<glob> --reps 3 --rounds 4 --out experiments/<run_id>
python -m skelnet eval experiments/<run_id>          # external oracle, offline re-run
python -m skelnet report experiments/<run_id> [...]  # one table
python -m skelnet run --arm SKEL --tasks all --reps 3 --rounds 4 --dry-run
```

`--dry-run` prints the request budget and prompt shas and calls no model.

## Report columns

`report` prints one table over runs, one row per run (first column is the run
id, then arm × model): cells, parse rate, check pass rate, verify pass rate,
mean revision rounds, evidence sufficiency, and functional pass rate. Multiple
run directories can be compared in one call.

- **parse rate**: first candidate parsed (SKEL: no `S0xx`; CIR: ConcIR JSON
  parsed; G0: non-empty Rust).
- **check pass rate**: SKEL: `skelnet check` passed on any attempt; CIR/G0:
  the artifact was well-formed (same as parse).
- **verify pass rate**: `skelnet verify` / `concir explore` returned PASS.
- **mean rounds**: mean generation attempts used (SKEL/CIR).
- **evidence**: `evidence_sufficient` (PASS with every property PASS).
- **functional pass**: the oracle's `functional_ok` (built, ran, and the
  terminal line matched).

## Reproducibility

- `MANIFEST.json` records the git sha, binary sha, prompt sha256, model,
  parameters and seed.
- Prompts are content-addressed (`prompts.prompt_asset_record()`).
- `eval` re-runs the oracle on stored Rust without any model calls.
