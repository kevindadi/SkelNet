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
| `SKEL` | `skel_generation_v1.md` | `skel_generation_v1.md` + `skel_feedback_v1.md` | `rust_from_skel_v1.md` + `rust_runtime_api_v1.md` |
| `CIR` | `concir_generation_v4.md` | `concir_generation_v4.md` + `concir_feedback_v1.md` | `rust_from_cir_v2.md` + `rust_runtime_api_v1.md` |
| `G0` | `rust_generation_v2.md` + `rust_runtime_api_v1.md` | — | — |

`rust_runtime_api_v1.md` is the current `concir_sync` public API. A missing
route raises; the workflow never falls back to another arm's prompt. `--dry-run`
prints, per stage, the ordered asset list, each asset's sha256, and the
concatenated `system_sha256`.

## Model parameters

The four experimental models are GPT 6 Luna (`gpt-6-luna`, OpenCode Responses,
`OPENCODE_API_KEY`, reasoning effort `medium`), Kimi (`kimi-k3`, Moonshot direct
Chat Completions, `MOONSHOT_API_KEY`, reasoning effort `high`), DeepSeek Flash
(`deepseek-flash`, direct) and Qwen (`qwen3.8-flash`, DashScope direct). Kimi no
longer runs through the OpenCode gateway: it uses the owner's own Moonshot key
against `https://api.moonshot.cn/v1`. `kimi-k3` always reasons, so no `thinking`
key is sent; its strength is the request's top-level `reasoning_effort`. That
Kimi's effort differs from GPT's is the owner's decision, not a provider
requirement. DeepSeek and Qwen are unchanged.

All four run with thinking enabled; no temperature is sent
(`provider_default`); each cell is capped at 5 calls / 200k tokens; one output
is capped at 32768 tokens (retry cap 65536). Kimi's `reasoning_content` is
recorded separately and never merged into the reply text.

`RunParams` (in the MANIFEST as `run_params`) fixes the temperature policy,
seed policy, per-cell call/token budgets, max output tokens and hint.
`--temperature` is only accepted with `--temperature-policy fixed`. The
`models probe --dry-run` command lists each model's policy and whether its key
is present (never the value); `--env-file` selects the dotenv file to load
(defaults to the repository `.env`).

A real probe also sends one nontrivial concurrency question
(`PROBE_NONTRIVIAL_USER`, correct answer `YES`) at the model's default effort,
and, for models that take a reasoning effort (Kimi and GPT), once more at
`low`. The record stores `reasoning_tokens_nontrivial`,
`nontrivial_answer_ok`, `nontrivial_output_tokens`, and
`reasoning_tokens_nontrivial_low` when the low call ran. GPT's Responses
channel also stores `responses_reasoning_echo` (the `reasoning` object echoed
on the response, or null), `responses_reasoning_items` (output items whose
`type` is `reasoning`), `responses_output_tokens_details`, and
`responses_reasoning_summary_present` from one extra probe-only request that
sets `reasoning.summary` to `"auto"`. Experiment runs never send `summary`.

`reasoning_diagnosis` reads the nontrivial call:

| value | meaning |
| --- | --- |
| `model_reasons` | `reasoning_tokens_nontrivial` > 0 |
| `gateway_dropped_reasoning_param` | tokens are 0 and the Responses echo is null or has no effort |
| `reasoning_not_reported_or_not_used` | tokens are 0 and the echo still carries an effort |
| `no_reasoning_observed` | a Chat channel reported 0 reasoning tokens and no `reasoning_content` |
| `probe_error` | the probe call failed |

## Terminal line

The required terminating stdout line is read from
`benchmarks/tasks/<task>/requirements.json`. With `--hint h0` the `terminal`
field is used; otherwise `terminal_v2` is preferred when present (falling back
to `terminal`). `read_terminal`'s own default argument is `h1` so tooling that
does not pass a hint uses the v2 line once it exists. Tasks without a
`requirements.json` (the boundary tasks) have no terminal line.

