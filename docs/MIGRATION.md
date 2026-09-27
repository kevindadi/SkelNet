# Migration record

This repository is a curated extraction from two read-only source repositories.
History (experiments, notes, paper drafts, repair tooling) stays in the originals;
this file records exactly what was brought over, what was deleted, and why.

## Source repositories

| Source | Path | Commit SHA |
| --- | --- | --- |
| ConcPlanVerify | `/Users/kevin/local-repos/ConcPlanVerify` | `8bf9fa49b0300e8be00fc5c0b61a98cd8d5aa53f` |
| ConcIR | `/Users/kevin/local-repos/ConcIR` | `a35dc867d6327c772d48bd7c0473a6606fcc467a` |

Both sources are read-only for this migration: they are never modified, committed
to, or tagged.

## P0: workspace skeleton

Created:

- `.gitignore` (ignores `.env`, `.env.*`, except `!.env.example`)
- `.env` copied from `ConcPlanVerify/.env` (ignored, never tracked, never printed)
- `.env.example` (key names only, no values)
- `rust-toolchain.toml` (nightly-2026-09-04 + miri + rust-src, from ConcIR)

Details of subsequent phases are appended below as they are completed.

## P1: ConcIR + runtime (pending)

## P2-P7 (pending)
