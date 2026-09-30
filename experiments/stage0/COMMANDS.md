# Stage 0 — model/runs smoke (run by Kevin, on his machine)

Stage 0 is the pre-experiment smoke run. It is the only stage executed in round
9; Stage 1–3 wait for the protocol to be frozen and for this smoke to pass.
Every command below runs from the repository root and uses the venv Python with
`python/` on the path. No real work is done by the executor; these commands are
run by the owner.

The frozen protocol is `experiments/protocol.json` (see `experiments/PROTOCOL.md`).
Stage 0 uses `--stage 0 --hint h1` explicitly, four L1 tasks, six main groups and
one `DYNAMIC_M` smoke (100 cells total). The ledger ceiling is
`max_requests=800` / `max_tokens=15000000`.

## 0. Prepare the budget ledger (once)

The ledger is git-ignored. Do not overwrite an existing one.

```sh
[ -f experiments/budget.json ] && cp experiments/budget.json experiments/budget.json.bak
[ -f experiments/budget.json ] || cp experiments/stage0/budget.template.json experiments/budget.json
cat experiments/budget.json
```

Expected: the `limits."0"` block with `max_requests=800` and
`max_tokens=15000000`, and an empty `stages` object. **Stop** if an existing
`experiments/budget.json` already has non-zero `stages."0"` counts (a previous
run already spent budget): inspect the backup before continuing.

## 1. Environment and tool checks

```sh
cargo build --workspace --offline
bash scripts/setup_oracle_tools.sh
bash scripts/setup_lockbud.sh
PYTHONPATH=python python -m skelnet protocol check
PYTHONPATH=python python -m skelnet models probe --dry-run
```

Expected: `cargo build` finishes with no warnings; `protocol check` prints
`protocol check: ok` and exits 0; `models probe --dry-run` lists the four models
and `api_key_present: true` for each (it never prints a key value). **Stop** if
`protocol check` exits non-zero, or if any model shows `api_key_present: false`.

## 2. Real model probe

```sh
PYTHONPATH=python python -m skelnet models probe --out experiments/stage0/probe
```

Expected: `experiments/stage0/probe/PROBE.json` with four `probed: true`
records. For GPT check `reasoning_diagnosis`; for every model note
`reasoning_tokens_nontrivial` and `nontrivial_answer_ok` (the answer must be
`YES`). **Stop** if a model reports `probe_error` or `nontrivial_answer_ok` is
false; report the model and the diagnosis.

## 3. GPT reasoning smoke (G0 and SKEL, one task)

The smoke runs go to `experiments/stage0-smoke/`, a separate directory from the
step-4 runs, so the step-5 glob `experiments/stage0/*-*/` never sees them (the
same `(model, arm, task, rep)` would otherwise appear twice and make
`stop-check` / `report` reject the input as duplicates).

```sh
PYTHONPATH=python python -m skelnet run --arm G0 --model "GPT 6 Luna" --tasks lock-order/abba_2lock --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0-smoke/gpt-g0
PYTHONPATH=python python -m skelnet run --arm SKEL --model "GPT 6 Luna" --tasks lock-order/abba_2lock --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0-smoke/gpt-skel
```

Then inspect the two cells:

```sh
PYTHONPATH=python python - <<'PY'
import json, glob
for path in glob.glob("experiments/stage0-smoke/*/cells/**/result.json", recursive=True):
    cell = json.load(open(path))
    for call in cell.get("calls", []):
        print(path, call["stage"], (call.get("usage") or {}).get("reasoning"))
PY
```

Expected: at least one call with `usage.reasoning > 0` (GPT's reasoning tokens
are reported). **Stop and hand back to the coordinator** if every reasoning
count is 0: the gateway may be dropping the `reasoning` parameter, and the
coordinator decides whether to accept (and write it into the paper) or switch
channels.

## 4. The Stage-0 runs (4 models, serial)

