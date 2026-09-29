# `tiny/` expected values (hand-derived)

Two models (DeepSeek Flash `deepseek-flash`, GPT 6 Luna `gpt-6-luna`), three
tasks, three reps, three arms.  The cells were generated from the hand-authored
matrices below by `make_tiny.py`; **none** of the numbers in this file were
produced by `skelnet.report` or `skelnet.stats`.

Outcome codes: `T` ok, `F` fail, `S` skipped, `E` error, `N`
`functional_ok: null`.

| task | tier | origin |
| --- | --- | --- |
| `lock-order/abba_2lock` | L1 | classic |
| `condvar/lost_wakeup` | L2 | classic |
| `semaphore/permits` | L3 | disguised |

The three special cells are all at DeepSeek, `condvar/lost_wakeup`, rep 0:
`G0 = S`, `STATIC = E`, `SKEL = N`.

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

## pass@1 of `ok` (included cells; `S`/`E` excluded, `N` counts as not ok)

| arm | DeepSeek | GPT | pooled |
| --- | --- | --- | --- |
| G0 | 4/8 = 50.0 | 5/9 = 55.6 | 9/17 = 52.9 |
| STATIC | 4/8 = 50.0 | 5/9 = 55.6 | 9/17 = 52.9 |
| SKEL | 7/9 = 77.8 | 6/9 = 66.7 | 13/18 = 72.2 |

`Δ = SKEL − G0` pooled `= 72.22 − 52.94 = +19.28 pp` (rounded `+19.3`).
`Δ = SKEL − STATIC` is the same `+19.3 pp`.

Sensitivity (`O1∧O2∧O3`): G0 11/17 = 64.7; STATIC 11/17 = 64.7; SKEL
14/18 = 77.8.  (The one `design` and one `monitor` failure per control are
O4-only, so they count as sensitivity successes.)

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

Pooled G0 pass@3 = 1.0.  `SKEL pass@1 − G0 pass@3 = 72.22 − 100 = −27.8 pp`.

## McNemar (SKEL vs G0), stratified by model

Only units present in both arms count (`deepseek/lost_wakeup/0` is dropped
because G0 is skipped).

- DeepSeek: b = 4, c = 1
- GPT: b = 3, c = 2
- merged: b = 7, c = 3

Exact two-sided: `X ~ Bin(10, 1/2)`,
`P(X ≤ 3) = (1 + 10 + 45 + 120)/1024 = 176/1024 = 0.171875`;
`p = min(1, 2·0.171875) = 0.34375`.

`SKEL vs STATIC` has the same b/c (the dropped unit is the STATIC error), so
`p = 0.34375` as well.

## Failure layer distribution (first failing layer; % of included cells)

Categories: G0 = [build, deadl, hang, output, policy, other, design, monitor]
assigned to its eight failing cells in reading order; STATIC = [output, deadl,
build, hang, monitor, other, policy, design]; SKEL = [deadl, output, design,
hang].

| arm | build | policy | hang | output | deadl. | other | design | monitor | deadlock rate | false acc. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2/17 = 11.8 | 0/17 = 0.0 |
| STATIC | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2/17 = 11.8 | 0/17 = 0.0 |
| SKEL | 0 | 0 | 1 | 1 | 1 | 0 | 1 | 0 | 2/18 = 11.1 | 0/18 = 0.0 |

(deadlock rate counts every cell with an O2 `hang` or O3 `deadlock`; false acc.
is `accepted ∧ ¬ok`, and no cell is accepted without being ok.)

## Anytime (cumulative `ok` at call `b`)

G0 and STATIC produce their final program at call 1; SKEL at call 2
(`skel_calls = 1` plus one Rust call).

| arm | b=1 | b=2 | b=3 | b=4 | b=5 | n |
| --- | --- | --- | --- | --- | --- | --- |
| G0 | 9/17 = 0.529 | same | same | same | same | 17 |
| STATIC | 9/17 = 0.529 | same | same | same | same | 17 |
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
(`deadlock = O2 hang or O3 deadlock`):

| | oracle deadlock | oracle not deadlock |
| --- | --- | --- |
| lockbud `fail` | 0 | 8 |
| lockbud `pass` | 2 | 7 |

Recall = 0/2 = 0.0; unavailable = 0.
