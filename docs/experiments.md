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

## Run layout

```
experiments/<run_id>/
  MANIFEST.json          # git sha, binary sha, prompt sha, model, params, seed
  audit.jsonl            # one record per real model call
  raw/                   # raw prompt/response text (optional)
  cells/<task>/<rep>/
    candidate_<n>.skel   # per-round artifacts
    candidate.rs         # final Rust
    result.json          # CellResult (history, ledger, oracle)
  SUMMARY.json
  REPORT.md
```

## Commands

```
python -m skelnet run  --arm SKEL --model <name> --tasks all|<glob> --reps 3 --rounds 4 --out experiments/<run_id>
python -m skelnet eval experiments/<run_id>          # external oracle, offline re-run
python -m skelnet report experiments/<run_id> [...]  # one table
python -m skelnet run --arm SKEL --tasks all --reps 3 --rounds 4 --dry-run
```

`--dry-run` prints the request budget and prompt shas and calls no model.

## Report columns

`report` prints one table over runs: arm × model — skeleton/CIR first-round
parse rate, check pass rate, verify PASS rate, mean revision rounds, Rust build
rate, functional correctness (RF), evidence sufficiency. Multiple run
directories can be compared in one call.

## Reproducibility

- `MANIFEST.json` records the git sha, binary sha, prompt sha256, model,
  parameters and seed.
- Prompts are content-addressed (`prompts.prompt_asset_record()`).
- `eval` re-runs the oracle on stored Rust without any model calls.
