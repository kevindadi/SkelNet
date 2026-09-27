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
have no terminal line.

The oracle records `terminal_check` as one of:

| value | meaning |
| --- | --- |
| `pass` | the terminal line appeared in stdout |
| `fail` | the program ran but the line did not appear |
| `absent` | the task has no terminal line; **never** counted as a pass |
| `not_applicable` | `check_terminal=False` (deterministic codegen mode) |
| `not_run` | the build failed or a step timed out |

It also records `run_ok` (built, exited 0, did not time out) in every mode, and
`functional_ok` (`run_ok` and `terminal_check == "pass"`; `null` in codegen
mode).

## Run layout

```
experiments/<run_id>/
  MANIFEST.json          # git sha + dirty, binary sha, prompt sha, model +
                         # model_id + channel, arm, rust_mode, tasks (pattern +
                         # selected), rounds, reps, seed (null until applied) +
                         # seed_applied, temperature, timeout, tool versions,
                         # started_at, ended_at (written at start, updated at end)
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
`skelnet codegen` (SKEL) or `concir-backend codegen` (CIR) instead. The
generated program prints nothing, so codegen mode is scored on whether the
verified design **builds and exits cleanly** (`terminal_check:
"not_applicable"`, `run_ok`), **not** on the functional output; it is therefore
not comparable to the LLM modes' `functional_ok`.

## Commands

```
python -m skelnet run  --arm SKEL --model <name> --tasks all|<glob> --reps 3 --rounds 4 --out experiments/<run_id>
python -m skelnet eval experiments/<run_id>          # external oracle, offline re-run
python -m skelnet report experiments/<run_id> [...]  # one table
python -m skelnet run --arm SKEL --tasks all --reps 3 --rounds 4 --dry-run
```

`--dry-run` prints the request budget and prompt shas and calls no model.
`--out` must be absent or empty. `--force` only clears a *previous run
directory* (one carrying a `MANIFEST.json`) and refuses to clear the repository,
the current directory, the home directory, the filesystem root, symlinks, or
their ancestors. A run directory is single-run, so `eval` rebuilds
`SUMMARY.json`/`REPORT.md` from the manifest's selected tasks and reps only.

## Report columns

`report` prints one table over runs, one row per run (first column is the run
id, then arm × model): cells, parse rate, check pass rate, verify pass rate,
mean revision rounds, evidence sufficiency, and functional pass rate. Multiple
run directories can be compared in one call.

- **parse rate**: first candidate parsed (SKEL: no `S0xx`; CIR: ConcIR JSON
  parsed; G0: non-empty Rust).
- **check pass rate**: SKEL: `skelnet check` passed on any attempt; CIR: any
  round returned a semantic result that is not `INVALID` (the same gate as
  SKEL's "passed check"); G0: the artifact was well-formed (same as parse).
- **verify pass rate**: `skelnet verify` / `concir explore` returned PASS.
  G0 has no verification stage, so its verify pass / evidence / mean rounds
  columns show `-`.
- **mean rounds**: mean generation attempts used (SKEL/CIR).
- **evidence**: `evidence_sufficient` (PASS with every property PASS).
- **run ok**: the oracle's `run_ok` (built, exited 0, no timeout).
- **functional pass**: the oracle's `functional_ok` (built, ran, and the
  terminal line matched). Cells whose `functional_ok` is `null` (codegen mode)
  are excluded from the denominator; when every cell is `null` the column shows
  `-`.

## Reproducibility

- `MANIFEST.json` records the git sha (+ dirty flag), binary sha256, prompt
  sha256, model/model_id/channel, arm, rust_mode, the task pattern and selected
  list, rounds/reps, temperature, timeout, tool versions, and start/end times.
  It is written at run start (`ended_at: null`) and updated at the end. `--seed`
  is recorded as `"seed": null` with `"seed_applied": false` until it actually
  takes effect.
- Prompts are content-addressed (`prompts.prompt_asset_record()`).
- `eval` re-runs the oracle on stored Rust without any model calls.