Four tasks (the same list frozen in `protocol.json`):

```sh
TASKS='lock-order/abba_2lock,condvar/lost_wakeup_notify_before_wait,atomic-data/atomic_lost_update,lock-order/partial_deadlock_bystander'
```

Run the four models **serially** (the ledger is now file-locked, but serial
runs are easier to interrupt). For each model: `G0` first (it fills the shared
cache), then `REFINE`, `STATIC`, `DYNAMIC` replaying that cache
(`--first-round require-cache`), then `SKEL`, `CIR`, and the `DYNAMIC_M` smoke.

### GPT 6 Luna

```sh
PYTHONPATH=python python -m skelnet run --arm G0 --model "GPT 6 Luna" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --out experiments/stage0/gpt-g0
PYTHONPATH=python python -m skelnet run --arm REFINE --model "GPT 6 Luna" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/gpt-refine
PYTHONPATH=python python -m skelnet run --arm STATIC --model "GPT 6 Luna" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/gpt-static --allow-missing-tools
PYTHONPATH=python python -m skelnet run --arm DYNAMIC --model "GPT 6 Luna" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/gpt-dynamic --allow-missing-tools
PYTHONPATH=python python -m skelnet run --arm SKEL --model "GPT 6 Luna" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0/gpt-skel
PYTHONPATH=python python -m skelnet run --arm CIR --model "GPT 6 Luna" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0/gpt-cir
PYTHONPATH=python python -m skelnet run --arm DYNAMIC_M --model "GPT 6 Luna" --tasks lock-order/abba_2lock --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/gpt-dynamic_m --allow-missing-tools
```

### Kimi

```sh
PYTHONPATH=python python -m skelnet run --arm G0 --model "Kimi" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --out experiments/stage0/kimi-g0
PYTHONPATH=python python -m skelnet run --arm REFINE --model "Kimi" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/kimi-refine
PYTHONPATH=python python -m skelnet run --arm STATIC --model "Kimi" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/kimi-static --allow-missing-tools
PYTHONPATH=python python -m skelnet run --arm DYNAMIC --model "Kimi" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/kimi-dynamic --allow-missing-tools
PYTHONPATH=python python -m skelnet run --arm SKEL --model "Kimi" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0/kimi-skel
PYTHONPATH=python python -m skelnet run --arm CIR --model "Kimi" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0/kimi-cir
PYTHONPATH=python python -m skelnet run --arm DYNAMIC_M --model "Kimi" --tasks lock-order/abba_2lock --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/kimi-dynamic_m --allow-missing-tools
```

### DeepSeek Flash

```sh
PYTHONPATH=python python -m skelnet run --arm G0 --model "DeepSeek Flash" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --out experiments/stage0/deepseek-g0
PYTHONPATH=python python -m skelnet run --arm REFINE --model "DeepSeek Flash" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/deepseek-refine
PYTHONPATH=python python -m skelnet run --arm STATIC --model "DeepSeek Flash" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/deepseek-static --allow-missing-tools
PYTHONPATH=python python -m skelnet run --arm DYNAMIC --model "DeepSeek Flash" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/deepseek-dynamic --allow-missing-tools
PYTHONPATH=python python -m skelnet run --arm SKEL --model "DeepSeek Flash" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0/deepseek-skel
PYTHONPATH=python python -m skelnet run --arm CIR --model "DeepSeek Flash" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0/deepseek-cir
PYTHONPATH=python python -m skelnet run --arm DYNAMIC_M --model "DeepSeek Flash" --tasks lock-order/abba_2lock --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/deepseek-dynamic_m --allow-missing-tools
```

### Qwen

