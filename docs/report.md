# Statistics and reporting (round 8)

`python -m skelnet report` and `python -m skelnet stop-check` read run
directories and produce the experiment-plan metrics, the paper tables, and the
staged stopping decisions.  Everything is pure Python (no SciPy/NumPy), reads
only run files and the JSON files named on the command line, never calls the
oracle or a model, and never writes an absolute path or a key into an artifact.

## Loading (`report.load_runs`)

Every positional argument must be a run directory carrying `MANIFEST.json`;
otherwise the command exits with code 2 and lists the offender.  Cells are read
from `MANIFEST.tasks.selected × MANIFEST.reps` (stale cells from another task
are ignored) and each is validated with `schema.validate_cell`.

- The analysis label is the `arm` (`D8-4`), except `arm == "SKEL"` with
  `run_params.feedback_mode == "outcome_only"` (`SKEL-outcome`), `nocex`
  (`SKEL-nocex`) or `nomap` (`SKEL-nomap`).
- The primary metric `ok` is `oracle.functional_ok is True`; a `null`
  (unavailable tool, no Rust) counts as unsuccessful and is counted separately
  (`D8-1`).  The sensitivity metric is `functional_ok_no_o4` (`O1∧O2∧O3`).
  A non-zero count of `status == "unavailable"` layers adds a warning per
  layer/group, and `functional_ok: null` cells get a reason
  (`no_oracle`, `unavailable:<layer>`, `not_applicable`, `other`); coverage
  reports the group × reason counts.
- `status == "skipped"` cells are excluded and counted; `status == "error"`
  cells are kept and counted as unsuccessful (`D8-2`).  The report header and
  `report.json.counts` list included / skipped / error per group.
- A duplicated `(model_id, label, task, rep)` is an error unless
  `--allow-duplicates` (keep the last, warn).
- `hint`, `run_params.call_budget` / `token_budget` / `temperature_policy` /
  `seed_policy` and per-model `max_output_tokens` must agree across runs;
  `--allow-mixed` downgrades a mismatch to a header warning.
- Runs whose `MANIFEST.status` is not `complete` are listed in the header.

Derived per cell: the first failing oracle layer (`D8-14`), the call index of
the final program version (`D8-5`), billable tokens (`input + output`),
reasoning tokens, LLM wall time (`calls[].wall_ms`), in-group tool time (sum of
the top-level `compile_wall_ms` — G0 and SKEL/CIR — `history[].wall_ms`,
`rust_attempts[].compile_wall_ms`, `baseline.rounds[].compile_wall_ms` and
`baseline.rounds[].tools.*.wall_ms`; `null` when no such field exists, so a
group with no tool timing prints `--`), and oracle wall time (sum of layer
`wall_ms`).  Coverage flags (`D8-15`) read
`oracle.o3_tools` when present and otherwise parse the O3 `detail` text.

The task tier comes from the cell's `tier`; the task origin (`classic` /
`disguised` / `unknown`) is read from
`<root>/benchmarks/tasks/<task>/requirements.json`.

## Commands

```
python -m skelnet report <run_dirs...> [--table NAME ...] [--figure anytime]
                         [--format md|tex|both] [--out DIR] [--root DIR]
                         [--look 0|1|2|3] [--planned-units 880]
                         [--previous-look-units N | --previous-look-from FILE]
                         [--prices FILE] [--fp-check FILE] [--probe FILE]
                         [--bootstrap 10000] [--seed 20260928]
                         [--allow-mixed] [--allow-duplicates]
python -m skelnet stop-check <run_dirs...> --look {0,1,2,3}
                         [--planned-units 880]
                         [--previous-look-units N | --previous-look-from FILE]
                         [--prices FILE] [--budget-file FILE] [--stage N]
                         [--next-stage-units N] [--root DIR] [--json]
```

