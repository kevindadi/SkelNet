# `tiny/` expected values (hand-derived)

Two models (DeepSeek Flash `deepseek-flash`, GPT 6 Luna `gpt-6-luna`), three
tasks, three reps, three arms.  The cells were generated from the hand-authored
matrices below by `make_tiny.py`; the counts in this file were derived by hand
from those matrices, not by `skelnet.report` or `skelnet.stats`.  (The
bootstrap confidence intervals are the one exception: they are produced by the
pre-registered cluster bootstrap and are not hand-computed.)

Outcome codes: `T` ok, `F` fail, `S` skipped, `E` error, `N`
`functional_ok: null`.

| task | tier | origin |
| --- | --- | --- |
| `lock-order/abba_2lock` | L1 | classic |
| `condvar/lost_wakeup` | L2 | classic |
| `semaphore/permits` | L3 | disguised |

The three special cells are all at DeepSeek, `condvar/lost_wakeup`, rep 0:
`G0 = S` (excluded), `STATIC = E` (counted as unsuccessful, included),
`SKEL = N` (included, counts as unsuccessful).

## Matrices

`G0`

| model | abba_2lock | lost_wakeup | permits |
| --- | --- | --- | --- |
| DeepSeek | T F T | **S** F T | T F F |
| GPT | F T T | T F F | T F T |

`STATIC`

| model | abba_2lock | lost_wakeup | permits |
| --- | --- | --- | --- |
| DeepSeek | F T T | **E** F T | F T F |
| GPT | T T F | F T F | F T T |

`SKEL`

| model | abba_2lock | lost_wakeup | permits |
| --- | --- | --- | --- |
| DeepSeek | T T F | **N** T T | T T T |
| GPT | T F T | T T F | T T F |

## pass@1 of `ok` (included cells; `S` excluded, `E` and `N` count as not ok)

| arm | DeepSeek | GPT | pooled |
| --- | --- | --- | --- |
| G0 | 4/8 = 50.0 | 5/9 = 55.6 | 9/17 = 52.9 |
| STATIC | 4/9 = 44.4 | 5/9 = 55.6 | 9/18 = 50.0 |
| SKEL | 7/9 = 77.8 | 6/9 = 66.7 | 13/18 = 72.2 |

The main-table `Δ` is the paired risk difference (D8-7), i.e. `(b − c) / N`:
`SKEL − G0 = (7 − 3)/17 = +23.5 pp`; `SKEL − STATIC = (7 − 3)/18 = +22.2 pp`.
(The difference of the pooled rates, `72.2 − 52.9 = +19.3` and
`72.2 − 50.0 = +22.2`, uses different denominators and is not the table Δ.)

Sensitivity (`O1∧O2∧O3`): G0 11/17 = 64.7; STATIC 11/18 = 61.1; SKEL
14/18 = 77.8.  (The one `design` and one `monitor` failure per arm are O4-only,
so they count as sensitivity successes.)

## G0 pass@3

Per `(model, task)`, over the included G0 reps (`n`); `deepseek/lost_wakeup`
has `n = 2`, so `k = min(3, n) = 2`.

| model | task | n | c | pass@3 |
| --- | --- | --- | --- | --- |
| deepseek | abba_2lock | 3 | 2 | 1 |
| deepseek | lost_wakeup | 2 | 1 | 1 |
| deepseek | permits | 3 | 1 | 1 |
| gpt | abba_2lock | 3 | 2 | 1 |
| gpt | lost_wakeup | 3 | 1 | 1 |
| gpt | permits | 3 | 2 | 1 |

Pooled G0 pass@3 = 1.0.  `SKEL pass@1 − G0 pass@3 = 72.2 − 100 = −27.8 pp`.

## McNemar (stratified by model)

Only units present in both arms count.  For `SKEL − G0`, `deepseek/lost_wakeup/0`
is dropped (G0 skipped); for `SKEL − STATIC` the same unit is dropped (STATIC
error).

- DeepSeek: b = 4, c = 1
- GPT: b = 3, c = 2
- merged: b = 7, c = 3

Exact two-sided: `X ~ Bin(10, 1/2)`,
`P(X ≤ 3) = (1 + 10 + 45 + 120)/1024 = 176/1024 = 0.171875`;
`p = min(1, 2·0.171875) = 0.34375`.  Both comparisons give `p = 0.34375`.

## Failure layer distribution (first failing layer)

Categories: G0 = [build, deadl, hang, output, policy, other, design, monitor]
assigned to its eight failing cells in reading order; STATIC = [output, deadl,
build, hang, monitor, other, policy, design]; SKEL = [deadl, output, design,
hang].

| arm | build | policy | hang | output | deadl. | other | design | monitor | deadlock rate | false acc. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2/17 = 11.8 | 0/17 = 0.0 |
| STATIC | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2/18 = 11.1 | 0/18 = 0.0 |
| SKEL | 0 | 0 | 1 | 1 | 1 | 0 | 1 | 0 | 2/18 = 11.1 | 0/18 = 0.0 |

The error cell (STATIC) and the null cell (SKEL) have no failing layer, so they
fall in the Markdown-only “other” bucket (1 each).

## Anytime (cumulative `ok` at call `b`)

G0 and STATIC produce their final program at call 1; SKEL at call 2
(`skel_calls = 1` plus one Rust call).

| arm | b=1 | b=2 | b=3 | b=4 | b=5 | n |
| --- | --- | --- | --- | --- | --- | --- |
| G0 | 9/17 = 0.529 | same | same | same | same | 17 |
| STATIC | 9/18 = 0.500 | same | same | same | same | 18 |
| SKEL | 0/18 = 0.000 | 13/18 = 0.722 | same | same | same | 18 |

## Coverage (per included cell)

| arm | instrument | shuttle unsup. | miri unsup. | no concurrency | compile unavail. | incomplete | null |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| STATIC | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SKEL | 0 | 0 | 0 | 1 | 0 | 1 | 1 |

(The DeepSeek SKEL `abba_2lock` rep 0 cell carries `no_concurrency`; the null
cell is incomplete.)

## Lockbud 2×2 (STATIC first version joined to the G0 oracle)

The STATIC call-1 lockbud status is generated deterministically from
`hash("lockbud", task, rep, model) % 100 < 45`.  Joining with the G0 oracle
(`deadlock = O2 hang or O3 deadlock`) over all 18 included STATIC cells:

| | oracle deadlock | oracle not deadlock |
| --- | --- | --- |
| lockbud `fail` | 0 | 9 |
| lockbud `pass` | 2 | 7 |

Recall = 0/2 = 0.0; FP on oracle-ok = 9/(9+7) = 0.5625; unavailable = 0;
excluded (v1 did not compile) = 0.
