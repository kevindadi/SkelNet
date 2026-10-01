# Protocol deviations

Any deviation from the frozen protocol in `experiments/protocol.json` (after it
was frozen) is recorded here, one entry per deviation: what changed, why, and
which experiment cells were affected. This file starts empty at freeze time.

## D-9c-1 — relative oracle paths invalidate the first Stage-0 round (2026-09-30)

- **What changed:** the oracle now resolves every path it hands to a subprocess.
  `cli.cmd_run` resolves `--out`, `--budget-file`, `--cache-dir` and
  `--replay-from` before use; `cmd_eval`, `oracle calibrate`, `tools fp-check`,
  `report` and `models probe` resolve their path arguments the same way; and
  `rusttools.runner.ToolRunner.run` normalizes `cwd` and a path-like `cmd[0]` to
  absolute paths against the *process* working directory (never the child's).
  The MANIFEST keeps recording the strings the user passed for `budget_file`,
  `cache_dir` and `replay_from`.
- **Why:** Stage 0 was first run on 2026-09-30 with relative `--out` paths
  (`experiments/stage0/<model>-<arm>`). The oracle built the probe at
  `workdir/target/debug/probe` and then ran it with `cwd=workdir`; because both
  the binary path and `cwd` were relative, the child re-resolved the binary
  against the new `cwd` and never found it. Every cell showed O2 `fail/crash`
  (`No such file or directory: '.../target/debug/probe'`), O3
  `shuttle_unsupported`, and O4 `not_run`; the DYNAMIC/DYNAMIC_M feedback loops
  saw the same crash/unsupported output, so those cells' generation was itself
  polluted. The defect had escaped the test suite because tests use pytest's
  absolute `tmp_path`.
- **Affected cells:** the entire first Stage-0 round — 14 run directories
  (7 GPT 6 Luna + 7 Kimi) plus the 2 step-3 smoke runs; the stage-0 ledger had
  spent **104 requests** (172,086 input / 143,650 output / 101,441 reasoning).
  All of it is void.
- **Handling:** the defect is fixed in round 9c (see `COMMANDS.md`, "Stage 0
  重新开始"); the old data is archived to
  `experiments/stage0-void-20260930/` (owner action, commands in `COMMANDS.md`)
  and never mixed with the new Stage 0. The ledger is replaced with a fresh
  `budget.json` from the template.
- **Paper impact:** Stage 0 is a pilot only; no Stage 1–3 data exists yet. The
  coordinator updates the models table and the threats-to-validity section.

## D-9c-2 — Kimi moves from `kimi-k3` to `kimi-k2.7-code` (2026-09-30)

- **What changed:** the experiment's Kimi model id is now `kimi-k2.7-code`
  (was `kimi-k3`). The channel is unchanged: Moonshot direct, OpenAI-compatible
  Chat Completions, `https://api.moonshot.cn/v1`, key `MOONSHOT_API_KEY`. The
  model cannot disable thinking, so the channel always sends
  `extra_body={"thinking": {"type": "enabled"}}`; `reasoning_effort` is not used
  on this channel (the protocol's Kimi row now records `reasoning_effort: null`),
  and no `temperature`/`top_p`/`n`/penalty parameters are sent. The old
  `kimi-k3` entry is kept as a **blocked** diagnostic (`role=diagnostic`,
  `status=blocked`, `blocked_reason="replaced by kimi-k2.7-code in round 9c
  (cost and behaviour gap)"`), so a run that names it is refused rather than
  silently remapped.
- **Why:** `kimi-k3` was materially more expensive and behaved differently from
  the other three comparison models; `kimi-k2.7-code` is the intended
  code-generation model.
- **Affected cells:** none in Stage 1–3 (this happens before any Stage 1 data).
  The first Stage-0 round is void under D-9c-1 regardless. `protocol.json` and
  `PROTOCOL.md` are regenerated (`protocol build` → `protocol render`).
- **Paper impact:** the models table now lists `kimi-k2.7-code`; the coordinator
  updates any cost/behaviour discussion.

## D-9d-1 — SKEL/CIR Rust stage had too few calls (2026-09-30, round 9d, F1)

- **Evidence in Stage 0 (main@03dbfe3):** with `--rounds 4 --call-budget 5` the
  skeleton stage took `min(rounds, B-1) = 4` calls, leaving the Rust stage a
  single call and no `rust_fix`. Of the 16 SKEL cells, the 5 that used all four
  skeleton rounds had exactly one Rust call; 3 were `O1 no_build`
  (`deepseek`/`gpt`/`kimi` on `partial_deadlock_bystander` /
  `atomic_lost_update`) and 1 was `O1 policy_violation`. Baselines always had a
  generation plus up to four feedback/fix calls.
- **Fix:** the llm-mode skeleton stage is capped at `min(rounds, call_budget-2)`
  (>=2 Rust calls); `--rust-mode codegen` keeps `min(rounds, call_budget-1)`.
  `protocol.json` records `run_params.skeleton_rounds_rule`.
- **Affected cells:** none in Stage 1–3; this is before any Stage 1 data. Stage 0
  is retained as pilot diagnostics only and enters no test.

## D-9d-2 — SKEL Rust prompt lacked the policy rules (2026-09-30, round 9d, F2)

- **Evidence:** `rust_generation_v2.md` (G0), `rust_from_cir_v3.md` (CIR) and
  `rust_compile_fix_v1.md` state the O1 policy (no `sleep`/`yield_now`, no
  `unsafe`/`#![feature]`, no external crates); `rust_from_skel_v2.md` did not.
  GPT and Qwen SKEL on `partial_deadlock_bystander` were `O1 policy_violation`
  (`yield_now` added to gold's busy-wait).
- **Fix:** new `rust_from_skel_v3.md` (route `("SKEL","rust")`) adds the O1
  policy rules, the busy-wait rule, and the `scope` translation; a rule-table
  test asserts the three generation prompts agree. `rust_from_skel_v2.md` is
  kept on disk.
- **Fix-round addendum (round 9d review):** the shared policy now lives in a
  neutral `rust_runtime_api_v2.md` appended to **every** Rust-stage route, so
  all arms receive the same runtime note; the generation prompts no longer
  mention `thread::Builder`.
- **Affected cells:** none in Stage 1–3; before any Stage 1 data.

## D-9d-3 — `thread::scope` breaks Shuttle coverage (2026-09-30, round 9d, F3)

- **Evidence:** Shuttle's transform marks `std::thread::scope` unsupported, so
  the O3 layer falls back to Miri only (`oracle_complete=false`). Kimi SKEL ×3
  and Qwen SKEL ×2 cells were `O3 shuttle_unsupported`; baselines used
  `thread::scope` 0/64, SKEL 8/16. This also violates the reference-program
  convention (no `thread::scope`).
- **Fix:** `rust_from_skel_v3.md` (new) and `rust_from_cir_v4.md` (new, route
  `("CIR","rust")`) state that `scope { spawn .. }` is translated to
  `std::thread::spawn` + `join` in order.
- **Fix-round addendum (round 9d review):** the `thread::scope` prohibition was
  moved out of the SKEL/CIR prompts into the shared `rust_runtime_api_v2.md`
  appendix, which every Rust-stage route includes; it no longer names the
  schedule explorer, so no group learns about the judge that the others do not.
- **Affected cells:** none in Stage 1–3; before any Stage 1 data.

## D-9d-4 — instrumenter did not recognize `thread::Builder` (2026-10-01, round 9d, F4)

- **Evidence:** `concir-instrument` reported `instrument_unsupported`
  ("residual spawn: .spawn(") for `thread::Builder::new()...spawn(..)`, so O4 was
  excluded from the conjunction. All 9 such Stage-0 cells were Qwen
  G0/REFINE/STATIC/DYNAMIC/DYNAMIC_M; their `ok` cells therefore bypassed O4.
- **Fix:** `crates/concir/src/instrument.rs` recognizes
  `Builder::new()[.name(..)][.stack_size(..)].spawn(closure)` (and imported
  `Builder`/`thread::Builder`) and rewrites it to
  `crate::cir_trace::builder_spawn`, which returns `io::Result<JoinHandle>` so a
  trailing `.unwrap()`/`.expect()` still compiles.
- **Affected cells:** none in Stage 1–3; before any Stage 1 data. The 9 Stage-0
  programs are copied into `python/tests/fixtures/round09d/builder_spawns/` as a
  read-only regression fixture.

## D-9d-5 — long generations need streaming (2026-10-01, round 9d, F5)

- **Evidence:** Qwen (`dashscope-direct`) and Kimi (`moonshot-direct`) generate
  ~32k output tokens (mostly reasoning); with `stream=False` the whole body must
  arrive inside the 300 s timeout, and `complete()` failed after 3 × 300 s
  (`wall_ms≈904,000`). 7 Stage-0 cells (6 Qwen, 1 Kimi) were `APITimeoutError`;
  the missing data was completed with a transient streaming override and 3 Qwen
  baseline cells then had `first_round_miss` downstream of a timed-out `G0`.
- **Fix:** the Qwen and Kimi `ModelSpec`s are `stream=True`; `DirectChatClient`
  already sends `stream_options={"include_usage": True}` and records usage,
  `finish_reason` and `reasoning_content` identically to the non-stream path.
  DeepSeek (`deepseek-direct`) had no timeout in Stage 0; its longest recorded
  single call was ≈ 301 s (2 truncation attempts summed), so it is left
  unchanged per the round-9d task sheet.
- **Fix-round addendum (round 9d review):** `stream` is now part of the frozen
  protocol (`models[*].stream` in `protocol.json` and the `PROTOCOL.md` Models
  table), so a transport drift such as flipping Qwen's `stream` back to `False`
  makes `protocol check` exit 1.
- **Affected cells:** none in Stage 1–3; before any Stage 1 data. Stage 0's
  7 completed cells used a mixed transport and stay pilot-diagnostic only.

## D-9e-1 — Kimi replaced by the Cursor Agent (2026-10-01, round 9e)

- **What changed:** the experimental model set now runs the **Cursor Agent**
  (registry id `cursor-agent`, Cursor) instead of **Kimi** (`kimi-k2.7-code`,
  Moonshot direct). Because the Cursor agent SDK requires its own model selector,
  the experiment calls this model "Cursor Agent" rather than reusing the SDK's
  `composer-2.5` id (that string stays internal to `CursorAgentClient`). A new
  `cursor` channel and `python/skelnet/cursor.py` (`CursorAgentClient`) drive the
  Cursor agent SDK; the Kimi `ModelSpec` stays **available** but is no longer one
  of the experimental models (so old run directories that name `Kimi` can still
  be replayed, while the frozen model set excludes it).
  `experiments/protocol.json` and `PROTOCOL.md` are regenerated
  (`protocol build` → `protocol render`); the new `protocol.json` sha256 is
  `7a881ea57e19019b960c7df7c49bd43410a27174ce320e4a0b14212c1959ca60`.
- **Why:** Kimi was too slow to keep the four-model grid on schedule. In Stage 1
  its `G0` run took ≈78 min for 72 cells (median LLM wall 32.3 s, max 350.7 s)
  versus DeepSeek's ≈43 min (median 16.8 s); `kimi-skel` was still incomplete
  after ≈90 min. Owner decision (2026-10-01).
- **Comparability caveat:** the Cursor Agent runs through the Cursor *agent* SDK,
  not a stateless chat endpoint. Its context is partly unobservable and its token
  usage/cost are server-reported per agent turn, so `budget_used.tokens` and
  `cost` are **not directly comparable** to the direct-API models. This is
  recorded as a threats-to-validity item; the comparison of primary metrics
  (`functional_ok` and the O1–O4 layers) is unaffected because every arm is
  scored by the same oracle.
- **Affected cells:** the Stage 1 Kimi runs are abandoned — `kimi-g0`
  (`complete`, 72 cells) and `kimi-skel` (incomplete, 25/72). They are retained
  on disk as pilot-diagnostic only and enter no test. The DeepSeek, GPT 6 Luna
  and Qwen runs are unaffected. Stage 0 Kimi runs are pilot-diagnostic only.
- **Handling:** the remaining Stage 1 grid is run for the other three models
  first (in progress); the Cursor Agent arms are launched with the same task set
  and flags. The stage-1 cache directory for the new model is
  `experiments/stage1/cache_cursor`.
- **Paper impact:** the models table lists the Cursor Agent; the coordinator
  updates the cost/behaviour discussion and the threats-to-validity section.