`--table` may repeat; `all` selects every table; `benchmark` needs no run
directory.  With `--out` the command writes `tables/*.tex`,
`figures/anytime.tex`, `data/anytime.csv`, `extra/*.tex`, `REPORT.md` (all
requested Markdown tables) and `report.json` (every number).  Without `--out`
the Markdown is printed to stdout.  When neither `--table`, `--figure` nor
`--out` is given the command keeps its pre-round-8 behaviour (the legacy
one-row-per-run `SUMMARY.json` table).  `--look 0` is descriptive only
(`Δ`/CI/`p` are `--`); `--look 1` computes the tests but writes the sequential
`α` as `--`; `--look 2/3` use the O'Brien-Fleming boundary.

`--prices FILE` is
`{"currency": "USD", "per_million": {"<model_id>": {"input": x, "output": y,
"cached_input": z}}}`.  A call's cost is `(input − cached)·input +
cached·cached_input + output·output`; reasoning is already inside `output`.
A missing model price prints `--` and warns.

## Tables

| `--table` | file | contents |
| --- | --- | --- |
| `main` | `tables/main.tex` | pass@1 per model and pooled; `SKEL − arm` paired `Δ`, cluster-bootstrap 95% CI and Holm-adjusted exact McNemar `p`; sensitivity column; the `G0 pass@3` row; Cochran's Q footnote |
| `tiers` | `tables/tiers.tex` | pooled pass@1 by tier and task origin |
| `design` | `tables/ingredients.tex` | parse@1, check@1, verified@1, verified@4, UNKNOWN, mean unmapped, verified∧¬ok for SKEL/CIR/SKEL-outcome |
| `failures` | `tables/failures.tex` | first failing layer/category, deadlock rate, false acceptance |
| `cost` | `tables/cost.tex` | mean calls, input/output/reasoning (k tokens), tokens per correct program, LLM seconds, tool seconds |
| `models` | `tables/models.tex` | family, model id, API, reasoning, Stage-0 probe truncation/seed |
| `benchmark` | `tables/benchmark.tex` | tasks per family and tier; boundary negatives |
| `coverage` | `extra/coverage.tex` | per-group coverage flags (`D8-15`) |
| `lockbud` | `extra/lockbud.tex` | reference false-positive/detection rates by family and the experiment 2×2 (pooled, per model, per family) with `no_g0` and three ratios (`D8-16`) |
| `tests` | `extra/tests.tex` | every comparison of both families, per-model and per-tier Δ/CI, the coverage-gated 7-group Cochran's Q, and Wilcoxon/A12/Cliff's δ for all ten comparisons |
| `numbers` | `extra/numbers.tex` | `\SNunits`, `\SNcalls`, `\SNtokens`, `\SNtruncpct`, `\SNincompletepct`, `\SNshuttleunsup`, `\SNinstrunsup`, `\SNlockbudfp`, `\SNlook`, `\SNalpha` |

The paper placeholders live in
`python/tests/fixtures/round08/paper_tables/`; `test_round08_latex.py` asserts
that the generated files keep their tabular spec, headers, rules, row labels
and `&` counts, and that they contain no `\PH`, `\TODO`, or absolute path.
The paper commands map directly:

```
report experiments/stage2-* --table main
report experiments/stage2-* --table tiers
report experiments/stage2-* --table design
report experiments/stage2-* --table failures
report experiments/stage2-* --table cost
report experiments/stage2-* --figure anytime
```

`anytime.tex`/`anytime.csv` use the conservative `D8-5` definition: a cell
counts as correct at call `b` only if its final program version was produced
within the first `b` calls **and** that final version is `ok` (G0 at call 1; a
baseline at its last `program` round; SKEL/CIR at their last `program` Rust
attempt).  Codegen runs are excluded.  This is a lower bound: a cell whose
final version is correct but which the in-group rule kept revising is counted
later.

## Statistics (`skelnet/stats.py`)

`pass_at_k`, `mcnemar_exact` / `stratified_mcnemar`, `holm`, `cochran_q` and
`chi2_sf` (regularized incomplete gamma), `wilcoxon_signed_rank` (exact for
`n ≤ 25` without ties, otherwise normal with tie and continuity corrections),
`a12` / `cliffs_delta`, `cluster_bootstrap_diff` (task-cluster resampling,
percentile CI), `obf_alpha_spent` / `obf_nominal_boundaries` (Armitage–
McPherson–Rowe recursion with composite Simpson integration and the
conditional density `Z_{k+1}|Z_k ~ N(ρ z, 1−ρ²)`), `normal_cdf` / `normal_ppf`.
The exact Wilcoxon distribution is counted by a rank-sum dynamic program, not
`2^n` enumeration.

- Paired unit: `(model, task, rep)`; `b` counts reference-ok/control-fail, `c`
  the reverse; `p = min(1, 2·P(X ≤ min(b,c)))` for `X ~ Bin(b+c, 1/2)`.
- `Δ` is the paired risk difference; the CI resamples tasks (10 000 draws,
  seed 20260928).
- Holm is applied separately to the two pre-registered families and
  monotone-corrected (`D8-8`).

## Staged stopping (`stop-check`)

Every look prints the loader warnings (duplicate cells, non-`complete`
manifests, unavailable layers, unclassified failing layers) and the per-group
included/skipped/error counts.

`--look 0` reports Stage-0 diagnostics (per-model calls, truncation with a `**`
flag above 2%, empty replies — visible output `output − reasoning ≤ 0` and no
error, `first_round_miss`, transport truncations, model identity errors,
unavailable layers, the coverage table), the per-group per-cell means and the
coverage table, the Stage-1 extrapolation (all four experimental models × the
six Stage-1 groups, falling back to the all-model average and noting it, with a
totals row), and the ledger check: the stage's `requests` (from
`--budget-file`, default `<root>/experiments/budget.json`; a missing file or
stage warns) must lie in `[Σ len(finish_reasons),
Σ len(finish_reasons) + Σ(transport_attempt − 1)]` over non-cache-hit calls.

`--look 1` is futility-only: it reports the SKEL-minus-best-baseline margin
from the shared 3 pp rule (futile below 3 pp) and the per-group failure-stage
decomposition.

`--look 2/3` evaluate the six success criteria of the plan: (1) all four main
Holm `p` below the O'Brien-Fleming nominal `α`; (2) SKEL better in at least 3/4
models per baseline; (3) positive SKEL − baseline on `L2∪L3`; (4) the four
sensitivity `Δ` share the main direction; (5) every main cluster-bootstrap 95%
CI excludes zero; (6) `SKEL − DYNAMIC_M` is reported (and a narrower claim is
suggested when DYNAMIC_M is significantly better).  At Look 2 the nominal `α` is
read at `t = paired units / --planned-units`; Look 2 is futile when the 3 pp
margin rule or an `L2∪L3` regression fires (`futility_reasons`), otherwise the
verdict is `success`, `futility`, or `continue`.

Look 3 is the final analysis.  It must be told the previous look's information
explicitly: `--previous-look-units N` or `--previous-look-from <Look-2
stop-check JSON>` (which reads the JSON's `units` field); without either it
exits 2.  The final boundary spends all remaining `α` at the real information
fraction `t_final = paired units / --planned-units` with the conditional
correlation `sqrt(t_prev / t_final)` (`t_prev = previous units /
--planned-units`).  A non-significant Look 3 is `no_success` (there is no next
look); the `main` table footnote (`Nominal alpha` / `Sequential boundary at
this look`) uses the same value.

## Decisions

`D8-1`–`D8-20` are implemented as tabled in the round-8 task.  In particular:
`ok` treats `null` as unsuccessful (`D8-1`); skipped cells are excluded and
error cells are kept (`D8-2`); pairing only uses units present in both arms and
its `n`/`missing` are reported (`D8-3`); costs count a cache-hit first call
against the group that replays it (`D8-12`); numbers are rounded before the
sign and use three significant digits for `p` (`D8-13`); the failure columns,
coverage flags, and lockbud join (with `no_g0`, recall, false positives on
`ok`, and per-model/per-family splits) follow `D8-14`/`D8-15`/`D8-16`; the
`G0 pass@3` row marks `(model, task)` pairs with `n < 3` (`D8-20`).
