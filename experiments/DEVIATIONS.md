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