```sh
PYTHONPATH=python python -m skelnet run --arm G0 --model "Qwen" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --out experiments/stage0/qwen-g0
PYTHONPATH=python python -m skelnet run --arm REFINE --model "Qwen" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/qwen-refine
PYTHONPATH=python python -m skelnet run --arm STATIC --model "Qwen" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/qwen-static --allow-missing-tools
PYTHONPATH=python python -m skelnet run --arm DYNAMIC --model "Qwen" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/qwen-dynamic --allow-missing-tools
PYTHONPATH=python python -m skelnet run --arm SKEL --model "Qwen" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0/qwen-skel
PYTHONPATH=python python -m skelnet run --arm CIR --model "Qwen" --tasks "$TASKS" --reps 1 --rounds 4 --stage 0 --hint h1 --out experiments/stage0/qwen-cir
PYTHONPATH=python python -m skelnet run --arm DYNAMIC_M --model "Qwen" --tasks lock-order/abba_2lock --reps 1 --rounds 4 --stage 0 --hint h1 --cache-dir experiments/stage0/cache --first-round require-cache --out experiments/stage0/qwen-dynamic_m --allow-missing-tools
```

Expected per run: a `MANIFEST.json` with `status: "complete"`,
`protocol_check: "pass"`, `hint: "h1"`, `stage: 0`, and four cells (the
`DYNAMIC_M` smoke has one). The `REFINE`/`STATIC`/`DYNAMIC`/`DYNAMIC_M` runs must
show their first call as a cache hit (`--first-round require-cache` fails the
run otherwise). **Stop** if any run exits non-zero, if
`MANIFEST.status != "complete"`, or if more than 5% of cells have
`status: "error"`; hand the failing run directory to the coordinator.

## 5. Summaries

```sh
PYTHONPATH=python python -m skelnet stop-check experiments/stage0/*-*/ --look 0 --stage 0 --budget-file experiments/budget.json --json > experiments/stage0/look0.json
PYTHONPATH=python python -m skelnet stop-check experiments/stage0/*-*/ --look 0 --stage 0 --budget-file experiments/budget.json > experiments/stage0/look0.md
PYTHONPATH=python python -m skelnet report experiments/stage0/*-*/ --look 0 --out experiments/stage0/report
```

Expected: the Look-0 table has one row per model with `truncation` below 2%
(marked `**` above 2%), no `unavailable` layer spikes, and the ledger check is
`consistent: true`. **Stop** if any model's `truncation_flag` is set
(`transport_truncated` above 2%), if `identity_error` is true, or if the ledger
check is inconsistent; hand `look0.json` to the coordinator.

## 6. lockbud false-positive quantification

```sh
PYTHONPATH=python python -m skelnet tools fp-check --tasks all --out experiments/stage0/fpcheck
```

Expected: `experiments/stage0/fpcheck/FP_CHECK.json` with `summary.clippy` and
`summary.lockbud`. This can take a while (it builds every task's fixed/buggy
programs). **Stop** only on a crash; a high false-positive rate is a result, not
an error.

## Files to hand back to the coordinator

Return these (paths are repository-relative):

- `experiments/stage0/probe/PROBE.json` — key presence is `true` by
  construction; the file contains no key value.
- `experiments/stage0/look0.json` and `experiments/stage0/look0.md`.
- `experiments/stage0/report/REPORT.md` and `experiments/stage0/report/report.json`.
- Each `experiments/stage0/<model>-*/MANIFEST.json` and `SUMMARY.json`.
- The `experiments/stage0-smoke/*/` reasoning check output (step 3).
- `experiments/stage0/fpcheck/FP_CHECK.json` (and `FP_CHECK.md` if wanted).

Before sending anything, check it for secrets and absolute paths:

- Do **not** send `.env`, `experiments/budget.json`, or any `audit.jsonl` /
  `evidence/` / `raw/` file: `requests.jsonl` stores a reasoning hash by
  default, but audit/evidence/raw may carry model text or key-adjacent data.
- `MANIFEST.json`, `SUMMARY.json`, `PROBE.json`, and the Look-0/report JSON
  contain no API keys and no absolute paths; inspect any failure output for a
  machine path before pasting it.