`run --hint` defaults to `params.DEFAULT_HINT` (currently `h0`). The argparse
default is unset; `_run_params` reads the constant when the command runs, so
round 9 changes the protocol default by editing `DEFAULT_HINT` to `h1` and
nothing else. MANIFEST and `--dry-run` record `hint_source` as `explicit` or
`default`. Before any model call, a non-boundary task that lacks
`REQUIREMENTS.md` (h0) or `REQUIREMENTS.h1.md` (h1) aborts the run and lists
the tasks. `--dry-run` does not abort: it lists them in `requirements_missing`
and exits 0. Boundary tasks stay skipped. `--stage` 1, 2, or 3 requires hint
`h1` (plan D10) unless `--allow-nonprotocol-hint` is set, which records
`hint_override: true`. `eval` of a MANIFEST with no `hint` uses
`params.LEGACY_HINT` (`h0`) and does not follow a later change of
`DEFAULT_HINT`.

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
                         # model_policy + model_id + channel, arm, rust_mode,
                         # hint, stage, run_params, budget_file, cache_dir,
                         # replay_from, tasks (pattern + selected), rounds,
                         # reps, temperature, timeout, tool versions,
                         # started_at, ended_at, status
  audit.jsonl            # one record per real model call (real cell/task/rep)
  raw/                   # raw prompt/response text (optional)
  cache/                 # response cache for this run
  cells/<task>/<rep>/
    candidate_<n>.skel   # per-round artifacts
    candidate.rs         # final Rust
    cir_trace.rs         # deterministic-codegen runtime, when --rust-mode codegen
    result.json          # skelnet-cell-v1 (see docs/result-schema.md)
  SUMMARY.json
  REPORT.md
