# Refactor report

Running log for the SkelNet refactor. One section per phase (P0–P7). Each section
records: what changed, the test command(s) and result summary, and deviations /
open questions.

---

## P0 — workspace skeleton, secrets hygiene

### Changes

- Added `.gitignore` ignoring `.env`, `.env.*` (negating `!.env.example`), plus
  Python caches, Rust `target/`, insta pending snapshots, experiment raw layer,
  transient logs, and OS/editor files.
- Copied `ConcPlanVerify/.env` → `SkelNet/.env` (never printed, never tracked).
- Added `.env.example` containing only key names:
  `DEEPSEEK_API_KEY`, `OPENCODE_API_KEY`, `CURSOR_API_KEY`, `DASHSCOPE_API_KEY`.
- Added `rust-toolchain.toml` (`nightly-2026-09-04`, `miri`, `rust-src`), matching ConcIR.
- Added `docs/MIGRATION.md` initial draft with source commit SHAs.
- Added `README.md` skeleton.

### §1.2 checks (outputs)

Command: `git check-ignore -v .env`

```
.gitignore:2:.env	.env
```

Command: `git ls-files | grep -E '(^|/)\.env$'`

```
(no output)
```

Command: `git diff --cached | grep -nE '(sk-|key-)[A-Za-z0-9_-]{16,}'`

```
(no output)
```

### Deviations / Open questions

- None at this phase.

---