```

`MANIFEST.json` is written at run start with `status: "running"` and updated to
`"complete"` (or `"budget_exhausted"`) at the end.

`--rust-mode codegen` skips the Rust LLM call after a PASS and uses
`skelnet codegen` (SKEL) or `concir-backend codegen` (CIR) instead. The
generated program prints nothing, so codegen mode is scored on whether the
verified design **builds and exits cleanly** (`terminal_check:
"not_applicable"`, `run_ok`), **not** on the functional output; it is therefore
not comparable to the LLM modes' `functional_ok`.

## Commands

```
python -m skelnet run  --arm SKEL --model <name> --tasks all|<glob>[,<glob>...] --reps 3 --rounds 4 --out experiments/<run_id>
python -m skelnet eval experiments/<run_id>          # external oracle, offline re-run
python -m skelnet report experiments/<run_id> [...]  # one table
python -m skelnet models probe --dry-run             # key presence + policy, no calls
python -m skelnet run --arm SKEL --tasks all --reps 3 --rounds 4 --dry-run
```

`--tasks` for `run`, `oracle calibrate`, and `tools fp-check` matches `bench`:
`all`, or a comma-separated union of fnmatch patterns, in directory order.
If any pattern matches nothing, the command prints
`unmatched task patterns: ...` on stderr and exits 2 without creating the
output directory (`run --dry-run` included). `oracle calibrate --fixtures`
still reads that directory and does not use `--tasks`. MANIFEST
`tasks.pattern` keeps the raw string; `tasks.selected` is the union.

`--dry-run` prints the request budget and prompt shas and calls no model.
`--out` must be absent or empty. `--force` only clears a *previous run
directory* (one carrying a `MANIFEST.json`) and refuses to clear the repository,
the current directory, the home directory, the filesystem root, symlinks, or
their ancestors. A run directory is single-run, so `eval` rebuilds
`SUMMARY.json`/`REPORT.md` from the manifest's selected tasks and reps only.

## Report columns

Each run's `REPORT.md`/`SUMMARY.json` still carries the legacy single-run table
described below.  The formal cross-run analysis is produced by
`python -m skelnet report <run_dirs...> --table …` (round 8), which writes the
paper tables, the anytime figure, and `report.json`; see
[`docs/report.md`](report.md) for the tables, the statistics, and the
`stop-check` stopping rules.

`report` (with no `--table`, `--figure`, or `--out`) prints one legacy table
over runs, one row per run (first column is the run id, then arm × model):
cells, parse rate, check pass rate, verify pass rate, mean revision rounds,
evidence sufficiency, and functional pass rate. Multiple run directories can be
compared in one call.

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
  sha256, model policy (`model_policy`) and ids, arm, rust_mode, hint, stage,
  `run_params`, the budget/cache/replay settings, the task pattern and selected
  list, rounds/reps, temperature, timeout, tool versions, and start/end times.
  It is written at run start (`status: "running"`) and updated at the end.
- Per-cell seeds are derived as `seed_for(task, rep)` and sent only to models
  whose registry entry sets `supports_seed` (Responses never send a seed).
- Prompts are content-addressed (`prompts.prompt_asset_record()`).
- The global request/token ledger (`--budget-file`, default
  `experiments/budget.json`) accumulates across restarts; `--stage` separates
  budgets. Limits live in the ledger file under `limits.<stage>`
  (`max_requests`, `max_tokens`) and are read on load; every real request
  (including transport and truncation retries) reserves before it is sent.
  Per-cell call/token budgets are enforced before each logical call.
- The cache key is the sha256 of the request identity: model, system/user
  prompts, `task`, `rep`, the always-computed `seed_for(task, rep)`, the
  per-cell logical `call_index`, temperature policy/value, max output tokens,
  thinking and reasoning effort. It deliberately excludes arm/stage so a
  byte-identical first-round request (call_index 1) still hits across arms with
  a shared `--cache-dir`.
- `--cache-dir` shares responses across runs; `--replay-from` replays a run
  directory or a cache directory without any network call. Cache hits count as a
  logical call but not against the global spend.
- `--replay-mode key` (the default) looks up the request hash. It only
  reproduces a run when tool results are reproducible: DYNAMIC and DYNAMIC_M
  feed native stress output back into the next prompt, and a hang that appears
  on one machine changes that prompt, so the hash misses. `--replay-mode
  sequence` (requires `--replay-from`) ignores the request text and returns the
  reply recorded at `(model_id, arm, task, rep, call_index)`. A different
  request still returns that reply and sets `calls[].replay_mismatch` to true.
  A cache recorded before round 9a has no `sequence/` index; sequence mode then
  exits with `replay cache has no sequence index (recorded before round 9a)`.
- `--resume` reuses a run directory, skipping cells that already have a
  `result.json`, and requires matching arm/model/tasks/reps/rounds/RunParams.
- `eval` re-runs the oracle on stored Rust without any model calls.

## SKEL/CIR method rules (round 5)

- **Budget.** A cell may make at most `--call-budget` LLM calls. The skeleton
  stage gets `min(rounds, call_budget - 1)` calls (so at least one is left for
  Rust); the Rust stage uses the rest. `_budget` reports the per-arm request
  totals: G0 = 1, SKEL/CIR codegen = `min(rounds, call_budget-1)`, SKEL/CIR llm
  and every round-4 baseline = `call_budget`.
- **Skeleton acceptance (K5).** A skeleton is accepted only on `PASS ∧ complete`.
  If the skeleton never verifies but a candidate exists, the last non-empty
  skeleton still drives the Rust stage (`--rust-when-unverified last`, the
  default); `--rust-when-unverified skip` records `rust_skipped="unverified"`.
  The cell records `skel_verified=false` and `accepted=false`.
- **Rust stage.** Generate once, then, whenever the program does not compile,
  retry the same `rust_fix` stage (same system prompt, the rustc diagnostics)
  until it compiles or the budget runs out. A reply without a program keeps the
  previous version and repeats the stage with a format-retry note. The final
  Rust is the latest version (even if it does not compile) and is scored by the
  oracle.
- **Compiler unavailable / timeout (shared with round 4).** If `cargo` cannot
  run (`unavailable`), the compile times out (`timed_out`), or cargo exits
  non-zero without any compiler error, the Rust stage stops immediately with no
  further LLM call: the attempt records `compile: "unavailable"`/`"timeout"`,
  `rust_compiled=null`, and the cell error is `compile_unavailable`/
  `compile_timeout`. The latest Rust version is still scored by the oracle.
  Only a real compiler error triggers `rust_fix`.
- **`check_ok`.** SKEL: `check` was semantically valid on any round. CIR: the
  explorer returned a semantic result that is neither `INVALID` nor
  `UNSUPPORTED`.
- **Codegen.** `--rust-mode codegen` needs the last skeleton to pass `check`;
  otherwise the cell records `rust_skipped="skeleton_invalid"`. It reports
  `run_ok` and the layer statuses only (`functional_ok` and
  `functional_ok_no_o4` are `null`).
- **`feedback_mode`** (`full`/`outcome_only`/`nocex`/`nomap`) trims the
  verification-stage feedback only; the check stage is never trimmed. See
  `docs/feedback.md`.
- **Cache.** Within one cell the skeleton, `rust` and `rust_fix` calls have
  consecutive call indices, so no two hit each other. `--replay-from` replays a
  whole cell (including `rust_fix`) with zero network calls, and `--resume`
  re-runs an interrupted cell from the cache. A shared `--cache-dir` lets the
  byte-identical first call of SKEL and `--feedback-mode outcome_only` hit the
  same entry (a paired design), while SKEL/CIR/G0 never share (different system
  prompts).
